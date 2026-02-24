"""Unit tests for mobile.simulate — COM-based pivot solver."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from mobile.config import MobileConfig
from mobile.dsl import Arc
from mobile.errors import MobileSimulationError
from mobile.resolve import ResolvedBranch, ResolvedLeaf
from mobile.simulate import (
    _collect_branches,
    _compute_target_angle,
    _group_by_level,
    _patch_tree,
    _solve_pivot,
    simulate_mobile,
)


# ---------------------------------------------------------------------------
# Fixtures: small resolved trees for testing
# ---------------------------------------------------------------------------

def _leaf(label: str, weight: float = 1.0) -> ResolvedLeaf:
    """Create a minimal ResolvedLeaf for testing."""
    return ResolvedLeaf(
        label=label,
        space=None,  # type: ignore[arg-type]
        area=100.0,
        volume=200.0,
        weight=weight,
        scale=1.0,
        rotation=0.0,
    )


def _branch(
    left: ResolvedLeaf | ResolvedBranch,
    right: ResolvedLeaf | ResolvedBranch,
    arc_w: float = 100.0,
    angle_hint: float = 0.0,
) -> ResolvedBranch:
    """Create a minimal ResolvedBranch for testing."""
    return ResolvedBranch(
        left=left,
        right=right,
        arc=Arc(w=arc_w, h=10.0),
        weight=left.weight + right.weight,
        pivot=0.5,
        pivot_mm=arc_w / 2.0,
        angle_eq=0.0,
        angle_hint=angle_hint,
        angle=0.0,
    )


# ---------------------------------------------------------------------------
# Binary STL helpers for testing
# ---------------------------------------------------------------------------

def _write_binary_stl(path: Path, triangles: list[tuple[tuple, tuple, tuple]]) -> None:
    """Write a binary STL file from a list of triangle vertex tuples.

    Each triangle is ((x0,y0,z0), (x1,y1,z1), (x2,y2,z2)).
    Normal is set to (0,0,0) — compute_com ignores normals.
    """
    with open(path, "wb") as f:
        f.write(b"\0" * 80)  # header
        f.write(struct.pack("<I", len(triangles)))
        for v0, v1, v2 in triangles:
            # normal (ignored)
            f.write(struct.pack("<3f", 0.0, 0.0, 0.0))
            # vertices
            f.write(struct.pack("<3f", *v0))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            # attribute byte count
            f.write(struct.pack("<H", 0))


def _box_triangles(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> list[tuple[tuple, tuple, tuple]]:
    """Generate 12 triangles for an axis-aligned box from (x0,y0,z0) to (x1,y1,z1).

    Winding order is outward-facing (counter-clockwise from outside).
    """
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),  # bottom
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),  # top
    ]
    faces = [
        # bottom (z0)
        (v[0], v[2], v[1]), (v[0], v[3], v[2]),
        # top (z1)
        (v[4], v[5], v[6]), (v[4], v[6], v[7]),
        # front (y0)
        (v[0], v[1], v[5]), (v[0], v[5], v[4]),
        # back (y1)
        (v[2], v[3], v[7]), (v[2], v[7], v[6]),
        # left (x0)
        (v[0], v[4], v[7]), (v[0], v[7], v[3]),
        # right (x1)
        (v[1], v[2], v[6]), (v[1], v[6], v[5]),
    ]
    return faces


# ---------------------------------------------------------------------------
# _collect_branches
# ---------------------------------------------------------------------------


class TestCollectBranches:
    def test_single_branch(self) -> None:
        tree = _branch(_leaf("A"), _leaf("B"))
        branches: dict = {}
        tree_map: dict = {}
        depth_map: dict = {}
        _collect_branches(tree, "", branches, tree_map, depth_map, 0)

        assert set(branches.keys()) == {"0"}
        assert depth_map == {"0": 0}
        assert tree_map == {"0": {"left_child": None, "right_child": None}}

    def test_nested_tree(self) -> None:
        """Tree: root with left=branch(A,B), right=leaf(C)."""
        left_branch = _branch(_leaf("A"), _leaf("B"))
        tree = _branch(left_branch, _leaf("C"))
        branches: dict = {}
        tree_map: dict = {}
        depth_map: dict = {}
        _collect_branches(tree, "", branches, tree_map, depth_map, 0)

        assert set(branches.keys()) == {"0", "L"}
        assert depth_map == {"0": 0, "L": 1}
        assert tree_map["0"] == {"left_child": "L", "right_child": None}
        assert tree_map["L"] == {"left_child": None, "right_child": None}

    def test_full_binary_tree(self) -> None:
        """Tree: root with both children as branches."""
        left = _branch(_leaf("A"), _leaf("B"))
        right = _branch(_leaf("C"), _leaf("D"))
        tree = _branch(left, right)
        branches: dict = {}
        tree_map: dict = {}
        depth_map: dict = {}
        _collect_branches(tree, "", branches, tree_map, depth_map, 0)

        assert set(branches.keys()) == {"0", "L", "R"}
        assert depth_map == {"0": 0, "L": 1, "R": 1}
        assert tree_map["0"] == {"left_child": "L", "right_child": "R"}

    def test_leaf_returns_nothing(self) -> None:
        branches: dict = {}
        tree_map: dict = {}
        depth_map: dict = {}
        _collect_branches(_leaf("X"), "", branches, tree_map, depth_map, 0)
        assert branches == {}


# ---------------------------------------------------------------------------
# _compute_target_angle
# ---------------------------------------------------------------------------


class TestComputeTargetAngle:
    def test_equilibrium(self) -> None:
        branch = _branch(_leaf("A"), _leaf("B"), angle_hint=15.0)
        config = MobileConfig(angle_strategy="equilibrium")
        assert _compute_target_angle(branch, config) == 0.0

    def test_hint(self) -> None:
        branch = _branch(_leaf("A"), _leaf("B"), angle_hint=15.0)
        config = MobileConfig(angle_strategy="hint")
        assert _compute_target_angle(branch, config) == 15.0

    def test_blend(self) -> None:
        branch = _branch(_leaf("A"), _leaf("B"), angle_hint=10.0)
        config = MobileConfig(angle_strategy="blend", blend_ratio=0.7)
        expected = (1.0 - 0.7) * 10.0  # 3.0
        assert _compute_target_angle(branch, config) == pytest.approx(expected)

    def test_blend_zero_hint(self) -> None:
        branch = _branch(_leaf("A"), _leaf("B"), angle_hint=0.0)
        config = MobileConfig(angle_strategy="blend", blend_ratio=0.7)
        assert _compute_target_angle(branch, config) == 0.0


# ---------------------------------------------------------------------------
# _group_by_level
# ---------------------------------------------------------------------------


class TestGroupByLevel:
    def test_empty(self) -> None:
        assert _group_by_level({}) == []

    def test_single_level(self) -> None:
        assert _group_by_level({"0": 0}) == [["0"]]

    def test_three_levels(self) -> None:
        depth_map = {"0": 0, "L": 1, "R": 1, "LL": 2, "LR": 2}
        levels = _group_by_level(depth_map)
        assert len(levels) == 3
        # Bottom-up: deepest first
        assert set(levels[0]) == {"LL", "LR"}
        assert set(levels[1]) == {"L", "R"}
        assert levels[2] == ["0"]


# ---------------------------------------------------------------------------
# _patch_tree
# ---------------------------------------------------------------------------


class TestPatchTree:
    def test_patches_single_branch(self) -> None:
        tree = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        results = {"0": {"pivot_mm": 60.0, "angle": 2.5}}
        patched = _patch_tree(tree, "", results)

        assert isinstance(patched, ResolvedBranch)
        assert patched.pivot_mm == 60.0
        assert patched.pivot == pytest.approx(0.6)
        assert patched.angle_eq == 2.5
        assert patched.angle == 2.5

    def test_preserves_leaves(self) -> None:
        tree = _branch(_leaf("A", weight=3.0), _leaf("B", weight=5.0))
        results = {"0": {"pivot_mm": 40.0, "angle": -1.0}}
        patched = _patch_tree(tree, "", results)

        assert isinstance(patched, ResolvedBranch)
        assert isinstance(patched.left, ResolvedLeaf)
        assert patched.left.weight == 3.0
        assert patched.left.label == "A"

    def test_patches_nested(self) -> None:
        left = _branch(_leaf("A"), _leaf("B"), arc_w=50.0)
        tree = _branch(left, _leaf("C"), arc_w=100.0)
        results = {
            "0": {"pivot_mm": 70.0, "angle": 1.0},
            "L": {"pivot_mm": 20.0, "angle": -0.5},
        }
        patched = _patch_tree(tree, "", results)

        assert isinstance(patched, ResolvedBranch)
        assert patched.pivot_mm == 70.0
        assert isinstance(patched.left, ResolvedBranch)
        assert patched.left.pivot_mm == 20.0
        assert patched.left.pivot == pytest.approx(0.4)

    def test_no_result_preserves_original(self) -> None:
        tree = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        patched = _patch_tree(tree, "", {})

        assert isinstance(patched, ResolvedBranch)
        assert patched.pivot_mm == 50.0  # original midpoint


# ---------------------------------------------------------------------------
# _solve_pivot — unit tests with synthetic STL
# ---------------------------------------------------------------------------


class TestSolvePivot:
    def test_symmetric_box_target_zero(self, tmp_path: Path) -> None:
        """A box centered at origin with target 0° should pivot near midpoint."""
        # Box from (-50, -1, -1) to (50, 1, 1): centered at origin
        stl = tmp_path / "arc-0.stl"
        _write_binary_stl(stl, _box_triangles(-50, -1, -1, 50, 1, 1))

        branch = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        config = MobileConfig()
        result = _solve_pivot(branch, stl, 0.0, config)

        assert result["converged"]
        # Symmetric box: pivot should be near midpoint (50mm)
        assert result["pivot_mm"] == pytest.approx(50.0, abs=1.0)

    def test_asymmetric_box_shifts_pivot(self, tmp_path: Path) -> None:
        """A box with more mass on the right should shift pivot right."""
        # Box from (-20, -1, -1) to (80, 1, 1): COM is at x=30 (rightward from midpoint 0)
        stl = tmp_path / "arc-0.stl"
        _write_binary_stl(stl, _box_triangles(-20, -1, -1, 80, 1, 1))

        # arc_w=100, midpoint=50, so STL origin is at midpoint
        # But the box extends [-20, 80] so COM_x = (-20+80)/2 = 30
        branch = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        config = MobileConfig()
        result = _solve_pivot(branch, stl, 0.0, config)

        assert result["converged"]
        # COM is right of midpoint → pivot should shift right to balance
        assert result["pivot_mm"] > 50.0

    def test_zero_mass_returns_midpoint(self, tmp_path: Path) -> None:
        """Zero-volume STL should return midpoint."""
        # Degenerate STL: single flat triangle (zero volume)
        stl = tmp_path / "arc-0.stl"
        tris = [((0, 0, 0), (1, 0, 0), (0, 1, 0))]
        _write_binary_stl(stl, tris)

        branch = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        config = MobileConfig()
        result = _solve_pivot(branch, stl, 0.0, config)

        assert result["converged"]
        assert result["pivot_mm"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# simulate_mobile — integration and error path tests
# ---------------------------------------------------------------------------


class TestSimulateMobileErrors:
    def test_leaf_passthrough(self) -> None:
        """A single leaf needs no simulation."""
        leaf = _leaf("X")
        config = MobileConfig()
        result = simulate_mobile(leaf, config, Path("/nonexistent"))
        assert result is leaf

    def test_missing_stl_file(self) -> None:
        tree = _branch(_leaf("A"), _leaf("B"))
        config = MobileConfig()
        with pytest.raises(MobileSimulationError, match="STL file not found"):
            simulate_mobile(tree, config, Path("/tmp/nonexistent_dir_xyz"))

    def test_successful_symmetric(self, tmp_path: Path) -> None:
        """Verify tree is patched correctly for a symmetric box."""
        # Symmetric box: COM at origin → pivot near midpoint
        stl = tmp_path / "arc-0.stl"
        _write_binary_stl(stl, _box_triangles(-50, -1, -1, 50, 1, 1))

        tree = _branch(_leaf("A"), _leaf("B"), arc_w=100.0)
        config = MobileConfig()
        patched = simulate_mobile(tree, config, tmp_path)

        assert isinstance(patched, ResolvedBranch)
        assert patched.pivot_mm == pytest.approx(50.0, abs=1.0)
        assert patched.angle == pytest.approx(0.0, abs=0.5)
