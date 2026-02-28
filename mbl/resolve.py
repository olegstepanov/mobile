"""mbl.resolve — Grid-to-tree resolution and bottom-up physics computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import Face, import_svg, Compound, FontStyle, TextAlign

from mbl.dsl import Arc, Leaf, Svg, Txt
from mbl.errors import MobileWeightError

if TYPE_CHECKING:
    from mbl.config import MobileConfig
    from mbl.dsl import Mobile


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


# ---------------------------------------------------------------------------
# Phase 1: Structural linking (top-down)
# ---------------------------------------------------------------------------

def _link_levels(mobile: Mobile) -> _IntermediateNode:
    """Convert grid-row representation to a single rooted binary tree."""
    # Build all intermediate nodes for all levels
    all_level_nodes: list[list[_IntermediateNode]] = []

    for row in mobile.grid:
        level_nodes = []
        for cell in row:
            inode = _IntermediateNode(
                left_child=cell.left,
                right_child=cell.right,
                arc=cell.arc,
                rotation=cell.arc.rotation,
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
        # Leaf scale is XY-only (thickness is constant), so mass follows area.
        weight = volume * config.density * (scale ** 2)

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

    child_scale = cumulative_scale

    left_resolved = _resolve_node(node.left_child, config, child_scale)
    right_resolved = _resolve_node(node.right_child, config, child_scale)

    total_weight = left_resolved.weight + right_resolved.weight
    angle_hint = node.rotation

    # Midpoint pivot — COM solver will refine the real pivot later.
    pivot_mm = node.arc.w / 2.0
    pivot = 0.5
    angle_eq = 0.0
    angle = 0.0

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
