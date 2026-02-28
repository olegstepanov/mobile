"""CLI entrypoint for mbl."""

from __future__ import annotations

import argparse
from pathlib import Path

from mbl import Mobile, MobileConfig


def _default_font_path() -> str | None:
    font = Path(__file__).resolve().parent / "assets" / "StardosStencil-Regular.ttf"
    return str(font) if font.exists() else None


def _default_output_path(word: str) -> Path:
    stem = "".join(ch.lower() if ch.isalnum() else "-" for ch in word).strip("-")
    if not stem:
        stem = "mbl"
    while "--" in stem:
        stem = stem.replace("--", "-")
    return Path(f"{stem}.3mf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mbl",
        description="Generate a parametric hanging mobile model from a word.",
    )
    parser.add_argument("word", help="Word to render into a mobile")
    parser.add_argument("--font", dest="font_path", help="Path to stencil TTF/OTF font")
    parser.add_argument(
        "--output",
        default=None,
        help="Output path (.stl or .3mf, default: <word>.3mf)",
    )
    parser.add_argument("--hook-style", choices=["line", "hook"], default="line")
    parser.add_argument(
        "--leaf-shape",
        choices=["circle", "burst", "star"],
        default="circle",
        help="Base leaf shape for letters/spaces",
    )
    parser.add_argument("--font-size", type=float, default=22.0, help="Stencil text size in mm")
    parser.add_argument("--width", type=float, default=80.0, help="Top arc width (mm)")
    parser.add_argument("--height", type=float, default=12.0, help="Top arc sagitta (mm)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    font_path = args.font_path or _default_font_path()
    config = MobileConfig(
        font_path=font_path,
        font_size=args.font_size,
        hook_style=args.hook_style,
    )

    mobile = Mobile.from_word(
        args.word,
        width=args.width,
        height=args.height,
        leaf_shape=args.leaf_shape,
        config=config,
    )

    output = Path(args.output) if args.output else _default_output_path(args.word)
    out_path = mobile.to_file(output)
    print(f"Generated {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
