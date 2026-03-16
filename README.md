# mbl

![mbl demo](mbl/assets/demo.gif)

Generate printable hanging mobiles with letters and shapes.

```bash
uv tool install --upgrade git+https://github.com/astaff/mobile.git
mbl "HELLO"
```

Shape modes:

```bash
# Built-in shape, normalized to 25 mm diameter at shape-scale 1.0
mbl "LOVE" --shape heart

# Seven hearts for mom
mbl "❤️❤️❤️❤️❤️❤️❤️"

# MOM stencil-cut into hearts
mbl "MOM" --shape heart

# Emoji are mapped to built-in shapes automatically
mbl "⭐❤️😊🐙☀️"

# Right-to-left languages are detected automatically
mbl "שלום" --shape blank --text-scale 2.0

# Custom SVG, normalized to 25 mm diameter at shape-scale 1.0
mbl "HELLO" --shape custom-shape.svg

# Use whitespace if no text is needed
mbl "     " --shape shopify

# Scale shape and font (relative to the scaled shape)
mbl "HELLO" --shape custom-shape.svg --shape-scale 1.5 --text-scale 0.8

# Print a stage timing profile
mbl "HELLO" --shape custom-shape.svg --profile
```

Key flags:
- `--shape`: `circle` (default), `burst`, `star`, `heart`, `shopify`, `peace`, `cup`, `eclipse`, `octopus`, `smile`, `sun`, `blank`, or path to `.svg`
- `--shape-scale`: background shape multiplier (default `1.0`)
- `--text-scale`: text multiplier (default `0.8`)
- `--leaf-mass-scale`: solver calibration for leaf mass (`1.0` same, `<1` lighter, `>1` heavier)

## SDK

```python
from pathlib import Path
from mbl import Arc, Leaf, to_3mf

STATES = Path(__file__).parent / "states"

def leaf(name: str, scale: float = 0.17) -> Leaf:
    return Leaf.from_svg(STATES / f"{name}.svg") * scale

levels = [
                               [             Arc(100, 22) @ leaf("ME")],
                   [          Arc(90, 18)         ],
    [leaf("VT") @ Arc(45, 12) @ leaf("NH"),      Arc(50, 10) @ leaf("MA")],
                                 [leaf("CT") @ Arc(35, 10) @ leaf("RI")],
]

# pass config=MobileConfig(...) to override generation parameters
out = to_3mf(levels, "new-england.3mf")
```

## Shape semantics

- Default shape is `circle`.
- `shape_scale=1.0` means shape diameter is normalized to `25 mm`.
- Built-ins (`circle`, `burst`, `star`, `heart`, `shopify`, `peace`, `cup`, `eclipse`, `octopus`, `smile`) are normalized the same way.
- Custom SVGs are loaded and normalized to `25 mm` diameter before `shape_scale` is applied.
- Text subtraction/geometry uses `text_scale` independently of `shape_scale`.

## Creative Commons attribution

The following built-in shapes are sourced from [Noun Project](https://thenounproject.com/) under Creative Commons:

| Shape | Author | Noun Project ID |
|-------|--------|-----------------|
| cup | Adrien Coquet | 7683336 |
| eclipse | Amazona Adorada | 7666379 |
| octopus | Moreno | 8216521 |
| smile | Dwi ridwanto | 7786982 |
| sun | Creative Stall | 130085 |
