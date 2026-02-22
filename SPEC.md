# mobile — Specification

A typed, minimalist Python DSL for describing balanced hanging mobiles as
binary trees with positive/negative space composition, auto-balanced pivots,
and STL generation via build123d.

Python 3.13+. Haskell-inspired operator conventions. build123d for CAD.

---

## Pipeline overview

```
DSL  →  ResolvedTree  →  STL files
```

| Stage | Module | Purpose |
|---|---|---|
| DSL | `mobile.dsl` | User-facing types and operator overloading |
| Resolve | `mobile.resolve` | Level-to-tree linking, area/weight computation, pivot solving |
| Generate | `mobile.generate` | build123d geometry creation, boolean ops, STL export |
| Arc math | `mobile.arc_math` | Pure math for sagitta arcs and pivot solving |
| Config | `mobile.config` | Global physical/rendering defaults |
| Errors | `mobile.errors` | Exception hierarchy |

---

## 1. DSL primitives

### Svg

An SVG image shape. Has area and density → contributes to weight.

```python
circle = Svg("circle.svg")
star   = Svg("star.svg")
```

Fields: `path: str`, `neg: bool = False`

### Txt

A text glyph shape. Has area and density → contributes to weight.

```python
label = Txt("Y")
```

Fields: `text: str`, `neg: bool = False`

### Atom

```python
Atom = Svg | Txt
```

---

## 2. Operators

Six operators. Fixed meanings regardless of context.

| Op | Name | Meaning |
|----|---------|---------------------|
| `~` | negate | flip positive ↔ negative space |
| `&` | compose | layer atoms into a compound shape |
| `@` | bind | attach an `Arc` to a node or level |
| `%` | rotate | rotation in degrees |
| `*` | scale | scale factor |
| `\|` | pipe | convert atom/space to `Leaf` (sugar; auto-promotion preferred) |

### Precedence (Python built-in, highest first)

1. `~` (unary)
2. `*` (multiplication)
3. `@` (matmul)
4. `%` (modulo)
5. `&` (bitwise and)
6. `|` (bitwise or)

---

## 3. Space composition

### Negate (`~`)

Flips an atom between positive and negative space. Positive space adds
volume (and therefore weight). Negative space subtracts volume.

```python
Txt("Y")         # positive — adds mass
~Txt("Y")        # negative — subtracts mass (cutout)
~~Txt("Y")       # double negate — positive again
```

Returns: a new `Atom` with `neg` flipped.

Implementation: `Svg.__invert__` / `Txt.__invert__` return a copy with
`neg = not self.neg`.

### Compose (`&`)

Layers atoms left to right into a `Space`. Rendering order = layer order.

```python
Svg("circle.svg") & Txt("Y")                         # circle with Y overlaid
Svg("circle.svg") & ~Txt("I")                        # circle with I-shaped cutout
Svg("circle.svg") & ~Svg("dot.svg") & Txt("R")       # three layers
```

Returns: `Space`

Associativity: left. `a & b & c` = `(a & b) & c`.

Both `Atom & Atom → Space` and `Space & Atom → Space` work.
`Atom.__and__` creates `Space((self, other))`.
`Space.__and__` appends: `Space(self.layers + (other,))`.

### Space

```python
@dataclass(frozen=True)
class Space:
    layers: tuple[Atom, ...]
```

---

## 4. Leaf

A `Leaf` is a renderable weighted endpoint of the mobile.

```python
@dataclass(frozen=True)
class Leaf:
    space:    Space
    scale:    float = 1.0
    rotation: float = 0.0     # degrees
```

### Creation

A `Leaf` is created by auto-promotion: any `Atom`, `Space`, or explicit
`Leaf` used where a `Leaf` is expected is automatically converted. The `|`
operator also works but is optional sugar.

```python
# These are all equivalent in Node context:
_(Svg("circle.svg") & Txt("Y"), 0)    # Space auto-promoted to Leaf
_(Leaf(Space((Svg("circle.svg"), Txt("Y")))), 0)  # explicit
```

Auto-promotion rules (via `_to_leaf`):
- `int 0` → `None` (hole)
- `Leaf` → returned as-is
- `Svg` or `Txt` → `Leaf(Space((atom,)))`
- `Space` → `Leaf(space)`

### Leaf transforms

```python
Y * 0.8          # scale (multiplicative): Leaf(space, scale=0.8)
Y % 45           # rotate (additive): Leaf(space, rotation=45)
Y * 0.8 % 45     # both: Leaf(space, scale=0.8, rotation=45)
```

Transforms also work on `Atom` and `Space` — they auto-promote to `Leaf`
first, then apply the transform.

