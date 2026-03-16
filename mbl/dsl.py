"""mbl.dsl — Grid-first DSL for parametric hanging mobiles.

Canonical structure: a row matrix.
- each row = one mobile level
- each cell = Leaf @ Arc @ Leaf  (both leaves optional)
- a missing slot (None) is a continuation hole for the next row
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unicodedata
import warnings
from typing import Sequence, Union

from build123d import Compound, Face, FontStyle, TextAlign, import_svg

from mbl.config import MobileConfig
from mbl.errors import MobileEmptyError, MobileShapeError
from mbl.perf import count, span
from mbl.three_mf import export_3mf_files


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vector:
    path: str
    neg: bool = False

    def __invert__(self) -> Vector:
        return Vector(self.path, not self.neg)

    def __and__(self, other: Atom | Leaf) -> Space:
        if isinstance(other, Leaf):
            return Space((self,) + other.space.layers)
        return Space((self, other))

    def __matmul__(self, other):
        return _to_leaf(self).__matmul__(other)

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation


Svg = Vector


@dataclass(frozen=True)
class Text:
    text: str
    neg: bool = False
    scale: float = 1.0

    def __invert__(self) -> Text:
        return Text(self.text, not self.neg, self.scale)

    def __and__(self, other: Atom | Leaf) -> Space:
        if isinstance(other, Leaf):
            return Space((self,) + other.space.layers)
        return Space((self, other))

    def __matmul__(self, other):
        return _to_leaf(self).__matmul__(other)

    def __mul__(self, scale: float) -> Leaf:
        return _to_leaf(self) * scale

    def __mod__(self, rotation: float) -> Leaf:
        return _to_leaf(self) % rotation


Txt = Text

Atom = Vector | Text


@dataclass(frozen=True)
class Space:
    layers: tuple[Atom, ...]

    def __and__(self, other: Atom | Leaf) -> Space:
        if isinstance(other, Leaf):
            return Space(self.layers + other.space.layers)
        return Space(self.layers + (other,))

    def __matmul__(self, other):
        return _to_leaf(self).__matmul__(other)

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

    def __and__(self, other: Atom | Leaf | Space) -> Leaf:
        if isinstance(other, Leaf):
            combined = Space(self.space.layers + other.space.layers)
        elif isinstance(other, Space):
            combined = Space(self.space.layers + other.layers)
        else:  # Atom
            combined = Space(self.space.layers + (other,))
        return Leaf(combined, self.scale, self.rotation)

    def __matmul__(self, other: Arc) -> Cell:
        if not isinstance(other, Arc):
            return NotImplemented
        return Cell(other, self, None)

    @staticmethod
    def from_svg(path: str) -> Leaf:
        return Leaf(Space((Vector(path),)))

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

    @staticmethod
    def heart(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("heart.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def shopify(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("shopify.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def peace(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("peace.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def cup(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("cup.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def eclipse(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("eclipse.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def octopus(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("octopus.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def smile(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("smile.svg"))
        return Leaf.from_svg(p)

    @staticmethod
    def sun(path: str | None = None) -> Leaf:
        p = path or str(_asset_path("sun.svg"))
        return Leaf.from_svg(p)


# Top-level shape constructors
def Circle() -> Leaf:  return Leaf.from_svg(str(_asset_path("circle.svg")))
def Star() -> Leaf:    return Leaf.from_svg(str(_asset_path("star.svg")))
def Burst() -> Leaf:   return Leaf.from_svg(str(_asset_path("burst.svg")))
def Heart() -> Leaf:   return Leaf.from_svg(str(_asset_path("heart.svg")))
def Shopify() -> Leaf: return Leaf.from_svg(str(_asset_path("shopify.svg")))
def Peace() -> Leaf:   return Leaf.from_svg(str(_asset_path("peace.svg")))
def Cup() -> Leaf:     return Leaf.from_svg(str(_asset_path("cup.svg")))
def Eclipse() -> Leaf: return Leaf.from_svg(str(_asset_path("eclipse.svg")))
def Octopus() -> Leaf: return Leaf.from_svg(str(_asset_path("octopus.svg")))
def Smile() -> Leaf:   return Leaf.from_svg(str(_asset_path("smile.svg")))
def Sun() -> Leaf:     return Leaf.from_svg(str(_asset_path("sun.svg")))


Child = Union[Leaf, Vector, Text, Space, None]


# ---------------------------------------------------------------------------
# Grid cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Arc:
    w: float
    h: float
    rotation: float = 0.0
    offset: tuple[float, float] = (0.0, 0.0)

    def __add__(self, xy: tuple[float, float]) -> Arc:
        return Arc(self.w, self.h, self.rotation,
                   (self.offset[0] + xy[0], self.offset[1] + xy[1]))

    def __mod__(self, degrees: float) -> Arc:
        return Arc(self.w, self.h, self.rotation + degrees, self.offset)

    def __matmul__(self, other) -> Cell:
        """Arc @ Leaf → Cell(arc, left=None, right=Leaf)."""
        leaf = _to_leaf(other)
        if leaf is None:
            return NotImplemented
        return Cell(self, None, leaf)


@dataclass(frozen=True)
class Cell:
    arc: Arc
    left: Leaf | None
    right: Leaf | None

    def __matmul__(self, other) -> Cell:
        """Cell @ Leaf → fill the right slot."""
        leaf = _to_leaf(other)
        if leaf is None:
            return NotImplemented
        if self.right is not None:
            raise TypeError("Right leaf is already bound")
        return Cell(self.arc, self.left, leaf)

    def __mod__(self, degrees: float) -> Cell:
        return Cell(self.arc % degrees, self.left, self.right)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _asset_path(name: str) -> Path:
    return Path(__file__).parent / "assets" / name


DEFAULT_SHAPE_DIAMETER_MM = 25.0
BUILTIN_SHAPES = {
    "circle": "circle.svg",
    "burst": "burst.svg",
    "star": "star.svg",
    "heart": "heart.svg",
    "shopify": "shopify.svg",
    "peace": "peace.svg",
    "cup": "cup.svg",
    "eclipse": "eclipse.svg",
    "octopus": "octopus.svg",
    "smile": "smile.svg",
    "sun": "sun.svg",
}

# Emoji / special-character → built-in shape mapping.
# Keys are base codepoints (without U+FE0F variation selector).
EMOJI_SHAPE_MAP: dict[str, str] = {
    # Stars
    "\u2b50": "star",       # ⭐
    "\U0001f31f": "star",   # 🌟
    "\u2734": "star",       # ✴
    # Hearts
    "\u2764": "heart",      # ❤ (❤️)
    "\U0001f49c": "heart",  # 💜
    "\U0001f499": "heart",  # 💙
    "\U0001f49a": "heart",  # 💚
    "\U0001f9e1": "heart",  # 🧡
    "\U0001f5a4": "heart",  # 🖤
    "\U0001f90d": "heart",  # 🤍
    "\U0001f90e": "heart",  # 🤎
    "\U0001f498": "heart",  # 💘
    # Sun
    "\u2600": "sun",        # ☀ (☀️)
    "\U0001f31e": "sun",    # 🌞
    # Eclipse / moon
    "\U0001f319": "eclipse",  # 🌙
    "\U0001f311": "eclipse",  # 🌑
    "\U0001f312": "eclipse",  # 🌒
    "\U0001f318": "eclipse",  # 🌘
    # Smile
    "\U0001f60a": "smile",  # 😊
    "\U0001f642": "smile",  # 🙂
    "\U0001f600": "smile",  # 😀
    "\U0001f603": "smile",  # 😃
    "\U0001f604": "smile",  # 😄
    # Octopus
    "\U0001f419": "octopus",  # 🐙
    # Cup / coffee
    "\u2615": "cup",        # ☕
    "\U0001f375": "cup",    # 🍵
    # Burst / explosion
    "\U0001f4a5": "burst",  # 💥
    "\u2733": "burst",      # ✳ (✳️)
    # Circle
    "\u26aa": "circle",     # ⚪
    "\u2b24": "circle",     # ⬤
    "\u25cf": "circle",     # ●
    "\U0001f534": "circle", # 🔴
    "\U0001f535": "circle", # 🔵
    # Peace
    "\u262e": "peace",      # ☮ (☮️)
    # Shopify (shopping-related emoji)
    "\U0001f6cd": "shopify",  # 🛍 (🛍️)
    "\U0001f6d2": "shopify",  # 🛒
}


def _can_use_helvetica_neue_bold() -> bool:
    """Return True when text engine can render Helvetica Neue in bold style."""
    try:
        Compound.make_text(
            txt="A",
            font_size=8.0,
            font="Helvetica Neue",
            font_path=None,
            font_style=FontStyle.BOLD,
            text_align=(TextAlign.CENTER, TextAlign.CENTER),
        )
    except Exception:
        return False
    return True


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


def stencil_cut(
    text: str,
    base: Leaf | Space | Svg | None = None,
    *,
    text_scale: float = 1.0,
) -> Leaf:
    base_shape = base if base is not None else Leaf.circle()
    base_leaf = _to_leaf(base_shape)
    assert base_leaf is not None
    return Leaf(
        base_leaf.space & ~Txt(text, scale=text_scale),
        base_leaf.scale,
        base_leaf.rotation,
    )


def text_leaf(text: str, *, text_scale: float = 1.0) -> Leaf:
    return Leaf(Space((Txt(text, scale=text_scale),)))


def _is_rtl(text: str) -> bool:
    """Return True if the first strong directional character is right-to-left."""
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL", "AN"):
            return True
        if bidi == "L":
            return False
    return False


def _split_graphemes(text: str) -> list[str]:
    """Split a string into grapheme clusters (handles emoji with variation selectors)."""
    clusters: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        i += 1
        # Consume trailing variation selectors (U+FE0E, U+FE0F) and ZWJ sequences
        while i < len(text) and text[i] in ("\ufe0e", "\ufe0f"):
            ch += text[i]
            i += 1
        # Handle ZWJ sequences (e.g., family emoji)
        while i < len(text) and text[i] == "\u200d":
            ch += text[i]
            i += 1
            if i < len(text):
                ch += text[i]
                i += 1
                while i < len(text) and text[i] in ("\ufe0e", "\ufe0f"):
                    ch += text[i]
                    i += 1
        # Handle surrogate pairs — Python str already handles this, but
        # catch combining marks (skin tones, keycaps, etc.)
        while i < len(text) and (0x1F3FB <= ord(text[i]) <= 0x1F3FF  # skin tones
                                 or text[i] == "\u20e3"):             # keycap
            ch += text[i]
            i += 1
        clusters.append(ch)
    return clusters


def _emoji_leaf(
    grapheme: str,
    *,
    shape_scale: float,
    default_diameter_mm: float = DEFAULT_SHAPE_DIAMETER_MM,
) -> Leaf | None:
    """Return a shape Leaf if the grapheme maps to a built-in emoji shape, else None."""
    # Strip variation selectors to get the base codepoint(s)
    base = grapheme.replace("\ufe0e", "").replace("\ufe0f", "")
    if base not in EMOJI_SHAPE_MAP:
        return None
    shape_name = EMOJI_SHAPE_MAP[base]
    return _shape_leaf(shape_name, shape_scale=shape_scale,
                       default_diameter_mm=default_diameter_mm)


def _shape_path(shape: str) -> Path | None:
    normalized = shape.strip()
    if not normalized:
        raise ValueError("shape cannot be empty")

    key = normalized.lower()
    if key == "blank":
        return None

    if key in BUILTIN_SHAPES:
        return _asset_path(BUILTIN_SHAPES[key])

    path = Path(normalized).expanduser()
    if path.suffix.lower() != ".svg":
        raise ValueError(
            "shape must be a preset "
            "(circle|burst|star|heart|shopify|peace|blank) or an .svg path"
        )
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise ValueError(f"Custom shape file not found: {path}")
    return path


def _svg_diameter(path: Path) -> float:
    with span("shape.svg_diameter.import"):
        shapes = import_svg(str(path))
    faces = [s for s in shapes if isinstance(s, Face)]
    count("shape.svg_diameter.faces", len(faces))
    if not faces:
        raise ValueError(f"Shape '{path}' has no SVG faces")

    min_x = min(face.bounding_box().min.X for face in faces)
    max_x = max(face.bounding_box().max.X for face in faces)
    min_y = min(face.bounding_box().min.Y for face in faces)
    max_y = max(face.bounding_box().max.Y for face in faces)

    diameter = max(max_x - min_x, max_y - min_y)
    if diameter <= 0:
        raise ValueError(f"Shape '{path}' has invalid diameter ({diameter})")
    return diameter


def _shape_leaf(
    shape: str,
    *,
    shape_scale: float,
    default_diameter_mm: float = DEFAULT_SHAPE_DIAMETER_MM,
) -> Leaf | None:
    path = _shape_path(shape)
    if path is None:
        return None

    diameter = _svg_diameter(path)
    normalization = default_diameter_mm / diameter
    return Leaf.from_svg(str(path)) * (normalization * shape_scale)


RowLike = Cell | Arc | Sequence[Cell | Arc]


# ---------------------------------------------------------------------------
# Mobile
# ---------------------------------------------------------------------------


class Mobile:
    """Namespace for mobile generation utilities.

    All public methods are static — pass ``levels`` (a list of rows) and an
    optional ``config`` to any export helper.
    """

    def __init__(self, rows: Sequence[RowLike], config: MobileConfig | None = None):
        self.config = config or MobileConfig()
        self.grid: list[list[Cell]] = [self._coerce_row(row) for row in rows]
        self._validate()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def rows(self) -> list[list[Cell]]:
        return self.grid

    @staticmethod
    def _to_cell(item: Cell | Arc) -> Cell:
        if isinstance(item, Arc):
            return Cell(item, None, None)
        if isinstance(item, Cell):
            return item
        raise TypeError(f"Expected Cell or Arc, got {type(item).__name__}")

    def _coerce_row(self, row: RowLike) -> list[Cell]:
        if isinstance(row, (Cell, Arc)):
            return [self._to_cell(row)]
        if isinstance(row, Sequence):
            return [self._to_cell(c) for c in row]
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

    def _build(self, output_dir: str | Path) -> None:
        """Resolve pivots and export one STL per arc piece."""
        from mbl.generate import generate
        from mbl.resolve import resolve
        from mbl.simulate import simulate_mobile

        with span("build.resolve"):
            tree = resolve(self)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with span("build.generate.sim"):
                generate(
                    tree,
                    self.config,
                    tmp_path,
                    skip_holes=True,
                    stl_tolerance_override=self.config.sim_stl_tolerance,
                    stl_angular_tolerance_override=self.config.sim_stl_angular_tolerance,
                )
            with span("build.simulate"):
                tree = simulate_mobile(tree, self.config, tmp_path)

        with span("build.generate.final"):
            generate(tree, self.config, Path(output_dir))


# ---------------------------------------------------------------------------
# Module-level API
# ---------------------------------------------------------------------------


def from_word(
    word: str,
    *,
    width: float = 80.0,
    height: float = 12.0,
    shape: str = "circle",
    shape_scale: float = 1.0,
    text_scale: float = 0.8,
    config: MobileConfig | None = None,
) -> list[Cell]:
    """Generate levels for *word*. Mutates *config* in-place (font selection)."""
    if not word:
        raise MobileEmptyError("word is empty")
    if shape_scale <= 0:
        raise ValueError("shape_scale must be > 0")
    if text_scale <= 0:
        raise ValueError("text_scale must be > 0")

    cfg = config or MobileConfig()
    rtl = _is_rtl(word)
    chars = _split_graphemes(word)
    char_count = len(chars)
    level_count = max(1, char_count - 1)
    rows: list[Cell] = []
    base_leaf = _shape_leaf(shape, shape_scale=shape_scale)
    is_blank = base_leaf is None

    default_font_name = MobileConfig().font
    using_default_font = cfg.font_path is None and cfg.font == default_font_name
    if using_default_font:
        if is_blank:
            if _can_use_helvetica_neue_bold():
                cfg.font = "Helvetica Neue Bold"
                cfg.font_path = None
            else:
                warnings.warn(
                    "shape='blank' prefers 'Helvetica Neue Bold', but it is not "
                    "available on this system. Falling back to default font.",
                    stacklevel=2,
                )
        else:
            bundled_font = _asset_path("StardosStencil-Regular.ttf")
            if bundled_font.exists():
                cfg.font_path = str(bundled_font)

    def _make_char_leaf(
        ch: str, scale: float
    ) -> Leaf | None:
        """Build a leaf for a single grapheme cluster, checking emoji first."""
        if ch is None:
            return None
        emoji = _emoji_leaf(ch, shape_scale=shape_scale)
        if emoji is not None:
            return emoji * scale
        if is_blank:
            return text_leaf(ch, text_scale=text_scale) * scale
        assert base_leaf is not None
        if ch.isspace():
            return base_leaf * scale
        return stencil_cut(ch, base=base_leaf, text_scale=text_scale) * scale

    for idx in range(level_count):
        ratio = idx / max(1, level_count - 1)
        arc_w = max(28.0, width * (0.68 + (1.0 - ratio) * 0.32))
        arc_h = max(4.0, height * (0.6 + (1.0 - ratio) * 0.4))
        leaf_scale = max(0.62, 1.0 - 0.32 * ratio)
        right_scale = max(0.55, leaf_scale * 0.8)

        left_ch = chars[idx] if char_count > 1 else chars[0]
        right_ch = (
            chars[idx + 1]
            if char_count > 1 and idx == level_count - 1
            else (chars[0] if char_count == 1 else None)
        )

        left_leaf = _make_char_leaf(left_ch, leaf_scale)
        right_leaf = _make_char_leaf(right_ch, right_scale)

        if rtl:
            left_leaf, right_leaf = right_leaf, left_leaf

        arc = Arc(arc_w, arc_h)
        if left_leaf and right_leaf:
            rows.append(left_leaf @ arc @ right_leaf)
        elif left_leaf:
            rows.append(left_leaf @ arc)
        elif right_leaf:
            rows.append(arc @ right_leaf)
        else:
            rows.append(Cell(arc, None, None))

    return rows


def to_3mf(
    levels: Sequence[RowLike],
    output_path: str | Path,
    *,
    config: MobileConfig | None = None,
) -> Path:
    """Export a multi-object 3MF where each arc is an individual object."""
    mobile = Mobile(levels, config=config)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with span("export.to_3mf.build"):
            mobile._build(tmp_path)
        parts = sorted(tmp_path.glob("arc-*.stl"))
        if not parts:
            raise MobileEmptyError("No STL parts were generated")
        with span("export.to_3mf.pack"):
            export_3mf_files(parts, out)

    return out
