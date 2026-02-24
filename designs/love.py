"""L-O-V-E mobile: two levels, three arcs, four letters.

Level 0: one arc with no letters (two holes for child arcs)
Level 1: left arc (L, O) rotated +30°, right arc (V, E) rotated -30°
"""

from pathlib import Path

from mobile import Arc, Mobile, MobileConfig, Svg, Txt, _

here = Path(__file__).parent

circle = Svg(str(here / "circle.svg"))

config = MobileConfig(
    font_path=str(here.parent / "fonts" / "StardosStencil-Regular.ttf"),
    font_size=25.0,
    angle_strategy="hint",
)

L = circle & ~Txt("L")
O = circle & ~Txt("O")
V = circle & ~Txt("V")
E = circle & ~Txt("E")

mobile = Mobile([
    [_(0, 0)]              @ Arc(120, 10),
    [_(L, O) % 30, _(V, E) % -30] @ Arc(50, 8),
], config=config)

if __name__ == "__main__":
    output = here.parent / "output" / Path(__file__).stem
    mobile.build(output)
    print(f"STLs written to {output}")