### Weight computation

```
area   = Σ positive_atom_areas − Σ negative_atom_areas    (mm²)
volume = area × leaf_thickness                             (mm³)
weight = volume × density × cumulative_scale               (grams)
```

Where:
- `density` is from `MobileConfig.density` (default 1.0 g/mm³)
- `leaf_thickness` is from `MobileConfig.leaf_thickness` (default 2.0 mm)
- `cumulative_scale` = leaf's own `scale` × all ancestor level `scale` values
- Atom areas are computed by build123d: `import_svg` for SVG files,
  `Compound.make_text` for text glyphs, then `sum(face.area for face in faces)`

---

## 5. Node (`_`)

A binary node in the mobile tree. Each node has a left child and a right child.

```python
_(left, right)
```

```python
@dataclass(frozen=True)
class Node:
    left:     Leaf | None      # None = hole
    right:    Leaf | None      # None = hole
    arc:      Arc | None = None
    rotation: float = 0.0      # degrees
```

Children: `Leaf | Atom | Space | 0`

`0` is a hole — an attachment point for the next level's arc.

```python
_(Y, 0)      # Y on left, hole on right
_(0, 0)      # two holes (both continue to next level)
_(U, R)      # two leaves (terminal)
```

The `_` function converts children via `_to_leaf`: auto-promotes atoms/spaces
to `Leaf`, converts `0` to `None`.

### Node bind (`@`)

Binds a per-node `Arc`. Overrides the level default.

```python
_(Y, 0) @ Arc(90, 8)
```

Returns: `Node` with `arc` set. Implementation: `Node.__matmul__`.

### Node rotate (`%`)

Rotation hint for the node's arc in degrees. Additive.

```python
_(Y, 0) % +15
_(0, 0) % -15
```

Returns: `Node` with `rotation` accumulated. Implementation: `Node.__mod__`.

### Node chaining

`@` and `%` chain left to right:

```python
_(Y, 0) @ Arc(90, 8) % 15     # own arc, rotated 15°
```

---

## 6. Arc

Pure geometry. The curved bar a node hangs from. Modeled as a **sagitta
(circular) arc**: a circular arc defined by chord length and sagitta (rise).

```python
@dataclass(frozen=True)
class Arc:
    w: float   # width (chord/span), mm
    h: float   # height (sagitta/rise), mm
```

The `Arc` also implements `__rmatmul__` so that `list @ Arc → Level` works
(Python tries `list.__matmul__` first, which is undefined, then falls back
to `Arc.__rmatmul__`).

### Sagitta arc geometry

Given chord `w` and sagitta `h`:

```
R = w² / (8·h) + h / 2          (radius of the circular arc)
center_y = h − R                 (Y of circle center, below chord)
y(x) = center_y + √(R² − (x − mid_x)²)
```

Where `mid_x` is the midpoint of the chord. The arc's peak is at
`y = h` (at the midpoint), and the endpoints are at `y = 0`.

---

## 7. Level

A level is a list of nodes bound to an arc.

```python
@dataclass(frozen=True)
class Level:
    nodes:    tuple[Node, ...]
    arc:      Arc | None = None
    rotation: float = 0.0
    scale:    float = 1.0
```

### Level bind (`@`)

Binds a default `Arc` to all nodes in the level that don't have their own.

```python
[_(Y, 0) % +15, _(0, 0) % -15]  @ Arc(90, 8)
```

### Level rotate (`%`)

Bulk rotation applied to all nodes on the level. Individual node `%`
composes **additively** with level `%`:

```python
[_(Y, 0) % +5, _(0, 0) % -5]  @ Arc(90, 8) % 10
# Y node effective rotation: +5 + 10 = +15°
# 0 node effective rotation: -5 + 10 = +5°
```

### Level scale (`*`)

Bulk weight scale applied to all leaves on the level. Individual leaf `*`
composes **multiplicatively** with level `*`:

```python
[_(U, R * 0.8)]  @ Arc(80, 6) * 0.9
# U effective scale: 1.0 × 0.9 = 0.9
# R effective scale: 0.8 × 0.9 = 0.72
```

### Levels without `@`

Valid only if every node has its own arc via `@`:

```python
[_(Y, 0) @ Arc(90, 8) % 15,  _(0, 0) @ Arc(70, 8) % -15]
```

A level where any node lacks both individual and level arc raises
`MobileArcError`.

---

## 8. Mobile

The top-level container. Validates topology on construction.

```python
class Mobile:
    def __init__(
        self,
        levels: list[Level | list[Node]],
        config: MobileConfig | None = None,
    ): ...
```

