"""mobile.arc_math — Pure math helpers for sagitta arcs and pivot solving.

This module is intentionally build123d-free so it can be used by both:
- `mobile.resolve` (physics / layout decisions)
- `mobile.generate` (geometry generation)
"""

from __future__ import annotations

import math


def _circle_radius_from_sagitta(chord: float, sagitta: float) -> float:
    """Radius of a circle from chord length and sagitta (rise)."""
    # R = chord²/(8·s) + s/2
    return (chord**2) / (8.0 * sagitta) + sagitta / 2.0


def arc_y_at_x(arc_w: float, arc_h: float, pivot_mm: float, x: float) -> float:
    """Compute Y coordinate on the sagitta arc at local X.

    Coordinates match `mobile.generate` conventions:
    - local origin is at the pivot projection on the chord line (x=0 on chord)
    - arc endpoints are at:
        left  = (-pivot_mm, 0)
        right = (arc_w - pivot_mm, 0)
    - sagitta (arc_h) is the maximum rise above the chord.
    """
    if arc_h == 0:
        return 0.0

    left_x = -pivot_mm
    right_x = arc_w - pivot_mm
    chord = right_x - left_x  # == arc_w
    mid_x = (left_x + right_x) / 2.0

    R = _circle_radius_from_sagitta(chord, arc_h)
    center_y = arc_h - R

    dx = x - mid_x
    disc = R * R - dx * dx
    if disc <= 0:
        return 0.0
    return center_y + math.sqrt(disc)


def pivot_y(arc_w: float, arc_h: float, pivot_mm: float) -> float:
    """Y coordinate of the pivot point on the arc (x=0)."""
    return arc_y_at_x(arc_w, arc_h, pivot_mm, 0.0)


def equilibrium_angle_deg(
    arc_w: float,
    arc_h: float,
    pivot_mm: float,
    weight_left: float,
    weight_right: float,
) -> float:
    """Equilibrium tilt angle (degrees) for a given pivot location.

    Model:
    - two point weights at arc endpoints
    - pivot point is on the arc at x=0 (not on the chord), giving a vertical
      offset that makes the angle statically determined.

    Derived relation:
      tan(theta) = (pivot_mm - base_mm) / pivot_y
      where base_mm = arc_w * weight_right / (weight_left + weight_right)
    """
    total = weight_left + weight_right
    if total == 0:
        return 0.0

    y = pivot_y(arc_w, arc_h, pivot_mm)
    if y == 0:
        return 0.0

    base = arc_w * (weight_right / total)
    return math.degrees(math.atan2(pivot_mm - base, y))


def solve_pivot_mm_for_angle(
    *,
    arc_w: float,
    arc_h: float,
    weight_left: float,
    weight_right: float,
    target_angle_deg: float,
    min_tip_span_mm: float,
    max_iter: int = 80,
) -> float:
    """Solve pivot_mm such that the equilibrium angle equals target_angle_deg.

    Returns pivot_mm (offset from left endpoint), constrained to:
      [min_tip_span_mm, arc_w - min_tip_span_mm]

    Raises ValueError if the target is impossible within constraints.
    """
    if arc_w <= 0:
        raise ValueError("arc_w must be > 0")

    p_min = float(min_tip_span_mm)
    p_max = float(arc_w - min_tip_span_mm)
    if p_min >= p_max:
        raise ValueError(
            f"Arc too small for tip span constraint: arc_w={arc_w}, "
            f"min_tip_span_mm={min_tip_span_mm}"
        )

    total = weight_left + weight_right
    if total == 0:
        return arc_w / 2.0

    base = arc_w * (weight_right / total)

    if arc_h == 0:
        if abs(target_angle_deg) < 1e-9:
            return min(max(base, p_min), p_max)
        raise ValueError("Cannot enforce a non-zero angle when arc_h == 0")

    tan_t = math.tan(math.radians(target_angle_deg))

    def f(p: float) -> float:
        return p - base - pivot_y(arc_w, arc_h, p) * tan_t

    samples = 200
    xs = [p_min + (p_max - p_min) * (i / samples) for i in range(samples + 1)]
    fs = [f(x) for x in xs]

    brackets: list[tuple[float, float]] = []
    for i in range(samples):
        a, b = xs[i], xs[i + 1]
        fa, fb = fs[i], fs[i + 1]
        if fa == 0:
            return a
        if fa * fb < 0:
            brackets.append((a, b))

    if not brackets:
        ang_min = equilibrium_angle_deg(arc_w, arc_h, p_min, weight_left, weight_right)
        ang_max = equilibrium_angle_deg(arc_w, arc_h, p_max, weight_left, weight_right)
        lo = min(ang_min, ang_max)
        hi = max(ang_min, ang_max)
        raise ValueError(
            f"Target angle {target_angle_deg:.3f}° is not achievable with "
            f"pivot constrained to [{p_min:.3f}, {p_max:.3f}]mm. "
            f"Achievable equilibrium angle is approximately [{lo:.3f}°, {hi:.3f}°]."
        )

    # Prefer the bracket closest to the unconstrained fixed-point estimate.
    est = base + pivot_y(arc_w, arc_h, min(max(base, p_min), p_max)) * tan_t
    best = min(brackets, key=lambda ab: min(abs(est - ab[0]), abs(est - ab[1])))
    a, b = best
    fa, fb = f(a), f(b)

    for _ in range(max_iter):
        m = (a + b) / 2.0
        fm = f(m)
        if abs(fm) < 1e-10:
            return m
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm

    return (a + b) / 2.0

