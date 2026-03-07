# mbl

![mbl demo](mbl/assets/demo.gif)

Generate printable hanging mobiles with letters and shapes.

```bash
uv sync
uv run mbl "HELLO"
```

Shape modes:

```bash
# Built-in shape, normalized to 25 mm diameter at shape-scale 1.0
uv run mbl "LOVE" --shape heart

# Custom SVG, normalized to 25 mm diameter at shape-scale 1.0
uv run mbl "HELLO" --shape custom-shape.svg

# Use whitespace if no text is needed
uv run mbl "     " --shape shopify

# Scale shape and font (relative to the scaled shape)
uv run mbl "HELLO" --shape custom-shape.svg --shape-scale 1.5 --text-scale 0.8

# Print a stage timing profile
uv run mbl "HELLO" --shape custom-shape.svg --profile
```

Key flags:
- `--shape`: `circle` (default), `burst`, `star`, `heart`, `shopify`, `blank`, or path to `.svg`
- `--shape-scale`: background shape multiplier (default `1.0`)
- `--text-scale`: text multiplier (default `0.8`)
- `--font-size`: base font size in mm
- `--output`: `.3mf` (default) or `.stl`

## SDK (golden path)

```python
from mbl import Mobile

Mobile.from_word("HELLO").to_file("hello.3mf")
Mobile.from_word("HELLO", shape="burst").to_file("hello-burst.3mf")
Mobile.from_word("HELLO", shape="custom-shape.svg", shape_scale=1.5, text_scale=0.8).to_file("hello-scaled.3mf")
Mobile.from_word("HELLO", shape="blank").to_file("hello-blank.3mf")  # Print letters as solids in Helvetica
```

## SDK (custom DSL, mixed shapes)

```python
from mbl import Arc, Leaf, Mobile, stencil_cut

mobile = Mobile(
    [
        Arc(88, 12)
        @ (
            stencil_cut("S", base=Leaf.circle(), text_scale=0.7),
            stencil_cut("U", base=Leaf.burst(), text_scale=0.7),
        ),
    ]
)

mobile.to_file("sun-mixed-shapes.3mf")
```

Two-row variant:

```python
from mbl import Arc, Leaf, Mobile, stencil_cut

mobile = Mobile(
    [
        Arc(88, 12) @ (stencil_cut("S", base=Leaf.circle(), text_scale=0.7), None),
        Arc(64, 9)
        @ (
            stencil_cut("U", base=Leaf.burst(), text_scale=0.7),
            stencil_cut("N", base=Leaf.heart(), text_scale=0.7),
        ),
    ]
)

mobile.to_file("sun-two-row.3mf")
```

## Shape semantics

- Default shape is `circle`.
- `shape_scale=1.0` means shape diameter is normalized to `25 mm`.
- Built-ins (`circle`, `burst`, `star`, `heart`, `shopify`) are normalized the same way.
- Custom SVGs are loaded and normalized to `25 mm` diameter before `shape_scale` is applied.
- Text subtraction/geometry uses `text_scale` independently of `shape_scale`.
- Simulation runs after shape/text scaling, so balancing uses final scaled geometry.
