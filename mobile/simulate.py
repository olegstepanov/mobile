"""mobile.simulate — COM-based pivot solver.

Computes center of mass from intermediate STL files, then binary-searches
for the pivot position on each arc bar that achieves the target equilibrium
angle.  Pure Python — no external dependencies beyond the standard library.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from mobile.arc_math import arc_y_at_x
from mobile.blender_pivot import compute_com, equilibrium_angle_from_com
from mobile.errors import MobileSimulationError
from mobile.resolve import ResolvedBranch, ResolvedLeaf, ResolvedTree

if TYPE_CHECKING:
    from mobile.config import MobileConfig


# ---------------------------------------------------------------------------
# Tree traversal helpers
# ---------------------------------------------------------------------------

def _collect_branches(
    node: ResolvedTree,
    path: str,
    branches: dict[str, tuple[ResolvedBranch, str]],
    tree_map: dict[str, dict[str, str | None]],
    depth_map: dict[str, int],
    depth: int,
) -> None:
    """Walk the tree and collect branch info, tree connectivity, and depths."""
    if isinstance(node, ResolvedLeaf):
        return

    label = path if path else "0"
    branches[label] = (node, label)
    depth_map[label] = depth

    left_child: str | None = None
    right_child: str | None = None

    if isinstance(node.left, ResolvedBranch):
        left_label = path + "L" if path else "L"
        left_child = left_label
        _collect_branches(node.left, left_label, branches, tree_map, depth_map, depth + 1)

    if isinstance(node.right, ResolvedBranch):
        right_label = path + "R" if path else "R"
        right_child = right_label
        _collect_branches(node.right, right_label, branches, tree_map, depth_map, depth + 1)

    tree_map[label] = {"left_child": left_child, "right_child": right_child}


def _compute_target_angle(branch: ResolvedBranch, config: MobileConfig) -> float:
    """Compute target angle for a branch using the config's angle strategy."""
    angle_hint = branch.angle_hint
    if config.angle_strategy == "equilibrium":
        return 0.0
    elif config.angle_strategy == "hint":
        return angle_hint
    else:  # "blend"
        return (1.0 - config.blend_ratio) * angle_hint


def _group_by_level(depth_map: dict[str, int]) -> list[list[str]]:
    """Group branch labels by depth, bottom-up (deepest first)."""
    if not depth_map:
        return []
    max_depth = max(depth_map.values())
    levels: list[list[str]] = []
    for d in range(max_depth, -1, -1):
        level = [label for label, dep in depth_map.items() if dep == d]
        if level:
            levels.append(level)
    return levels


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
    branches: dict[str, tuple[ResolvedBranch, str]] = {}
    tree_map: dict[str, dict[str, str | None]] = {}
    depth_map: dict[str, int] = {}
    _collect_branches(tree, "", branches, tree_map, depth_map, 0)

    results: dict[str, dict] = {}

    for label, (branch, _) in branches.items():
        stl_name = "arc-0.stl" if label == "0" else f"arc-{label}.stl"
        stl_path = stl_dir / stl_name
        if not stl_path.exists():
            raise MobileSimulationError(f"STL file not found: {stl_path}")

        target_angle = _compute_target_angle(branch, config)
        result = _solve_pivot(branch, stl_path, target_angle, config)

        if not result["converged"]:
            raise MobileSimulationError(
                f"Branch '{label}' did not converge after {result['iterations']} "
                f"iterations (angle={result['angle']:.3f}, "
                f"target={target_angle:.3f})"
            )

        results[label] = result

    return _patch_tree(tree, "", results)
