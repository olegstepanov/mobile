"""YURIKA mobile design."""

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
Y = circle & ~Txt("Y")
U = circle & ~Txt("U")
R = circle & ~Txt("R")
I = circle & ~Txt("I")
r = circle & ~Txt("R")
i = circle & ~Txt("I")
A = circle & ~Txt("A")

# ── mobile ────────────────────────────────────────────────────
mobile = Mobile([
    [_(0, 0)]                                                     @ Arc(180, 10),
    [_(Y, 0) % +15,                      _(0, 0) % -15]           @ Arc(70,  10),
    [_(U, R),            _(I, r) % +5,   _(i, A) % -5]            @ Arc(30,  10),
], config=config)

# ── build ─────────────────────────────────────────────────────
if __name__ == "__main__":
    output = here.parent / "output" / Path(__file__).stem
    mobile.build(output)
    print(f"Built to {output}/")
    for f in sorted(output.iterdir()):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")
