"""mobile.resolve — Level-to-tree resolution and bottom-up physics computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import Face, import_svg, Compound, FontStyle, TextAlign

from mobile.dsl import Arc, Leaf, Svg, Txt
from mobile.arc_math import equilibrium_angle_deg, solve_pivot_mm_for_angle
from mobile.errors import MobilePivotError, MobileWeightError

if TYPE_CHECKING:
    from mobile.config import MobileConfig
    from mobile.dsl import Mobile


# ---------------------------------------------------------------------------
# Resolved tree types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResolvedLeaf:
    label: str
    space: object  # dsl.Space
    area: float  # net area (positive - negative), mm²
    volume: float  # net area × thickness, mm³
    weight: float  # volume × density × cumulative_scale, grams
    scale: float  # cumulative scale factor
    rotation: float  # cumulative rotation, degrees


@dataclass(frozen=True)
class ResolvedBranch:
    left: ResolvedLeaf | ResolvedBranch
    right: ResolvedLeaf | ResolvedBranch
    arc: Arc
    weight: float  # total subtree weight
    pivot: float  # 0..1 position on arc
    pivot_mm: float  # pivot offset from left endpoint, mm
    angle_eq: float  # equilibrium tilt angle, degrees
    angle_hint: float  # user-specified rotation hint, degrees
    angle: float  # final angle (blend of eq + hint), degrees


ResolvedTree = ResolvedLeaf | ResolvedBranch


# ---------------------------------------------------------------------------
# Intermediate mutable node for tree linking
# ---------------------------------------------------------------------------

@dataclass
class _IntermediateNode:
    """Mutable node used during top-down structural linking."""
    left_child: _IntermediateNode | Leaf | None  # None = unlinked hole
    right_child: _IntermediateNode | Leaf | None
    arc: Arc
    rotation: float  # effective rotation (node + level)
    scale: float  # level scale


# ---------------------------------------------------------------------------
# Phase 1: Structural linking (top-down)
# ---------------------------------------------------------------------------

def _link_levels(mobile: Mobile) -> _IntermediateNode:
    """Convert level-based representation to a single rooted binary tree."""
    # Build all intermediate nodes for all levels
    all_level_nodes: list[list[_IntermediateNode]] = []

    for level in mobile.levels:
        level_nodes = []
        for node in level.nodes:
            arc = node.arc if node.arc is not None else level.arc
            effective_rotation = node.rotation + level.rotation
            inode = _IntermediateNode(
                left_child=node.left,
                right_child=node.right,
                arc=arc,
                rotation=effective_rotation,
                scale=level.scale,
            )
            level_nodes.append(inode)
        all_level_nodes.append(level_nodes)

    # Link holes in level N to nodes in level N+1, left-to-right
    for i in range(len(all_level_nodes) - 1):
        hole_queue = iter(all_level_nodes[i + 1])
        for inode in all_level_nodes[i]:
            if inode.left_child is None:
                inode.left_child = next(hole_queue)
            if inode.right_child is None:
                inode.right_child = next(hole_queue)

    # Root is the single node in level 0
    return all_level_nodes[0][0]


# ---------------------------------------------------------------------------
# Phase 2: Weight computation (bottom-up)
# ---------------------------------------------------------------------------

def _compute_leaf_area(leaf: Leaf, config: MobileConfig) -> float:
    """Compute net area of a leaf by loading its SVG/text shapes."""
    positive_area = 0.0
    negative_area = 0.0

    for atom in leaf.space.layers:
        if isinstance(atom, Svg):
            shapes = import_svg(atom.path)
            faces = [s for s in shapes if isinstance(s, Face)]
            atom_area = sum(f.area for f in faces)
            if atom.neg:
                negative_area += atom_area
            else:
                positive_area += atom_area
        elif isinstance(atom, Txt):
            text_compound = Compound.make_text(
                txt=atom.text,
                font_size=config.font_size,
                font=config.font,
                font_path=config.font_path,
                font_style=FontStyle.REGULAR,
                text_align=(TextAlign.CENTER, TextAlign.CENTER),
            )
            atom_area = sum(f.area for f in text_compound.faces())
            if atom.neg:
                negative_area += atom_area
            else:
                positive_area += atom_area

    return positive_area - negative_area


def _extract_label(leaf: Leaf) -> str:
    """Extract a display label from the leaf's layers."""
    for atom in leaf.space.layers:
        if isinstance(atom, Txt):
            return atom.text
    # Fall back to SVG filename
    for atom in leaf.space.layers:
        if isinstance(atom, Svg):
            return atom.path
    return "?"


def _resolve_node(
    node: _IntermediateNode | Leaf,
    config: MobileConfig,
    cumulative_scale: float,
) -> ResolvedTree:
    """Recursively resolve a node into a ResolvedTree."""
    if isinstance(node, Leaf):
        net_area = _compute_leaf_area(node, config)
        volume = net_area * config.leaf_thickness
        scale = node.scale * cumulative_scale
        weight = volume * config.density * scale

        if weight < 0:
            raise MobileWeightError(
                f"Leaf '{_extract_label(node)}' has negative weight "
                f"({weight:.3f}g) — too many cutouts"
            )

        return ResolvedLeaf(
            label=_extract_label(node),
            space=node.space,
            area=net_area,
            volume=volume,
            weight=weight,
            scale=scale,
            rotation=node.rotation,
        )

    # It's an _IntermediateNode (branch)
    assert isinstance(node, _IntermediateNode)

    child_scale = cumulative_scale * node.scale

    left_resolved = _resolve_node(node.left_child, config, child_scale)
    right_resolved = _resolve_node(node.right_child, config, child_scale)

    total_weight = left_resolved.weight + right_resolved.weight
    angle_hint = node.rotation

    # Interpret the hint as the *desired* equilibrium rotation about the pivot.
    # We solve for pivot position that achieves the target angle.
    if config.angle_strategy == "equilibrium":
        target_angle = 0.0
    elif config.angle_strategy == "hint":
        target_angle = angle_hint
    else:  # "blend" (weight toward equilibrium == smaller angle magnitude)
        target_angle = (1.0 - config.blend_ratio) * angle_hint

    try:
        pivot_mm = solve_pivot_mm_for_angle(
            arc_w=node.arc.w,
            arc_h=node.arc.h,
            weight_left=left_resolved.weight,
            weight_right=right_resolved.weight,
            target_angle_deg=target_angle,
            min_tip_span_mm=config.hole_tip_inset,
        )
    except ValueError as e:
        raise MobilePivotError(str(e)) from e

    pivot = pivot_mm / node.arc.w

    angle_eq = equilibrium_angle_deg(
        node.arc.w,
        node.arc.h,
        pivot_mm,
        left_resolved.weight,
        right_resolved.weight,
    )
    angle = angle_eq

    return ResolvedBranch(
        left=left_resolved,
        right=right_resolved,
        arc=node.arc,
        weight=total_weight,
        pivot=pivot,
        pivot_mm=pivot_mm,
        angle_eq=angle_eq,
        angle_hint=angle_hint,
        angle=angle,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve(mobile: Mobile) -> ResolvedTree:
    """Resolve a Mobile into a fully computed ResolvedTree."""
    root = _link_levels(mobile)
    return _resolve_node(root, mobile.config, cumulative_scale=1.0)
