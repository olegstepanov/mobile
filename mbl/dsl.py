"""mbl.dsl — Grid-first DSL for parametric hanging mobiles.

Canonical structure: a row matrix.
- each row = one mobile level
- each cell = Arc @ (left, right)
- a missing slot (None) is a continuation hole for the next row
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Sequence, Union

from mbl.config import MobileConfig
from mbl.errors import MobileEmptyError, MobileShapeError
from mbl.stl import merge_stl_files
from mbl.three_mf import export_3mf_files


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Svg:
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


@dataclass(frozen=True)
class Txt:
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


Atom = Svg | Txt


@dataclass(frozen=True)
class Space:
    layers: tuple[Atom, ...]

    def __and__(self, other: Atom) -> Space:
        return Space(self.layers + (other,))

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation


@dataclass(frozen=True)
class Leaf:
    space: Space
    scale: float = 1.0
    rotation: float = 0.0

    def __mul__(self, scale: float) -> Leaf:
        return Leaf(self.space, self.scale * scale, self.rotation)

    def __mod__(self, rotation: float) -> Leaf:
        return Leaf(self.space, self.scale, self.rotation + rotation)

    @staticmethod
    def from_svg(path: str) -> Leaf:
        return Leaf(Space((Svg(path),)))

    @staticmethod
    def circle(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("circle.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def star(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("star.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def burst(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("burst.svg"))
        return Leaf.from_svg(p)


Child = Union[Leaf, Svg, Txt, Space, None]


# ---------------------------------------------------------------------------
# Grid cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Arc:
    w: float
    h: float
    rotation: float = 0.0

    def __mod__(self, degrees: float) -> Arc:
        return Arc(self.w, self.h, self.rotation + degrees)

    def __matmul__(self, hanging) -> Cell | list[Cell]:
        """Bind arc to one pair or map across a list of pairs.

        Supported:
        - Arc(...) @ (left, right) -> Cell
        - Arc(...) @ (left,)       -> Cell (right hole)
        - Arc(...) @ [(a, b), (c,)] -> list[Cell]
        """
        if isinstance(hanging, (tuple, list)) and hanging:
            if self._is_pair(hanging):
                return self._bind_pair(hanging)
            if all(self._is_pair(item) for item in hanging):
                return [self._bind_pair(item) for item in hanging]
        raise TypeError(
            "Arc bind expects (left[, right]) or a list of such tuples"
        )

    @staticmethod
    def _is_pair(value) -> bool:
        if not isinstance(value, (tuple, list)):
            return False
        if len(value) not in (1, 2):
            return False
        return not any(isinstance(v, (tuple, list)) for v in value)

    def _bind_pair(self, pair: Sequence[Child]) -> Cell:
        left = pair[0]
        right = pair[1] if len(pair) == 2 else None
        return Cell(self, _to_leaf(left), _to_leaf(right))


@dataclass(frozen=True)
class Cell:
    arc: Arc
    left: Leaf | None
    right: Leaf | None

    def __mod__(self, degrees: float) -> Cell:
        return Cell(self.arc % degrees, self.left, self.right)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_path(name: str) -> Path:
    return Path(__file__).parent / "assets" / name


def _to_leaf(obj: Atom | Space | Leaf | None) -> Leaf | None:
    if obj is None:
        return None
    if isinstance(obj, Leaf):
        return obj
    if isinstance(obj, (Svg, Txt)):
        return Leaf(Space((obj,)))
    if isinstance(obj, Space):
        return Leaf(obj)
    raise TypeError(f"Cannot convert {type(obj).__name__} to Leaf")


def stencil_cut(text: str, base: Leaf | Space | Svg | None = None) -> Leaf:
    base_shape = base if base is not None else Leaf.circle()
    base_leaf = _to_leaf(base_shape)
    assert base_leaf is not None
    return Leaf(base_leaf.space & ~Txt(text), base_leaf.scale, base_leaf.rotation)


def _leaf_from_shape(shape: str) -> Leaf:
    if shape == "circle":
        return Leaf.circle()
    if shape == "burst":
        return Leaf.burst()
    if shape == "star":
        return Leaf.star()
    raise ValueError(f"Unsupported leaf shape: {shape}")


RowLike = Cell | Sequence[Cell]


# ---------------------------------------------------------------------------
# Mobile
# ---------------------------------------------------------------------------


class Mobile:
    """Grid-first mobile model and build entrypoint."""

    def __init__(self, rows: Sequence[RowLike], config: MobileConfig | None = None):
        self.config = config or MobileConfig()
        self.grid: list[list[Cell]] = [self._coerce_row(row) for row in rows]
        self._validate()

    @classmethod
    def from_word(
        cls,
        word: str,
        *,
        width: float = 80.0,
        height: float = 12.0,
        leaf_shape: str = "circle",
        config: MobileConfig | None = None,
    ) -> Mobile:
        if not word:
            raise MobileEmptyError("word is empty")

        cfg = config or MobileConfig()
        if cfg.font_path is None:
            bundled_font = _asset_path("StardosStencil-Regular.ttf")
            if bundled_font.exists():
                cfg.font_path = str(bundled_font)
        count = len(word)
        rows: list[Cell] = []

        for idx, ch in enumerate(word):
            ratio = idx / max(1, count - 1)
            arc_w = max(28.0, width * (0.68 + (1.0 - ratio) * 0.32))
            arc_h = max(4.0, height * (0.6 + (1.0 - ratio) * 0.4))
            leaf_scale = max(0.62, 1.0 - 0.32 * ratio)
            base_leaf = _leaf_from_shape(leaf_shape)
            if ch.isspace():
                left_leaf = base_leaf * leaf_scale
            else:
                left_leaf = stencil_cut(ch, base=base_leaf) * leaf_scale
            right_leaf = (
                base_leaf * max(0.55, leaf_scale * 0.8)
                if idx == count - 1
                else None
            )
            rows.append(Arc(arc_w, arc_h) @ (left_leaf, right_leaf))

        return cls(rows, config=cfg)

    @property
    def rows(self) -> list[list[Cell]]:
        return self.grid

    def _coerce_row(self, row: RowLike) -> list[Cell]:
        if isinstance(row, Cell):
            return [row]
        if isinstance(row, Sequence):
            if not all(isinstance(c, Cell) for c in row):
                bad = [type(c).__name__ for c in row if not isinstance(c, Cell)][0]
                raise TypeError(f"Row must contain Cell items, got {bad}")
            return list(row)
        raise TypeError(f"Unsupported row type: {type(row).__name__}")

    def _validate(self) -> None:
        if not self.grid:
            raise MobileEmptyError("Mobile has no rows")
        if len(self.grid[0]) != 1:
            raise MobileShapeError("Top row must contain exactly one arc cell")

        for i, row in enumerate(self.grid):
            if not row:
                raise MobileShapeError(f"Row {i} is empty")
            for cell in row:
                if cell.arc.w <= 0:
                    raise MobileShapeError(f"Row {i}: arc width must be > 0")
                if cell.arc.h < 0:
                    raise MobileShapeError(f"Row {i}: arc height must be >= 0")

        for i in range(len(self.grid) - 1):
            holes = sum(
                (1 if c.left is None else 0) + (1 if c.right is None else 0)
                for c in self.grid[i]
            )
            next_cells = len(self.grid[i + 1])
            if holes != next_cells:
                raise MobileShapeError(
                    f"Row {i} has {holes} hole(s), row {i + 1} has {next_cells} cell(s)"
                )

        last_holes = sum(
            (1 if c.left is None else 0) + (1 if c.right is None else 0)
            for c in self.grid[-1]
        )
        if last_holes > 0:
            raise MobileShapeError(f"Last row has {last_holes} hole(s) with no continuation")

    def build(self, output_dir: str | Path) -> None:
        """Resolve pivots and export one STL per arc piece."""
        from mbl.generate import generate
        from mbl.resolve import resolve
        from mbl.simulate import simulate_mobile

        tree = resolve(self)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generate(
                tree,
                self.config,
                tmp_path,
                skip_holes=True,
                stl_tolerance_override=self.config.sim_stl_tolerance,
                stl_angular_tolerance_override=self.config.sim_stl_angular_tolerance,
            )
            tree = simulate_mobile(tree, self.config, tmp_path)

        generate(tree, self.config, Path(output_dir))

    def to_stl(self, output_path: str | Path) -> Path:
        """Export a packed single STL and sidecar part STLs."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.build(tmp_path)
            parts = sorted(tmp_path.glob("arc-*.stl"))
            if not parts:
                raise MobileEmptyError("No STL parts were generated")

            merge_stl_files(parts, out)

            stem = out.stem
            for stl in parts:
                sidecar = out.with_name(f"{stem}-{stl.stem}.stl")
                if sidecar != out:
                    shutil.copy2(stl, sidecar)

        return out

    def to_3mf(self, output_path: str | Path) -> Path:
        """Export a multi-object 3MF where each arc is an individual object."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self.build(tmp_path)
            parts = sorted(tmp_path.glob("arc-*.stl"))
            if not parts:
                raise MobileEmptyError("No STL parts were generated")
            export_3mf_files(parts, out)

        return out

    def to_file(self, output_path: str | Path) -> Path:
        """Export based on extension: .stl or .3mf."""
        out = Path(output_path)
        suffix = out.suffix.lower()
        if suffix == ".3mf":
            return self.to_3mf(out)
        if suffix == ".stl" or suffix == "":
            return self.to_stl(out)
        raise ValueError(f"Unsupported output format: {out.suffix}")