Accepts a list of `Level` objects or bare `list[Node]` (auto-wrapped into
`Level(tuple(nodes))`). If no `config` is provided, uses `MobileConfig()`
defaults.

### Validation (on construction)

1. **Non-empty**: at least one level, else `MobileEmptyError`
2. **Arc coverage**: every node must have an arc (individual or level default),
   else `MobileArcError`
3. **Hole/node matching**: holes in level N must equal nodes in level N+1,
   else `MobileShapeError`
4. **Last level closed**: last level must have zero holes,
   else `MobileShapeError`

### Level-to-tree resolution

Levels are listed top to bottom. Holes (`0` / `None`) in level N become
attachment points for nodes in level N+1, read left to right.

```
Level 0:  _(0, 0)                     → 2 holes
Level 1:  _(Y, 0)  _(0, 0)           → Y is leaf, 3 holes remain
Level 2:  _(U, R)  _(I, r)  _(i, A)  → all leaves, 3 nodes fill 3 holes
```

### `Mobile.build(output_dir)`

Convenience method that runs the full pipeline:

```python
def build(self, output_dir: str | Path) -> None:
    tree = resolve(self)
    generate(tree, self.config, Path(output_dir))
```

---

## 9. Resolution (`mobile.resolve`)

Converts a `Mobile` into a `ResolvedTree` in two phases.

### Phase 1: Structural linking (top-down)

`_link_levels(mobile)` converts the level-based representation into a
single rooted binary tree of `_IntermediateNode` objects.

For each level's node:
- `arc` = node's own arc if set, else level's arc
- `effective_rotation` = node's rotation + level's rotation
- `scale` = level's scale

Holes in level N are filled left-to-right by nodes from level N+1.

### Phase 2: Weight computation (bottom-up)

`_resolve_node` recurses bottom-up:

#### ResolvedLeaf

```python
@dataclass(frozen=True)
class ResolvedLeaf:
    label:    str         # from first Txt atom, or SVG path, or "?"
    space:    object      # the original dsl.Space
    area:     float       # net area (positive − negative), mm²
    volume:   float       # area × leaf_thickness, mm³
    weight:   float       # volume × density × cumulative_scale, grams
    scale:    float       # cumulative scale factor (leaf × ancestor levels)
    rotation: float       # leaf rotation, degrees
```

Area is computed by build123d:
- **Svg atoms**: `import_svg(path)` → filter `Face` objects → sum `.area`
- **Txt atoms**: `Compound.make_text(text, font_size, font, font_path,
  font_style=REGULAR, text_align=(CENTER, CENTER))` → sum face areas

A leaf with negative weight raises `MobileWeightError`.

#### ResolvedBranch

```python
@dataclass(frozen=True)
class ResolvedBranch:
    left:       ResolvedLeaf | ResolvedBranch
    right:      ResolvedLeaf | ResolvedBranch
    arc:        Arc
    weight:     float       # left.weight + right.weight
    pivot:      float       # 0..1, pivot_mm / arc.w
    pivot_mm:   float       # pivot offset from left endpoint, mm
    angle_eq:   float       # equilibrium tilt angle, degrees
    angle_hint: float       # user-specified rotation hint, degrees
    angle:      float       # final angle = angle_eq (after solving)
```

```python
ResolvedTree = ResolvedLeaf | ResolvedBranch
```

### Pivot solving

The pivot position is solved so that the arc's equilibrium tilt matches
a target angle determined by the angle strategy.

**Equilibrium angle formula:**

```
base_mm   = arc.w × weight_right / (weight_left + weight_right)
pivot_y   = Y coordinate of pivot point on the sagitta arc (at x=0)
angle_eq  = atan2(pivot_mm − base_mm, pivot_y)
```

The pivot sits *on the arc curve* (not on the chord), providing a vertical
offset that makes the equilibrium angle statically determined.

**Target angle by strategy** (configured on `MobileConfig.angle_strategy`):

