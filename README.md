# mbl

Generate parametric hanging mobiles with a small Python DSL and export printable `.3mf` / `.stl`.

## CLI

```bash
pip install mbl
mbl "HELLO" --output hello.3mf
mbl "XYZ" --leaf-shape burst --output xyz.3mf
```

Key flags:
- `--output`: output file (`.3mf` default, `.stl` supported)
- `--font`: stencil font file (`.ttf` / `.otf`)
- `--font-size`: letter size in mm
- `--leaf-shape`: `circle`, `burst`, `star`
- `--hook-style`: `line` or `hook`
- `--width`, `--height`: top arc dimensions

## Python SDK DSL

```python
from mbl import Mobile

Mobile.from_word("HELLO", leaf_shape="circle").to_file("hello.3mf")
Mobile.from_word("XYZ", leaf_shape="burst").to_file("xyz.3mf")
```

## DSL shape

- Single bind: `Arc(w, h) @ (left, right)`
- Right-hole shorthand: `Arc(w, h) @ (left,)`
- Row map bind: `Arc(w, h) @ [(a, b), (c,)]`
