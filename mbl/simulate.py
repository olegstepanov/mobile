"""mbl.simulate — COM-based pivot solver.

Computes center of mass from intermediate STL files, then binary-searches
for the pivot position on each arc bar that achieves the target equilibrium
angle.  Pure Python — no external dependencies beyond the standard library.
"""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import struct
from typing import TYPE_CHECKING

from mbl.arc_math import arc_y_at_x
from mbl.errors import MobileSimulationError
from mbl.perf import count, span
from mbl.resolve import ResolvedBranch, ResolvedLeaf, ResolvedTree

if TYPE_CHECKING:
    from mbl.config import MobileConfig


# ---------------------------------------------------------------------------
# Mesh COM helpers
# ---------------------------------------------------------------------------

def compute_com(stl_path: str) -> tuple[float, float, float, float]:
    """Compute volume-weighted center of mass from a binary STL file."""
    with span("simulate.compute_com"):
        with open(stl_path, "rb") as f:
            f.read(80)  # header
            (num_tris,) = struct.unpack("<I", f.read(4))
            count("simulate.compute_com.triangles", num_tris)

            vol_total = 0.0
            com_x = 0.0
            com_y = 0.0
            com_z = 0.0

            for _ in range(num_tris):
                data = f.read(50)  # 12 (normal) + 36 (3 vertices) + 2 (attrib)
                vals = struct.unpack("<12fH", data)

                v0 = (vals[3], vals[4], vals[5])
                v1 = (vals[6], vals[7], vals[8])
                v2 = (vals[9], vals[10], vals[11])

                vol = (
                    v0[0] * (v1[1] * v2[2] - v1[2] * v2[1])
                    - v0[1] * (v1[0] * v2[2] - v1[2] * v2[0])
                    + v0[2] * (v1[0] * v2[1] - v1[1] * v2[0])
                ) / 6.0

                vol_total += vol
                com_x += vol * (v0[0] + v1[0] + v2[0]) / 4.0
                com_y += vol * (v0[1] + v1[1] + v2[1]) / 4.0
                com_z += vol * (v0[2] + v1[2] + v2[2]) / 4.0

    if abs(vol_total) > 1e-10:
        com_x /= vol_total
        com_y /= vol_total
        com_z /= vol_total

    return com_x, com_y, com_z, abs(vol_total)


def equilibrium_angle_from_com(
    com_x: float,
    com_y: float,
    pivot_x: float,
    pivot_y: float,
) -> float:
    """Compute equilibrium tilt angle (degrees) from COM and pivot."""
    dx = com_x - pivot_x
    dy = pivot_y - com_y
    if dy <= 0:
        return 0.0
    return math.degrees(math.atan2(dx, dy))


# ---------------------------------------------------------------------------
# Tree traversal helpers
# ---------------------------------------------------------------------------

def _collect_branches(
    node: ResolvedTree,
    path: str,
    branches: dict[str, ResolvedBranch],
) -> None:
    """Walk the tree and collect all branch nodes by path label."""
    if isinstance(node, ResolvedLeaf):
        return

    label = path if path else "0"
    branches[label] = node

    if isinstance(node.left, ResolvedBranch):
        left_label = path + "L" if path else "L"
        _collect_branches(node.left, left_label, branches)

    if isinstance(node.right, ResolvedBranch):
        right_label = path + "R" if path else "R"
        _collect_branches(node.right, right_label, branches)


def _compute_target_angle(branch: ResolvedBranch, config: MobileConfig) -> float:
    """Compute target angle for a branch using the config's angle strategy."""
    angle_hint = branch.angle_hint
    if config.angle_strategy == "equilibrium":
        return 0.0
    elif config.angle_strategy == "hint":
        return angle_hint
    else:  # "blend"
        return (1.0 - config.blend_ratio) * angle_hint


# ---------------------------------------------------------------------------
# Tree patching
# ---------------------------------------------------------------------------

def _patch_tree(
    node: ResolvedTree,
    path: str,
    results: dict[str, dict],
) -> ResolvedTree:
    """Replace pivot_mm, pivot, angle_eq, angle on each branch from results."""
    if isinstance(node, ResolvedLeaf):
        return node

    label = path if path else "0"

    # Recurse into children first
    left_path = path + "L" if path else "L"
    right_path = path + "R" if path else "R"
    new_left = _patch_tree(node.left, left_path, results)
    new_right = _patch_tree(node.right, right_path, results)

    if label in results:
        r = results[label]
        pivot_mm = r["pivot_mm"]
        pivot = pivot_mm / node.arc.w
        angle = r["angle"]
        return replace(
            node,
            left=new_left,
            right=new_right,
            pivot_mm=pivot_mm,
            pivot=pivot,
            angle_eq=angle,
            angle=angle,
        )

    return replace(node, left=new_left, right=new_right)


# ---------------------------------------------------------------------------
# Pivot solver
# ---------------------------------------------------------------------------

