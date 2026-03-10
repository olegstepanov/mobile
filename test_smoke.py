"""Smoke tests: CLI and SDK happy paths from the README."""

import subprocess
import sys
import tempfile
from pathlib import Path

from mbl import (
    Arc, Cell, Leaf, Mobile, Space,
    Vector, Text, Svg, Txt, stencil_cut,
    Circle, Star, Burst, Heart, Shopify,
    Cup, Eclipse, Octopus, Smile, Sun,
)


# ---------------------------------------------------------------------------
# DSL unit tests
# ---------------------------------------------------------------------------


def test_text_invert_and_circle():
    """~Text('H') & Circle() produces Space with 2 layers, first has neg=True."""
    result = ~Text("H") & Circle()
    assert isinstance(result, Space)
    assert len(result.layers) == 2
    assert isinstance(result.layers[0], Text)
    assert result.layers[0].neg is True
    assert isinstance(result.layers[1], Vector)


def test_circle_and_text():
    """Circle() & ~Text('H') produces Leaf (Leaf on left preserves type)."""
    result = Circle() & ~Text("H")
    assert isinstance(result, Leaf)
    assert len(result.space.layers) == 2
    assert isinstance(result.space.layers[1], Text)
    assert result.space.layers[1].neg is True


def test_arc_offset():
    """Arc(80, 12) + (5, 3) has offset (5, 3)."""
    a = Arc(80, 12) + (5, 3)
    assert a.offset == (5, 3)
    assert a.w == 80
    assert a.h == 12


def test_arc_offset_accumulates():
    """Arc offset accumulates with multiple additions."""
    a = Arc(80, 12) + (5, 3) + (1, 2)
    assert a.offset == (6, 5)


def test_new_syntax_builds_cell():
    """Arc(...) @ (~Text('S') & Circle(), ~Text('U') & Burst()) builds a Cell."""
    cell = Arc(88, 12) @ (~Text("S") & Circle(), ~Text("U") & Burst())
    assert isinstance(cell, Cell)
    assert cell.left is not None
    assert cell.right is not None
    assert len(cell.left.space.layers) == 2
    assert len(cell.right.space.layers) == 2


def test_backward_compat_aliases():
    """Svg, Txt, Leaf.circle() still work."""
    assert Svg is Vector
    assert Txt is Text
    leaf = Leaf.circle()
    assert isinstance(leaf, Leaf)
    assert isinstance(leaf.space.layers[0], Svg)


def test_arc_default_offset():
    """Arc without offset has (0.0, 0.0)."""
    a = Arc(80, 12)
    assert a.offset == (0.0, 0.0)


def test_top_level_constructors():
    """Top-level shape constructors return Leaf."""
    for ctor in [Circle, Star, Burst, Heart, Shopify, Cup, Eclipse, Octopus, Smile, Sun]:
        leaf = ctor()
        assert isinstance(leaf, Leaf)
        assert len(leaf.space.layers) == 1


# ---------------------------------------------------------------------------
# Emoji / special character mapping tests
# ---------------------------------------------------------------------------


def test_split_graphemes():
    """Grapheme splitter handles ASCII, emoji, and variation selectors."""
    from mbl.dsl import _split_graphemes

    assert _split_graphemes("HI") == ["H", "I"]
    assert _split_graphemes("⭐❤️") == ["⭐", "❤️"]
    assert _split_graphemes("H⭐I") == ["H", "⭐", "I"]
    # Variation selector stays attached
    assert _split_graphemes("☀️") == ["☀️"]
    assert len(_split_graphemes("☀️")) == 1


def test_emoji_leaf():
    """Emoji maps to correct built-in shape leaf."""
    from mbl.dsl import _emoji_leaf

    leaf = _emoji_leaf("⭐", shape_scale=1.0)
    assert leaf is not None
    assert isinstance(leaf, Leaf)
    # Star SVG path
    assert "star.svg" in leaf.space.layers[0].path

    leaf_heart = _emoji_leaf("❤️", shape_scale=1.0)
    assert leaf_heart is not None
    assert "heart.svg" in leaf_heart.space.layers[0].path

    # Non-emoji returns None
    assert _emoji_leaf("H", shape_scale=1.0) is None


def test_emoji_from_word():
    """from_word with emoji produces a mobile with shape leaves (no stencil text)."""
    mobile = Mobile.from_word("⭐❤️")
    # Should have 1 level (2 chars - 1)
    assert len(mobile.grid) == 1
    cell = mobile.grid[0][0]
    # Both leaves should have exactly 1 layer (just the shape, no text)
    assert cell.left is not None
    assert cell.right is not None
    assert len(cell.left.space.layers) == 1
    assert len(cell.right.space.layers) == 1


def test_mixed_emoji_and_letters():
    """Mix of emoji and letters: emoji get shape, letters get stencil."""
    mobile = Mobile.from_word("H⭐")
    cell = mobile.grid[0][0]
    # Left = "H" → stencil_cut (2 layers: shape + neg text)
    assert cell.left is not None
    assert len(cell.left.space.layers) == 2
    # Right = ⭐ → star shape (1 layer, just the SVG)
    assert cell.right is not None
    assert len(cell.right.space.layers) == 1
    assert "star.svg" in cell.right.space.layers[0].path


def test_emoji_cli():
    """CLI handles emoji input."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "stars.3mf"
        r = subprocess.run(
            [sys.executable, "-m", "mbl.cli", "⭐❤️", "--output", str(out)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# Original smoke tests
# ---------------------------------------------------------------------------


def test_cli_default():
    """CLI generates output with default shape."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "hello.3mf"
        r = subprocess.run(
            [sys.executable, "-m", "mbl.cli", "HI", "--output", str(out)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        assert out.exists() and out.stat().st_size > 0


def test_cli_shape():
    """CLI works with a non-default built-in shape."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "hi-heart.3mf"
        r = subprocess.run(
            [sys.executable, "-m", "mbl.cli", "HI", "--shape", "heart", "--output", str(out)],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        assert out.exists() and out.stat().st_size > 0


def test_sdk_from_word():
    """SDK Mobile.from_word() produces a file."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "hi.3mf"
        Mobile.from_word("HI").to_file(out)
        assert out.exists() and out.stat().st_size > 0


def test_sdk_shape_burst():
    """SDK with shape= kwarg."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "hi-burst.3mf"
        Mobile.from_word("HI", shape="burst").to_file(out)
        assert out.exists() and out.stat().st_size > 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"{name} ... ", end="", flush=True)
            fn()
            print("ok")
    print("All tests passed.")
