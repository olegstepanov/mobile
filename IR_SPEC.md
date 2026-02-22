# mobile — Intermediate Representation Specification

From DSL to physical object. Three stages:

```
DSL → ResolvedTree → PartList → STL
```

---

## Stage 1: ResolvedTree

The DSL resolves into a tree where every node has computed physics.

### ResolvedLeaf

```python
@dataclass(frozen=True)
class ResolvedLeaf:
    label:      str
    space:      Space              # original layers
    volume:     float              # net volume (positive − negative), mm³
    weight:     float              # volume × density, grams
    scale:      float              # cumulative scale factor
    rotation:   float              # cumulative rotation, degrees
    bbox:       BBox               # bounding box of the resolved shape
```

### ResolvedBranch

```python
@dataclass(frozen=True)
class ResolvedBranch:
    left:       ResolvedTree
    right:      ResolvedTree
    arc:        Arc                # resolved arc (individual or level default)

    # computed
    weight:     float              # total subtree weight, grams
    pivot:      float              # 0..1 position on arc where string attaches
    pivot_mm:   float              # pivot offset from left endpoint, mm
    angle_eq:   float              # equilibrium tilt angle, degrees
    angle_hint: float              # user-specified rotation hint, degrees
    angle:      float              # final angle (blend of eq + hint), degrees
```

```python
type ResolvedTree = ResolvedBranch | ResolvedLeaf
```

### Computation rules

```
base_mm     = arc.w × weight_right / (weight_left + weight_right)
pivot_mm    = solve_pivot(target_angle)
pivot       = pivot_mm / arc.w
angle_eq    = equilibrium_angle(pivot_mm)    # should match target_angle when solvable
angle       = angle_eq
```

Strategy options (configurable on `Mobile`):
- `"equilibrium"` — ignore hint; choose `target_angle = 0°` (arc hangs level by shifting pivot)
- `"hint"` — choose `target_angle = angle_hint` (solve pivot so the arc's equilibrium tilt matches the hint)
- `"blend"` — choose `target_angle = (1 − blend_ratio) × angle_hint` (default: 30% of hint)

Notes:
- The solver constrains `pivot_mm` to keep the pivot away from either tip
  (see `MobileConfig.hole_tip_inset`). If the requested angle would require
  a pivot outside that span, resolution fails.

---

## Stage 2: PartList

The tree is flattened into a list of printable parts. Each part is a self-contained physical object.

### Part types

```python
type Part = ArcPart | LeafPart | StringPart | HookPart
```

### ArcPart

The curved bar. Extruded from a 2D arc profile.

```python
@dataclass(frozen=True)
class ArcPart:
    id:             str                # unique part id, e.g. "arc-0", "arc-1-L"
    parent_id:      str | None         # parent arc id (None for root)
    side:           Literal["L", "R"] | None  # which side of parent this hangs from

    # geometry
    width:          float              # arc span, mm
    height:         float              # arc sag/rise, mm
    thickness:      float              # extrusion depth, mm (default from config)
    cross_section:  CrossSection       # profile shape of the bar

    # attachment points (in local coordinates, origin = pivot)
    pivot:          Vec2               # (0, 0) by definition
    left_endpoint:  Vec2               # (−pivot_mm, 0) before arc curve
    right_endpoint: Vec2               # (+(w − pivot_mm), 0) before arc curve
    hook_hole:      Vec2               # hole at pivot for string/hook

    # transform (in world coordinates)
    position:       Vec3               # where pivot sits in world space
    angle:          float              # tilt, degrees

    # the 2D arc curve (for extrusion)
    profile:        ArcProfile
```

### ArcProfile

The 2D curve that defines the arc shape. Extruded along Z to create the 3D part.

```python
@dataclass(frozen=True)
class ArcProfile:
    curve:      list[Vec2]         # polyline or bezier control points
    curve_type: Literal["polyline", "cubic_bezier", "quadratic_bezier"]
    bar_width:  float              # width of the bar itself (cross-section), mm
```

### CrossSection

Profile of the bar's cross-section (what you'd see if you sliced it).

```python
@dataclass(frozen=True)
class CrossSection:
    shape:  Literal["rectangle", "circle", "ellipse"]
    width:  float    # mm
    height: float    # mm
```

### LeafPart

A weight/pendant. Extruded from SVG + text outlines.

```python
@dataclass(frozen=True)
class LeafPart:
    id:             str                # e.g. "leaf-Y", "leaf-U"
    parent_arc_id:  str                # which arc this hangs from
    side:           Literal["L", "R"]  # which endpoint

    # shape
    space:          Space              # original DSL layers
    outlines:       list[Outline]      # resolved 2D outlines for extrusion
    bbox:           BBox
    scale:          float
    rotation:       float              # degrees

    # physical
    volume:         float              # mm³
    weight:         float              # grams
    thickness:      float              # extrusion depth, mm

    # attachment
    hook_hole:      Vec2               # hole position in local coords
    position:       Vec3               # world position
```

### Outline

A single 2D outline derived from an `Atom`. Positive outlines are solid, negative outlines are boolean-subtracted.

```python
@dataclass(frozen=True)
class Outline:
    paths:    list[Path2D]         # closed paths (SVG path data or point lists)
    negative: bool                 # True = subtract from volume
    source:   Atom                 # original Svg or Txt
```