def _solve_pivot(
    branch: ResolvedBranch,
    stl_path: Path,
    target_angle: float,
    config: MobileConfig,
) -> dict:
    """Find pivot_mm where equilibrium angle matches target, using binary search.

    The intermediate STL was generated with the origin at the arc midpoint
    (arc_w / 2).  ``compute_com()`` returns the center of mass in that
    coordinate system.

    For a trial ``pivot_mm``, the pivot's position in STL coordinates is::

        pivot_x = trial_pivot_mm - arc_w / 2
        pivot_y = arc_y_at_x(arc_w, arc_h, arc_w/2, pivot_x)

    The equilibrium angle is computed from the combined COM (STL body mass +
    child point masses at endpoints) and the trial pivot position.
    """
    arc_w = branch.arc.w
    arc_h = branch.arc.h
    midpoint = arc_w / 2.0

    # 1. Compute COM from STL mesh
    com_x, com_y, _com_z, volume = compute_com(str(stl_path))
    stl_mass = volume * config.density

    # 2. Child point masses at endpoints (only for sub-arc children).
    #    Direct leaves are already fused into the STL.
    left_x = -midpoint
    right_x = arc_w - midpoint
    left_y = arc_y_at_x(arc_w, arc_h, midpoint, left_x)
    right_y = arc_y_at_x(arc_w, arc_h, midpoint, right_x)

    left_point_mass = branch.left.weight if isinstance(branch.left, ResolvedBranch) else 0.0
    right_point_mass = branch.right.weight if isinstance(branch.right, ResolvedBranch) else 0.0

    # 3. Combined COM
    total_mass = stl_mass + left_point_mass + right_point_mass
    if total_mass < 1e-10:
        return {"pivot_mm": midpoint, "angle": 0.0, "converged": True, "iterations": 0}

    combined_com_x = (
        stl_mass * com_x + left_point_mass * left_x + right_point_mass * right_x
    ) / total_mass
    combined_com_y = (
        stl_mass * com_y + left_point_mass * left_y + right_point_mass * right_y
    ) / total_mass

    # 4. Binary search for pivot_mm
    lo = config.hole_tip_inset
    hi = arc_w - config.hole_tip_inset
    tolerance = config.sim_angle_tolerance_deg
    max_iters = config.sim_max_bisect_iterations

    best_pivot = midpoint
    best_angle = 0.0

    for iteration in range(max_iters):
        count("simulate.solve_pivot.iterations")
        trial = (lo + hi) / 2.0

        # Pivot position in STL coordinates
        pivot_x = trial - midpoint
        pivot_y = arc_y_at_x(arc_w, arc_h, midpoint, pivot_x)

        angle = equilibrium_angle_from_com(
            combined_com_x, combined_com_y, pivot_x, pivot_y
        )

        best_pivot = trial
        best_angle = angle

        if abs(angle - target_angle) < tolerance:
            return {
                "pivot_mm": trial,
                "angle": angle,
                "converged": True,
                "iterations": iteration + 1,
            }

        # If angle > target (COM too far right of pivot), move pivot right.
        if angle > target_angle:
            lo = trial
        else:
            hi = trial

    return {
        "pivot_mm": best_pivot,
        "angle": best_angle,
        "converged": False,
        "iterations": max_iters,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def simulate_mobile(
    tree: ResolvedTree,
    config: MobileConfig,
    stl_dir: Path,
) -> ResolvedTree:
    """Find pivot positions using center-of-mass computation from STL files.

    For each arc bar, computes the volume-weighted center of mass from its
    intermediate STL mesh (using the signed tetrahedra method), then
    binary-searches for the pivot position that produces the desired
    equilibrium tilt angle.

    Args:
        tree: Resolved tree with midpoint pivots and correct weights.
        config: Mobile configuration with solver parameters.
        stl_dir: Directory containing intermediate STL files (no holes).

    Returns:
        A new ResolvedTree with pivot positions and angles from the solver.

    Raises:
        MobileSimulationError: If an STL file is missing or a branch
            fails to converge.
    """
    if isinstance(tree, ResolvedLeaf):
        return tree

    # Collect tree structure
    branches: dict[str, ResolvedBranch] = {}
    _collect_branches(tree, "", branches)

    results: dict[str, dict] = {}

    for label, branch in branches.items():
        count("simulate.branch.count")
        stl_name = "arc-0.stl" if label == "0" else f"arc-{label}.stl"
        stl_path = stl_dir / stl_name
        if not stl_path.exists():
            raise MobileSimulationError(f"STL file not found: {stl_path}")

        target_angle = _compute_target_angle(branch, config)
        with span("simulate.solve_pivot"):
            result = _solve_pivot(branch, stl_path, target_angle, config)

        if not result["converged"]:
            raise MobileSimulationError(
                f"Branch '{label}' did not converge after {result['iterations']} "
                f"iterations (angle={result['angle']:.3f}, "
                f"target={target_angle:.3f})"
            )

        results[label] = result

    return _patch_tree(tree, "", results)
