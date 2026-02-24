"""End-to-end tests: resolve → generate → COM solver → generate.

These tests require build123d to be installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mobile import Arc, Mobile, MobileConfig, Svg, Txt, _
from mobile.generate import generate
from mobile.resolve import ResolvedBranch, resolve
from mobile.simulate import simulate_mobile

# ---------------------------------------------------------------------------
# Paths to test assets
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
PROJECT = HERE.parent
CIRCLE_SVG = str(PROJECT / "designs" / "circle.svg")
FONT_PATH = str(PROJECT / "fonts" / "StardosStencil-Regular.ttf")


def _config(**overrides) -> MobileConfig:
    """Create a test config with reasonable solver settings."""
    defaults = dict(
        font_path=FONT_PATH,
        font_size=25.0,
        angle_strategy="equilibrium",
        sim_angle_tolerance_deg=0.5,  # relaxed for speed
        sim_max_bisect_iterations=30,
    )
    defaults.update(overrides)
    return MobileConfig(**defaults)


# ---------------------------------------------------------------------------
# Test: symmetric mobile → pivot near midpoint
# ---------------------------------------------------------------------------


def test_symmetric_mobile_pivot_near_midpoint(tmp_path: Path) -> None:
    """A symmetric mobile (equal leaves, target 0) should pivot near arc midpoint.

    When both sides weigh the same and the target angle is 0, the balance
    point should be very close to the geometric midpoint of the arc.
    """
    circle = Svg(CIRCLE_SVG)
    A = circle & ~Txt("A")
    B = circle & ~Txt("B")

    config = _config(angle_strategy="equilibrium")
    mobile = Mobile([
        [_(A, B)] @ Arc(80, 10),
    ], config=config)

    tree = resolve(mobile)
    assert isinstance(tree, ResolvedBranch)
    # Midpoint pivot from resolve
    assert tree.pivot_mm == pytest.approx(40.0)

    # Generate intermediate STLs (no holes, low-res)
    intermediate_dir = tmp_path / "intermediate"
    generate(
        tree, config, intermediate_dir,
        skip_holes=True,
        stl_tolerance_override=config.sim_stl_tolerance,
        stl_angular_tolerance_override=config.sim_stl_angular_tolerance,
    )
    assert (intermediate_dir / "arc-0.stl").exists()

    # Run COM-based pivot solver
    result = simulate_mobile(tree, config, intermediate_dir)
    assert isinstance(result, ResolvedBranch)

    # Symmetric mobile: pivot should be near midpoint (within a few mm)
    assert result.pivot_mm == pytest.approx(40.0, abs=5.0)
    # Angle should be near 0
    assert result.angle == pytest.approx(0.0, abs=1.0)

    # Generate final STLs
    output_dir = tmp_path / "output"
    generate(result, config, output_dir)
    assert (output_dir / "arc-0.stl").exists()
    # Final STL should be larger than intermediate (higher resolution)
    final_size = (output_dir / "arc-0.stl").stat().st_size
    intermediate_size = (intermediate_dir / "arc-0.stl").stat().st_size
    assert final_size > intermediate_size


# ---------------------------------------------------------------------------
# Test: full build pipeline (Mobile.build)
# ---------------------------------------------------------------------------


def test_full_build_pipeline(tmp_path: Path) -> None:
    """Run Mobile.build() end-to-end and verify output STLs exist."""
    circle = Svg(CIRCLE_SVG)
    A = circle & ~Txt("A")
    B = circle & ~Txt("B")
    C = circle & ~Txt("C")
    D = circle & ~Txt("D")

    config = _config(angle_strategy="equilibrium")
    mobile = Mobile([
        [_(0, 0)] @ Arc(120, 10),
        [_(A, B), _(C, D)] @ Arc(50, 8),
    ], config=config)

    output_dir = tmp_path / "output"
    mobile.build(output_dir)

    # Should produce 3 STL files: arc-0, arc-L, arc-R
    assert (output_dir / "arc-0.stl").exists()
    assert (output_dir / "arc-L.stl").exists()
    assert (output_dir / "arc-R.stl").exists()

    # All STL files should be non-trivial in size
    for stl in output_dir.glob("*.stl"):
        assert stl.stat().st_size > 100, f"{stl.name} is suspiciously small"


# ---------------------------------------------------------------------------
# Test: asymmetric mobile → pivot shifts toward heavier side
# ---------------------------------------------------------------------------


def test_asymmetric_pivot_shifts(tmp_path: Path) -> None:
    """When one side is heavier, the pivot should shift toward it."""
    circle = Svg(CIRCLE_SVG)
    # Left side: one leaf. Right side: one leaf scaled 2x (4x area -> 4x weight)
    light = circle & ~Txt("L")
    heavy = circle & ~Txt("H")

    config = _config(angle_strategy="equilibrium")
    mobile = Mobile([
        [_(light, heavy * 2.0)] @ Arc(80, 10),
    ], config=config)

    tree = resolve(mobile)
    assert isinstance(tree, ResolvedBranch)
    # Right child should be heavier
    assert tree.right.weight > tree.left.weight

    intermediate_dir = tmp_path / "intermediate"
    generate(
        tree, config, intermediate_dir,
        skip_holes=True,
        stl_tolerance_override=config.sim_stl_tolerance,
        stl_angular_tolerance_override=config.sim_stl_angular_tolerance,
    )

    result = simulate_mobile(tree, config, intermediate_dir)
    assert isinstance(result, ResolvedBranch)

    # Pivot should shift right of midpoint (toward heavier side)
    assert result.pivot_mm > 40.0 + 1.0  # at least 1mm right of center


# ---------------------------------------------------------------------------
# Test: generate skip_holes produces valid STL without holes
# ---------------------------------------------------------------------------


def test_generate_skip_holes(tmp_path: Path) -> None:
    """generate(skip_holes=True) should produce STLs without hole geometry.

    This test verifies generate accepts the flag.
    """
    circle = Svg(CIRCLE_SVG)
    A = circle & ~Txt("A")
    B = circle & ~Txt("B")

    config = MobileConfig(font_path=FONT_PATH, font_size=25.0)
    mobile = Mobile([
        [_(A, B)] @ Arc(60, 8),
    ], config=config)

    tree = resolve(mobile)

    # With holes
    with_holes_dir = tmp_path / "with_holes"
    generate(tree, config, with_holes_dir)

    # Without holes
    no_holes_dir = tmp_path / "no_holes"
    generate(tree, config, no_holes_dir, skip_holes=True)

    # Both should produce the file
    assert (with_holes_dir / "arc-0.stl").exists()
    assert (no_holes_dir / "arc-0.stl").exists()

    # The file without holes should be slightly smaller (fewer triangles)
    # but both should be non-trivial
    assert (with_holes_dir / "arc-0.stl").stat().st_size > 100
    assert (no_holes_dir / "arc-0.stl").stat().st_size > 100


# ---------------------------------------------------------------------------
# Test: tolerance overrides affect STL resolution
# ---------------------------------------------------------------------------


def test_tolerance_overrides(tmp_path: Path) -> None:
    """Low-res tolerance should produce smaller STL files than high-res."""
    circle = Svg(CIRCLE_SVG)
    A = circle & ~Txt("A")
    B = circle & ~Txt("B")

    config = MobileConfig(font_path=FONT_PATH, font_size=25.0)
    mobile = Mobile([
        [_(A, B)] @ Arc(60, 8),
    ], config=config)

    tree = resolve(mobile)

    hires_dir = tmp_path / "hires"
    generate(tree, config, hires_dir)

    lores_dir = tmp_path / "lores"
    generate(
        tree, config, lores_dir,
        stl_tolerance_override=0.05,
        stl_angular_tolerance_override=0.5,
    )

    hires_size = (hires_dir / "arc-0.stl").stat().st_size
    lores_size = (lores_dir / "arc-0.stl").stat().st_size

    # High-res should have more triangles -> larger file
    assert hires_size > lores_size
