"""mbl.generate — build123d geometry generation and STL export.

Each ResolvedBranch produces one fused STL containing the arc bar plus
any direct leaf children.  Sub-arc children get radial endpoint holes.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from build123d import (
    Box,
    Compound,
    Cylinder,
    Face,
    Part,
    Pos,
    Rectangle,
    Rot,
    SagittaArc,
    ShapeList,
    FontStyle,
    TextAlign,
    import_svg,
    export_stl,
    extrude,
    sweep,
)

from mbl.resolve import ResolvedBranch, ResolvedLeaf, ResolvedTree
from mbl.dsl import Svg, Txt
from mbl.arc_math import arc_y_at_x

if TYPE_CHECKING:
    from mbl.config import MobileConfig


# ---------------------------------------------------------------------------
# Helpers for boolean ops that may return ShapeList
# ---------------------------------------------------------------------------

def _fuse(a, b):
    """Boolean union that always returns a single exportable shape."""
    result = a + b
    if isinstance(result, ShapeList):
        return Compound(list(result))
    return result


def _cut(a, b):
    """Boolean subtraction that always returns a single exportable shape."""
    result = a - b
    if isinstance(result, ShapeList):
        return Compound(list(result))
    return result


# ---------------------------------------------------------------------------
# Arc bar creation
# ---------------------------------------------------------------------------

def _make_arc_bar(arc_w: float, arc_h: float, pivot_mm: float, config: MobileConfig) -> Part:
    """Create an arc bar via sweep of rectangular cross-section along SagittaArc."""
    left = (-pivot_mm, 0, 0)
    right = (arc_w - pivot_mm, 0, 0)

    # Create the arc path edge
    arc_edge = SagittaArc(left, right, arc_h)

    # Position cross-section at start of path
    location = arc_edge ^ 0  # Location at parameter 0
    cross_section = location * Rectangle(config.arc_bar_width, config.arc_bar_height)

    # Sweep cross-section along arc
    bar = sweep(cross_section, path=arc_edge)
    return bar


# ---------------------------------------------------------------------------
# Leaf part creation (positive body + negative cutters, separated)
# ---------------------------------------------------------------------------

def _make_leaf_parts(
    leaf: ResolvedLeaf, config: MobileConfig
) -> tuple[Part | None, list[Part]]:
    """Build a leaf's positive solid body and list of negative cutters.

    Both the positive body and cutters are centered at the origin:
      - XY center of the positive body's bounding box → (0, 0)
      - Z midplane → 0  (so Z range is [-thickness/2, +thickness/2])

    This means the caller can position the leaf at an arc endpoint with
    just ``Pos(ep_x, ep_y, 0) * body`` and it will be coplanar with
    the arc bar (whose midplane is also Z=0).

    Returns (positive_body, negative_cutters).
    positive_body may be None if the leaf has no positive atoms.
    """
    thickness = config.leaf_thickness
    xy_scale = leaf.scale
    pos_body: Part | None = None
    neg_cutters: list[Part] = []
    neg_cutter_is_text: list[bool] = []  # track origin for centering fix

    for atom in leaf.space.layers:
        if isinstance(atom, Svg):
            shapes = import_svg(atom.path)
            faces = [s for s in shapes if isinstance(s, Face)]
            for face in faces:
                face_scaled = face.scale(xy_scale) if xy_scale != 1.0 else face
                if atom.neg:
                    cutter = extrude(face_scaled, amount=thickness * 1.5)
                    neg_cutters.append(cutter)
                    neg_cutter_is_text.append(False)
                else:
                    solid = extrude(face_scaled, amount=thickness)
                    if pos_body is None:
                        pos_body = solid
                    else:
                        pos_body = _fuse(pos_body, solid)

        elif isinstance(atom, Txt):
            text_compound = Compound.make_text(
                txt=atom.text,
                font_size=config.font_size,
                font=config.font,
                font_path=config.font_path,
                font_style=FontStyle.REGULAR,
                text_align=(TextAlign.CENTER, TextAlign.CENTER),
            )
            # TextAlign.CENTER centres on typographic metrics (ascender/
            # descender), not on the visual bounding box of the glyphs.
            # Compute the visual BB centre and pre-shift each cutter so
            # it is truly at (0, 0) before the later SVG-centre step.
            tbb = text_compound.bounding_box()
            txt_cx = (tbb.min.X + tbb.max.X) / 2.0 * xy_scale
            txt_cy = (tbb.min.Y + tbb.max.Y) / 2.0 * xy_scale
            for face in text_compound.faces():
                face_scaled = face.scale(xy_scale) if xy_scale != 1.0 else face
                cutter = extrude(face_scaled, amount=thickness * 1.5)
                cutter = Pos(-txt_cx, -txt_cy, 0) * cutter
                neg_cutters.append(cutter)
                neg_cutter_is_text.append(True)

    if pos_body is None:
        return None, neg_cutters

    # --- Centre everything so the positive body is at the origin ----------
    #
    # The positive body (from SVG) may not be at the origin — e.g. a circle
    # SVG with viewBox "0 0 30 30" places the shape at (15, 15).
    # Text cutters, on the other hand, are created around (0, 0).
    #
    # Strategy: find the XY centre of the positive body's bounding box,
    # move SVG-sourced cutters by the same offset, but move text cutters
    # to the positive body's centre first so that after centering they
    # end up overlapping the leaf body at the origin.

    bb = pos_body.bounding_box()
    cx = (bb.min.X + bb.max.X) / 2.0
    cy = (bb.min.Y + bb.max.Y) / 2.0
    cz = (bb.min.Z + bb.max.Z) / 2.0   # extrude starts at Z=0, so cz ≈ thickness/2

    # Move text cutters so they sit at the positive body's centre
    # before the global centering pass shifts everything to the origin.
    repositioned = []
    for c, is_text in zip(neg_cutters, neg_cutter_is_text):
        if is_text:
            c = Pos(cx, cy, 0) * c
        repositioned.append(c)
    neg_cutters = repositioned

    centering = Pos(-cx, -cy, -cz)
    pos_body = centering * pos_body
    neg_cutters = [centering * c for c in neg_cutters]

    # --- Apply leaf-level rotation (around the now-centred origin).
    #
    # Leaf scaling is intentionally applied in 2D before extrusion so
    # thickness remains constant and leaf/arc intersections stay flush.

    if leaf.rotation != 0.0:
        r = Rot(0, 0, leaf.rotation)
        pos_body = r * pos_body
        neg_cutters = [r * c for c in neg_cutters]

    return pos_body, neg_cutters


# ---------------------------------------------------------------------------
# Hole geometry
# ---------------------------------------------------------------------------


def _cut_pivot_hole(piece: Part, branch: ResolvedBranch, config: MobileConfig) -> Part:
    """Cut a vertical hole at the pivot point (for parent string attachment)."""
    arc_y = arc_y_at_x(branch.arc.w, branch.arc.h, branch.pivot_mm, 0.0)
    hole_r = config.hole_diameter / 2.0
    bar_size = max(config.arc_bar_width, config.arc_bar_height)

    # Vertical cylinder at pivot, aligned with Y axis (gravity direction)
    hole = Pos(0, arc_y, 0) * Cylinder(
        radius=hole_r,
        height=bar_size * 3,
        rotation=(90, 0, 0),  # rotate to align with Y axis
    )
    return _cut(piece, hole)


def _cut_endpoint_hole(
    piece: Part, branch: ResolvedBranch, side: str, config: MobileConfig
) -> Part:
    """Cut a radial hole near an arc endpoint (for child string attachment).

    The hole points toward the centre of curvature of the arc and is
    inset from the tip by ``config.hole_tip_inset`` mm.
    """
    tip_x = -branch.pivot_mm if side == "left" else branch.arc.w - branch.pivot_mm

    # Inset toward the arc centre so the hole sits in solid bar material
    inset = config.hole_tip_inset
    if side == "left":
        hole_x = tip_x + inset
    else:
        hole_x = tip_x - inset

    arc_y = arc_y_at_x(branch.arc.w, branch.arc.h, branch.pivot_mm, hole_x)

    # Centre of curvature of the circular arc
    left_x = -branch.pivot_mm
    right_x = branch.arc.w - branch.pivot_mm
    mid_x = (left_x + right_x) / 2.0
    chord = right_x - left_x
    R = (chord ** 2) / (8 * branch.arc.h) + branch.arc.h / 2.0
    center_y = branch.arc.h - R

    # Direction from hole position toward centre of curvature
    dx = mid_x - hole_x
    dy = center_y - arc_y
    angle_from_y = math.degrees(math.atan2(dx, dy))

    hole_r = config.hole_diameter / 2.0
    bar_size = max(config.arc_bar_width, config.arc_bar_height)

    # Radial cylinder: start with Y-axis, rotate in XY plane toward centre
    hole = Pos(hole_x, arc_y, 0) * Rot(0, 0, -angle_from_y) * Cylinder(
        radius=hole_r,
        height=bar_size * 3,
        rotation=(90, 0, 0),
    )
    return _cut(piece, hole)


def _make_endpoint_hook(config: MobileConfig) -> Part:
    """Create a simple printable C-hook solid centered at origin."""
    outer_r = max(config.hook_outer_radius, 1.0)
    wall = max(min(config.hook_thickness, outer_r * 0.8), 0.4)
    depth = max(config.arc_bar_height, config.arc_bar_width, 1.0)
    gap = max(config.hook_gap, wall * 1.2)

    outer = Cylinder(radius=outer_r, height=depth)
    inner = Cylinder(radius=max(outer_r - wall, 0.2), height=depth * 1.2)
    hook = _cut(outer, inner)

    # Open the ring into a C profile.
    gap_box = Pos(outer_r - gap / 2.0, 0, 0) * Box(gap, outer_r * 2.4, depth * 2.0)
    hook = _cut(hook, gap_box)
    return hook


# ---------------------------------------------------------------------------
# Branch generation (recursive)
# ---------------------------------------------------------------------------

def _generate_branch(
    branch: ResolvedBranch,
    config: MobileConfig,
    output_dir: Path,
    path_prefix: str,
    depth: int,
    *,
    skip_holes: bool = False,
    stl_tolerance_override: float | None = None,
    stl_angular_tolerance_override: float | None = None,
) -> None:
    """Generate a single fused STL for this branch (arc + direct leaf children)."""

    # 1. Create the arc bar
    piece = _make_arc_bar(branch.arc.w, branch.arc.h, branch.pivot_mm, config)

    # 2. Endpoints in local coordinates (origin = pivot)
    left_x = -branch.pivot_mm
    right_x = branch.arc.w - branch.pivot_mm
    left_y = arc_y_at_x(branch.arc.w, branch.arc.h, branch.pivot_mm, left_x)
    right_y = arc_y_at_x(branch.arc.w, branch.arc.h, branch.pivot_mm, right_x)

    cutters: list[tuple[float, float, Part]] = []  # (ep_x, ep_y, cutter)

    # Counter-rotate leaves so they appear upright when the arc tilts.
    # branch.angle uses CW-positive convention; build123d Rot Z uses
    # CCW-positive (standard math).  The physical tilt is Rot(0,0,-angle),
    # so we pre-apply the inverse: Rot(0,0,+angle).
    counter_rot = Rot(0, 0, branch.angle)

    # 3. Fuse positive leaf bodies at endpoints
    #    _make_leaf_parts returns bodies centred at origin (XY and Z),
    #    so Pos(ep_x, ep_y, 0) places the leaf centre right at the
    #    arc tip, coplanar with the bar (both have midplane at Z=0).
    if isinstance(branch.left, ResolvedLeaf):
        pos_solid, neg_list = _make_leaf_parts(branch.left, config)
        if pos_solid is not None:
            piece = _fuse(piece, Pos(left_x, left_y, 0) * counter_rot * pos_solid)
        for c in neg_list:
            cutters.append((left_x, left_y, counter_rot * c))

    if isinstance(branch.right, ResolvedLeaf):
        pos_solid, neg_list = _make_leaf_parts(branch.right, config)
        if pos_solid is not None:
            piece = _fuse(piece, Pos(right_x, right_y, 0) * counter_rot * pos_solid)
        for c in neg_list:
            cutters.append((right_x, right_y, counter_rot * c))

    # 4. Apply ALL negative cutouts to the whole fused piece
    #    Cutters are already counter-rotated, so just translate to endpoint.
    for ep_x, ep_y, cutter in cutters:
        piece = _cut(piece, Pos(ep_x, ep_y, 0) * cutter)

    if not skip_holes:
        # 5. Cut pivot hole (always, vertical)
        piece = _cut_pivot_hole(piece, branch, config)

        # 6. Continuation attachment style at arc endpoints.
        if config.hook_style == "hook":
            hook = _make_endpoint_hook(config)
            if isinstance(branch.left, ResolvedBranch):
                piece = _fuse(
                    piece,
                    Pos(left_x, left_y + config.hook_offset_y, 0) * Rot(0, 0, 180) * hook,
                )
            if isinstance(branch.right, ResolvedBranch):
                piece = _fuse(
                    piece,
                    Pos(right_x, right_y + config.hook_offset_y, 0) * hook,
                )
        else:
            if isinstance(branch.left, ResolvedBranch):
                piece = _cut_endpoint_hole(piece, branch, "left", config)
            if isinstance(branch.right, ResolvedBranch):
                piece = _cut_endpoint_hole(piece, branch, "right", config)

    # 7. Export
    if not path_prefix:
        part_id = f"arc-{depth}"
    else:
        part_id = f"arc-{path_prefix}"

    tol = stl_tolerance_override if stl_tolerance_override is not None else config.stl_tolerance
    ang_tol = stl_angular_tolerance_override if stl_angular_tolerance_override is not None else config.stl_angular_tolerance

    export_stl(
        piece,
        str(output_dir / f"{part_id}.stl"),
        tolerance=tol,
        angular_tolerance=ang_tol,
    )

    # 8. Recurse into sub-arc children
    if isinstance(branch.left, ResolvedBranch):
        _generate_branch(
            branch.left, config, output_dir, path_prefix + "L", depth + 1,
            skip_holes=skip_holes,
            stl_tolerance_override=stl_tolerance_override,
            stl_angular_tolerance_override=stl_angular_tolerance_override,
        )
    if isinstance(branch.right, ResolvedBranch):
        _generate_branch(
            branch.right, config, output_dir, path_prefix + "R", depth + 1,
            skip_holes=skip_holes,
            stl_tolerance_override=stl_tolerance_override,
            stl_angular_tolerance_override=stl_angular_tolerance_override,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(
    tree: ResolvedTree,
    config: MobileConfig,
    output_dir: Path,
    *,
    skip_holes: bool = False,
    stl_tolerance_override: float | None = None,
    stl_angular_tolerance_override: float | None = None,
) -> None:
    """Generate STL files from a resolved tree."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(tree, ResolvedBranch):
        _generate_branch(
            tree, config, output_dir, "", 0,
            skip_holes=skip_holes,
            stl_tolerance_override=stl_tolerance_override,
            stl_angular_tolerance_override=stl_angular_tolerance_override,
        )
    else:
        # Single leaf — shouldn't normally happen but handle gracefully
        raise ValueError("Cannot generate STL from a single leaf — need at least one arc")
