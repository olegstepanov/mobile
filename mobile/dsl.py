"""mobile.dsl — DSL types and operator overloading.

Implements the mobile DSL per SPEC.md: Svg, Txt, Space, Leaf, Node, Arc, Level, Mobile.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

from mobile.config import MobileConfig
from mobile.errors import MobileArcError, MobileEmptyError, MobileShapeError


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Svg:
    """An SVG image shape."""

    path: str
    neg: bool = False

    def __invert__(self) -> Svg:
        return Svg(self.path, not self.neg)

    def __and__(self, other: Atom) -> Space:
        return Space((self, other))

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation

    def __or__(self, _other: object) -> Leaf:
        return _to_leaf(self)


@dataclass(frozen=True)
class Txt:
    """A text glyph shape."""

    text: str
    neg: bool = False

    def __invert__(self) -> Txt:
        return Txt(self.text, not self.neg)

    def __and__(self, other: Atom) -> Space:
        return Space((self, other))

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation

    def __or__(self, _other: object) -> Leaf:
        return _to_leaf(self)


Atom = Svg | Txt


# ---------------------------------------------------------------------------
# Space
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Space:
    """Layered composition of atoms."""

    layers: tuple[Atom, ...]

    def __and__(self, other: Atom) -> Space:
        return Space(self.layers + (other,))

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation

    def __or__(self, _other: object) -> Leaf:
        return _to_leaf(self)


# ---------------------------------------------------------------------------
# Leaf
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Leaf:
    """A renderable weighted endpoint."""

    space: Space
    scale: float = 1.0
    rotation: float = 0.0

    def __mul__(self, scale: float) -> Leaf:
        return Leaf(self.space, self.scale * scale, self.rotation)

    def __mod__(self, rotation: float) -> Leaf:
        return Leaf(self.space, self.scale, self.rotation + rotation)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_leaf(obj: Atom | Space | Leaf | int) -> Leaf | None:
    """Convert an atom/space/leaf/0 to a Leaf or None (hole)."""
    if isinstance(obj, int) and obj == 0:
        return None
    if isinstance(obj, Leaf):
        return obj
    if isinstance(obj, (Svg, Txt)):
        return Leaf(Space((obj,)))
    if isinstance(obj, Space):
        return Leaf(obj)
    raise TypeError(f"Cannot convert {type(obj).__name__} to Leaf")


# Type for node children: Leaf, Atom, Space, or 0 (hole)
Child = Union[Leaf, Svg, Txt, Space, int]


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Node:
    """Binary node in the mobile tree."""

    left: Leaf | None  # None = hole
    right: Leaf | None  # None = hole
    arc: Arc | None = None
    rotation: float = 0.0

    def __matmul__(self, arc: Arc) -> Node:
        return Node(self.left, self.right, arc, self.rotation)

    def __mod__(self, rotation: float) -> Node:
        return Node(self.left, self.right, self.arc, self.rotation + rotation)


def _(left: Child, right: Child) -> Node:
    """Create a binary node. Use 0 for holes."""
    return Node(_to_leaf(left), _to_leaf(right))


# ---------------------------------------------------------------------------
# Arc
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Arc:
    """Pure geometry: the curved bar a node hangs from."""

    w: float  # width (span), mm
    h: float  # height (sag), mm

    def __rmatmul__(self, nodes: list) -> Level:
        """list @ Arc → Level.  Python tries list.__matmul__ first (undefined),
        then falls back to Arc.__rmatmul__."""
        return Level(tuple(nodes), self)


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Level:
    """A list of nodes bound to an arc."""

    nodes: tuple[Node, ...]
    arc: Arc | None = None
    rotation: float = 0.0
    scale: float = 1.0

    def __mod__(self, rotation: float) -> Level:
        return Level(self.nodes, self.arc, self.rotation + rotation, self.scale)

    def __mul__(self, scale: float) -> Level:
        return Level(self.nodes, self.arc, self.rotation, self.scale * scale)


# ---------------------------------------------------------------------------
# Mobile
# ---------------------------------------------------------------------------

class Mobile:
    """Top-level mobile container.  Validates topology on construction."""

    def __init__(
        self,
        levels: list[Level | list[Node]],
        config: MobileConfig | None = None,
    ):
        self.config = config or MobileConfig()
        self.levels: list[Level] = []

        for lvl in levels:
            if isinstance(lvl, Level):
                self.levels.append(lvl)
            elif isinstance(lvl, list):
                # Bare list of nodes (no level-default arc)
                self.levels.append(Level(tuple(lvl)))
            else:
                raise TypeError(f"Expected Level or list[Node], got {type(lvl).__name__}")

        self._validate()

    def _validate(self) -> None:
        if not self.levels:
            raise MobileEmptyError("Mobile has no levels")

        for i, level in enumerate(self.levels):
            # Every node must have an arc (individual or level default)
            for node in level.nodes:
                if node.arc is None and level.arc is None:
                    raise MobileArcError(
                        f"Level {i}: node has no arc and level has no default arc"
                    )

        # Check hole/node count matching between adjacent levels
        for i in range(len(self.levels) - 1):
            holes = sum(
                (1 if n.left is None else 0) + (1 if n.right is None else 0)
                for n in self.levels[i].nodes
            )
            next_nodes = len(self.levels[i + 1].nodes)
            if holes != next_nodes:
                raise MobileShapeError(
                    f"Level {i} has {holes} hole(s) but level {i + 1} "
                    f"has {next_nodes} node(s)"
                )

        # Last level must have no holes
        last = self.levels[-1]
        last_holes = sum(
            (1 if n.left is None else 0) + (1 if n.right is None else 0)
            for n in last.nodes
        )
        if last_holes > 0:
            raise MobileShapeError(
                f"Last level has {last_holes} hole(s) — no next level to fill them"
            )

    def build(self, output_dir: str | Path) -> None:
        """Resolve physics and generate STL files.

        Three-pass pipeline:
        1. Resolve tree with midpoint pivots and weights from build123d.
        2. Generate low-res intermediate STLs (no holes) → COM solver finds pivots.
        3. Generate final hi-res STLs with correct holes at solved pivot positions.
        """
        import tempfile

        from mobile.generate import generate
        from mobile.resolve import resolve
        from mobile.simulate import simulate_mobile

        tree = resolve(self)

        # Pass 2: generate intermediate STLs for COM-based pivot solver
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generate(
                tree, self.config, tmp_path,
                skip_holes=True,
                stl_tolerance_override=self.config.sim_stl_tolerance,
                stl_angular_tolerance_override=self.config.sim_stl_angular_tolerance,
            )
            # Compute center of mass from STL meshes, find real pivot positions
            tree = simulate_mobile(tree, self.config, tmp_path)

        # Pass 3: generate final STLs with correct holes
        generate(tree, self.config, Path(output_dir))