| Strategy | Target angle |
|---|---|
| `"equilibrium"` | `0°` (arc hangs level) |
| `"hint"` | `angle_hint` (user's rotation value) |
| `"blend"` (default) | `(1 − blend_ratio) × angle_hint` |

The solver finds `pivot_mm` via bisection such that `equilibrium_angle(pivot_mm) = target_angle`.

**Constraints:**
- `pivot_mm` is clamped to `[hole_tip_inset, arc.w − hole_tip_inset]`
- If the target angle is not achievable within constraints, raises
  `MobilePivotError` with the achievable angle range

**Final angle:** `angle = angle_eq` (the actual equilibrium angle at the
solved pivot position, which should match the target when solvable).

### Scale propagation

`cumulative_scale` flows top-down:
- Root starts at `1.0`
- Each `_IntermediateNode` multiplies by its level's `scale`
- Each `Leaf` multiplies by its own `scale`

---

## 10. STL generation (`mobile.generate`)

Each `ResolvedBranch` produces **one fused STL file** containing the arc bar
plus any direct leaf children (leaves whose parent is this branch). Sub-arc
children are separate STL files.

### Arc bar creation

1. Sweep a rectangular cross-section (`arc_bar_width × arc_bar_height`) along
   a `SagittaArc` from `(-pivot_mm, 0, 0)` to `(arc_w - pivot_mm, 0, 0)`
   with sagitta `arc_h`.
2. The arc is in local coordinates with origin at the pivot point.

### Leaf body creation

For each direct leaf child:

1. **Positive atoms** (Svg with `neg=False`): `import_svg` → extrude faces
   by `leaf_thickness` → fuse into a single positive body.
2. **Negative atoms** (Svg with `neg=True`): extrude faces by
   `leaf_thickness × 1.5` (oversize for clean boolean cut) → collect as cutters.
3. **Text atoms** (Txt, always treated as negative cutters in the current
   design pattern): `Compound.make_text` → extrude faces by
   `leaf_thickness × 1.5` → re-center to visual bounding box center →
   collect as cutters.

**Centering:**
- The positive body is centered at origin (XY center of bounding box → (0,0),
  Z midplane → 0).
- SVG-sourced cutters are shifted by the same centering offset.
- Text cutters (already at origin from make_text centering) are moved to
  the positive body's center before the global centering pass.

**Transforms:**
- If `scale ≠ 1.0`: scale both body and cutters.
- If `rotation ≠ 0.0`: rotate both body and cutters around Z axis.

### Assembly

For each branch:

1. Create arc bar at origin (pivot at (0,0,0)).
2. Compute endpoint positions:
   - Left: `(-pivot_mm, arc_y(-pivot_mm), 0)`
   - Right: `(arc_w - pivot_mm, arc_y(arc_w - pivot_mm), 0)`
3. Fuse positive leaf bodies at their respective endpoints.
4. Apply all negative cutters at their respective endpoints.
5. Cut **pivot hole**: vertical cylinder at `(0, arc_y(0), 0)`, aligned
   with Y axis (gravity direction), radius = `hole_diameter / 2`.
6. Cut **endpoint holes** only for sub-arc children (not leaf children):
   radial cylinders near each endpoint, pointing toward the arc's center
   of curvature, inset from the tip by `hole_tip_inset` mm.
7. Export as STL.

### Output structure

```
output/
  arc-0.stl              # root branch (arc + fused leaves)
  arc-L.stl              # left child of root (if sub-arc)
  arc-R.stl              # right child of root (if sub-arc)
  arc-LL.stl             # left-left grandchild
  arc-LR.stl             # left-right grandchild
  arc-RL.stl             # etc.
  ...
```

Naming convention:
- Root: `arc-0.stl`
- Children: `arc-{path}.stl` where path is a string of `L`/`R` choices
  from root to that branch

Note: there are no separate leaf STL files, string STL files, or hook STL
files. Leaves are fused into their parent arc's STL. Strings and hooks are
not generated.

---

## 11. Configuration (`mobile.config`)

```python
@dataclass
class MobileConfig:
    # Material
    density:               float = 1.0      # g/mm³ (PLA ≈ 1.24, wood ≈ 0.5)
    leaf_thickness:        float = 2.0      # mm, extrusion depth for leaves

    # Arc cross-section
    arc_bar_width:         float = 2.0      # mm
    arc_bar_height:        float = 2.0      # mm

    # Holes
    hole_diameter:         float = 0.8      # mm (sized for fishing line)
    hole_tip_inset:        float = 1.0      # mm inward from arc tip for child holes

    # Typography
    font:                  str = "Cormorant Garamond"
    font_path:             str | None = None  # path to .ttf/.otf (overrides font name)
    font_size:             float = 14.0     # mm

    # Balance strategy
    angle_strategy:        str = "blend"    # "equilibrium" | "hint" | "blend"
    blend_ratio:           float = 0.7      # weight toward equilibrium (higher → closer to 0°)

    # STL export quality
    stl_tolerance:         float = 1e-4     # mm, linear deflection for mesh
    stl_angular_tolerance: float = 0.01     # radians (~0.6°), angular deflection
```

---

## 12. Errors (`mobile.errors`)

| Exception | Condition |
|---|---|
| `MobileError` | Base class for all mobile errors |
| `MobileShapeError` | Holes in level N ≠ nodes in level N+1, or last level has holes |
| `MobileArcError` | Node without arc and no level default |
| `MobileWeightError` | Negative net weight (too many cutouts) |
| `MobilePivotError` | Requested angle requires impossible pivot position |
| `MobileEmptyError` | Empty mobile (no levels) |

Hierarchy: all inherit from `MobileError` which inherits from `Exception`.

---

## 13. Operator dispatch table

What each operator does on each type:

| Expression | Returns | Mechanism |
|---|---|---|
| `~atom` | `Atom` | `__invert__`: flip `neg` field |
| `atom & atom` | `Space` | `__and__`: create `Space((self, other))` |
| `space & atom` | `Space` | `__and__`: append `Space(self.layers + (other,))` |
| `atom * float` | `Leaf` | `__mul__`: auto-promote to `Leaf`, then scale |
| `atom % float` | `Leaf` | `__mod__`: auto-promote to `Leaf`, then rotate |
| `atom \| _` | `Leaf` | `__or__`: auto-promote (other operand ignored) |
| `space * float` | `Leaf` | `__mul__`: auto-promote to `Leaf`, then scale |
| `space % float` | `Leaf` | `__mod__`: auto-promote to `Leaf`, then rotate |
| `space \| _` | `Leaf` | `__or__`: auto-promote (other operand ignored) |
| `leaf * float` | `Leaf` | `__mul__`: `Leaf(space, scale * float, rotation)` |
| `leaf % float` | `Leaf` | `__mod__`: `Leaf(space, scale, rotation + float)` |
| `_(l, r)` | `Node` | function: `Node(_to_leaf(l), _to_leaf(r))` |
| `node @ arc` | `Node` | `__matmul__`: set `arc` field |
| `node % float` | `Node` | `__mod__`: accumulate `rotation` |
| `list @ arc` | `Level` | `Arc.__rmatmul__`: `Level(tuple(list), arc)` |
| `level % float` | `Level` | `__mod__`: accumulate `rotation` |
| `level * float` | `Level` | `__mul__`: accumulate `scale` |

---

## 14. Full example

```python
from pathlib import Path
from mobile import Svg, Txt, _, Arc, Mobile, MobileConfig

# ── paths relative to this file ──────────────────────────────
here = Path(__file__).parent
circle = Svg(str(here / "circle.svg"))

# ── config ────────────────────────────────────────────────────
config = MobileConfig(
    font_path=str(here.parent / "fonts" / "StardosStencil-Regular.ttf"),
    font_size=25.0,
    angle_strategy="hint",
)

# ── leaves ────────────────────────────────────────────────────
Y = circle & ~Txt("Y")       # circle with Y cutout
U = circle & ~Txt("U")       # circle with U cutout
R = circle & ~Txt("R")
I = circle & ~Txt("I")
r = circle & ~Txt("R")       # lowercase uses same glyph
i = circle & ~Txt("I")
A = circle & ~Txt("A")

# ── mobile ────────────────────────────────────────────────────
mobile = Mobile([
    [_(0, 0)]                                                     @ Arc(180, 10),
    [_(Y, 0) % +15,                      _(0, 0) % -15]          @ Arc(70,  10),
    [_(U, R),            _(I, r) % +5,   _(i, A) % -5]           @ Arc(30,  10),
], config=config)

# ── build ─────────────────────────────────────────────────────
if __name__ == "__main__":
    output = here.parent / "output"
    mobile.build(output)
```

### Tree structure produced

```
              arc-0 (180mm, h=10)
             /                    \
        arc-L (70mm, h=10)     arc-R (70mm, h=10)
        hint=+15°              hint=-15°
       /        \             /        \
      Y       arc-LL       arc-RL     arc-RR
  (leaf)    (30mm,h=10)  (30mm,h=10) (30mm,h=10)
             hint=0°      hint=+5°    hint=-5°
            /     \       /     \     /     \
           U       R     I       r   i       A
```

### STL files produced

```
output/
  arc-0.stl       # root arc bar only (both children are sub-arcs)
  arc-L.stl       # left arc bar + Y leaf fused at left endpoint
  arc-R.stl       # right arc bar only (both children are sub-arcs)
  arc-LL.stl      # arc bar + U (left) + R (right) fused
  arc-RL.stl      # arc bar + I (left) + r (right) fused
  arc-RR.stl      # arc bar + i (left) + A (right) fused
```

---

## 15. Dependencies

- **build123d**: CAD kernel for geometry creation, boolean operations,
  SVG import, text-to-outline, sweep, extrude, STL export
- **Python 3.13+**: for `type X = A | B` union syntax and dataclass features
