"""Minimal binary STL helpers used for single-file export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

Triangle = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]


@dataclass(frozen=True)
class Bounds:
    min_x: float
    max_x: float


def read_binary_stl(path: Path) -> tuple[list[Triangle], Bounds]:
    triangles = []
    min_x = float("inf")
    max_x = float("-inf")

    with path.open("rb") as f:
        f.read(80)
        (num_tris,) = struct.unpack("<I", f.read(4))
        for _ in range(num_tris):
            data = f.read(50)
            vals = struct.unpack("<12fH", data)
            v0 = (vals[3], vals[4], vals[5])
            v1 = (vals[6], vals[7], vals[8])
            v2 = (vals[9], vals[10], vals[11])
            triangles.append((v0, v1, v2))
            for vx in (v0[0], v1[0], v2[0]):
                min_x = min(min_x, vx)
                max_x = max(max_x, vx)

    if min_x == float("inf"):
        min_x = 0.0
        max_x = 0.0

    return triangles, Bounds(min_x=min_x, max_x=max_x)


def write_binary_stl(path: Path, triangles: list[Triangle]) -> None:
    with path.open("wb") as f:
        header = b"mbl packed mobile STL"[:80]
        f.write(header + b"\0" * (80 - len(header)))
        f.write(struct.pack("<I", len(triangles)))
        for v0, v1, v2 in triangles:
            f.write(struct.pack("<3f", 0.0, 0.0, 0.0))
            f.write(struct.pack("<3f", *v0))
            f.write(struct.pack("<3f", *v1))
            f.write(struct.pack("<3f", *v2))
            f.write(struct.pack("<H", 0))


def merge_stl_files(inputs: list[Path], output: Path, spacing: float = 10.0) -> Path:
    """Merge multiple binary STL files into one, laid out along +X."""
    cursor_x = 0.0
    merged: list[Triangle] = []

    for path in inputs:
        tris, bounds = read_binary_stl(path)
        offset_x = cursor_x - bounds.min_x
        translated = []
        for v0, v1, v2 in tris:
            tv0 = (v0[0] + offset_x, v0[1], v0[2])
            tv1 = (v1[0] + offset_x, v1[1], v1[2])
            tv2 = (v2[0] + offset_x, v2[1], v2[2])
            translated.append((tv0, tv1, tv2))
        merged.extend(translated)

        width = bounds.max_x - bounds.min_x
        cursor_x += width + spacing

    output.parent.mkdir(parents=True, exist_ok=True)
    write_binary_stl(output, merged)
    return output