### Path2D

```python
@dataclass(frozen=True)
class Path2D:
    commands: list[PathCommand]    # M, L, C, Q, Z — standard SVG path commands
    closed:   bool = True
```

### StringPart

The connecting wire/string between an arc's endpoint and the child below.

```python
@dataclass(frozen=True)
class StringPart:
    id:         str
    from_arc:   str                # parent arc id
    from_point: Literal["pivot", "L", "R"]
    to_part:    str                # child arc or leaf id
    length:     float              # mm
    diameter:   float              # mm (wire gauge)
```

### HookPart

Top-level ceiling hook.

```python
@dataclass(frozen=True)
class HookPart:
    id:         str
    position:   Vec3
    hook_type:  Literal["loop", "S-hook", "swivel"]
    diameter:   float              # mm
```

---

## Stage 3: STL Generation

Each `Part` becomes one or more STL files.

### Pipeline per part

```
Outline (2D) → Extrude (3D) → Boolean ops → Mesh → STL
```

### LeafPart pipeline

```
1. Parse SVG paths → list[Path2D]
2. Parse Txt → font outlines → list[Path2D]
3. For each positive Outline:
     extrude(paths, thickness) → solid mesh
4. For each negative Outline:
     extrude(paths, thickness × 1.01) → cutter mesh  # slight oversize for clean boolean
5. result = union(positives) − union(negatives)
6. Apply scale, rotation
7. Add hook_hole (cylinder boolean subtract)
8. Export STL
```

### ArcPart pipeline

```
1. Generate arc curve from ArcProfile
2. Sweep CrossSection along curve → solid mesh
3. Add holes at pivot, left_endpoint, right_endpoint
     (cylinder boolean subtract, sized for StringPart.diameter)
4. Export STL
```

### StringPart pipeline

```
1. Cylinder(diameter, length)
2. Add loops at both ends (torus boolean union)
3. Export STL
```

### Output structure

```
output/
  mobile.json            # full ResolvedTree + PartList as JSON
  parts/
    hook-0.stl
    arc-0.stl            # root arc
    arc-1-L.stl          # left child of root
    arc-1-R.stl          # right child of root
    arc-2-LL.stl         # etc.
    leaf-Y.stl
    leaf-U.stl
    leaf-R.stl
    leaf-I.stl
    leaf-r.stl
    leaf-i.stl
    leaf-A.stl
    string-0-to-1L.stl
    string-0-to-1R.stl
    ...
  assembly.stl           # all parts in world position (for preview)
  assembly.3mf           # with color/material info (optional)
```

---

## Common types

```python
@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

@dataclass(frozen=True)
class BBox:
    min: Vec2
    max: Vec2

    @property
    def width(self) -> float:  return self.max.x - self.min.x
    @property
    def height(self) -> float: return self.max.y - self.min.y
    @property
    def area(self) -> float:   return self.width * self.height
```

---

## Config

Global defaults for physical properties.

```python
@dataclass
class MobileConfig:
    # material
    density:          float = 1.0        # g/mm³ (PLA ≈ 1.24, wood ≈ 0.5)
    default_thickness: float = 3.0       # mm, extrusion depth for leaves

    # arc
    arc_cross_section: CrossSection = CrossSection("rectangle", 4.0, 3.0)
    arc_thickness:     float = 3.0       # mm

    # string
    string_diameter:   float = 1.0       # mm
    string_material:   Literal["wire", "thread", "rod"] = "wire"

    # hook
    hook_hole_diameter: float = 2.0      # mm

    # balance strategy
    angle_strategy:    Literal["equilibrium", "hint", "blend"] = "blend"
    blend_ratio:       float = 0.7       # weight toward equilibrium (higher => closer to 0°)

    # SVG resolution
    svg_curve_tolerance: float = 0.1     # mm, for bezier flattening
    font:              str = "Cormorant Garamond"
    font_size:         float = 14.0      # mm
```

---

## JSON serialization

The full IR is serializable to JSON for handoff between pipeline stages.

```json
{
  "config": { "density": 1.24, "default_thickness": 3.0, ... },
  "tree": {
    "type": "branch",
    "weight": 17.0,
    "pivot": 0.53,
    "angle": 12.4,
    "arc": { "w": 100, "h": 10 },
    "left": {
      "type": "leaf",
      "label": "Y",
      "weight": 4.0,
      "outlines": [ ... ]
    },
    "right": { "type": "branch", ... }
  },
  "parts": [
    { "type": "arc", "id": "arc-0", ... },
    { "type": "leaf", "id": "leaf-Y", ... },
    ...
  ]
}
```

---

## Summary

```
          DSL                    ResolvedTree              PartList              STL
  ┌─────────────────┐    ┌───────────────────────┐   ┌──────────────────┐   ┌─────────┐
  │ Svg, Txt, Space │    │ weights, pivots,       │   │ ArcPart          │   │ .stl    │
  │ Leaf, _, Arc    │ →  │ equilibrium angles,    │ → │ LeafPart         │ → │ per     │
  │ Level, Mobile   │    │ world positions        │   │ StringPart       │   │ part    │
  │                 │    │                        │   │ HookPart         │   │         │
  └─────────────────┘    └───────────────────────┘   └──────────────────┘   └─────────┘
       human                  physics                   geometry              fabrication
```
