"""mobile.blender_pivot — Compute center of mass from binary STL files.

Standalone module — no mobile.* or build123d imports.  Uses the signed
tetrahedra method to compute the volume-weighted center of mass from a
closed triangular mesh, giving the exact mass distribution of each arc
bar with its fused leaf bodies.
"""

from __future__ import annotations

import math
import struct


def _circle_radius(chord: float, sagitta: float) -> float:
    return (chord ** 2) / (8.0 * sagitta) + sagitta / 2.0


def arc_y_at_x(arc_w: float, arc_h: float, pivot_mm: float, x: float) -> float:
    """Y coordinate on the sagitta arc at local X (origin = pivot on chord)."""
    if arc_h == 0:
        return 0.0
    left_x = -pivot_mm
    right_x = arc_w - pivot_mm
    mid_x = (left_x + right_x) / 2.0
    r = _circle_radius(arc_w, arc_h)
    center_y = arc_h - r
    dx = x - mid_x
    disc = r * r - dx * dx
    if disc <= 0:
        return 0.0
    return center_y + math.sqrt(disc)


def compute_com(stl_path: str) -> tuple[float, float, float, float]:
    """Compute volume-weighted center of mass from a binary STL file.

    Uses the signed tetrahedra method: each triangle forms a tetrahedron
    with the origin, and the signed volume gives exact COM for a closed mesh.

    Returns (com_x, com_y, com_z, volume).
    """
    with open(stl_path, "rb") as f:
        f.read(80)  # header
        (num_tris,) = struct.unpack("<I", f.read(4))

        vol_total = 0.0
        com_x = 0.0
        com_y = 0.0
        com_z = 0.0

        for _ in range(num_tris):
            data = f.read(50)  # 12 (normal) + 36 (3 vertices) + 2 (attrib)
            vals = struct.unpack("<12fH", data)

            v0 = (vals[3], vals[4], vals[5])
            v1 = (vals[6], vals[7], vals[8])
            v2 = (vals[9], vals[10], vals[11])

            # Signed volume of tetrahedron formed with origin
            vol = (
                v0[0] * (v1[1] * v2[2] - v1[2] * v2[1])
                - v0[1] * (v1[0] * v2[2] - v1[2] * v2[0])
                + v0[2] * (v1[0] * v2[1] - v1[1] * v2[0])
            ) / 6.0

            vol_total += vol
            com_x += vol * (v0[0] + v1[0] + v2[0]) / 4.0
            com_y += vol * (v0[1] + v1[1] + v2[1]) / 4.0
            com_z += vol * (v0[2] + v1[2] + v2[2]) / 4.0

    if abs(vol_total) > 1e-10:
        com_x /= vol_total
        com_y /= vol_total
        com_z /= vol_total

    return com_x, com_y, com_z, abs(vol_total)


def equilibrium_angle_from_com(
    com_x: float,
    com_y: float,
    pivot_x: float,
    pivot_y: float,
) -> float:
    """Compute equilibrium tilt angle (degrees) from COM and pivot position.

    At equilibrium, the COM hangs directly below the pivot.  The angle
    the body must rotate to reach this state is:

        angle = atan2(com_x - pivot_x, pivot_y - com_y)

    where (com_x, com_y) and (pivot_x, pivot_y) are in the body's
    unrotated local frame.  Positive angle = clockwise tilt (COM right
    of pivot).

    Requires pivot_y > com_y (pivot above COM) for stable equilibrium.
    """
    dx = com_x - pivot_x
    dy = pivot_y - com_y
    if dy <= 0:
        # Unstable: COM above or at pivot
        return 0.0
    return math.degrees(math.atan2(dx, dy))
