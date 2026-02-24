"""mobile.config — Global configuration for mobile generation."""

from dataclasses import dataclass


@dataclass
class MobileConfig:
    density: float = 1.0  # g/mm³
    leaf_thickness: float = 2.0  # mm
    arc_bar_width: float = 2.0  # mm (cross-section)
    arc_bar_height: float = 2.0  # mm (cross-section)
    hole_diameter: float = 0.8  # mm (fishing line)
    hole_tip_inset: float = 2.0  # mm inward from arc tip for child holes
    font: str = "Cormorant Garamond"
    font_path: str | None = None  # path to .ttf/.otf file (overrides font name)
    font_size: float = 14.0  # mm
    # How to interpret Node/Level rotation hints:
    # - "equilibrium": ignore hints; solve pivot so the arc hangs level (0°)
    # - "hint": solve pivot so the arc's equilibrium tilt matches the hint angle
    # - "blend": partially apply the hint by scaling it (see blend_ratio)
    angle_strategy: str = "blend"  # "equilibrium" | "hint" | "blend"
    blend_ratio: float = 0.7  # weight toward equilibrium (higher => closer to 0°)
    stl_tolerance: float = 1e-4  # mm, linear deflection for STL mesh
    stl_angular_tolerance: float = 0.01  # radians (~0.6°), angular deflection

    # Pivot solver (COM-based binary search)
    sim_angle_tolerance_deg: float = 0.1
    sim_max_bisect_iterations: int = 20
    sim_stl_tolerance: float = 0.05  # low-res for intermediate STLs
    sim_stl_angular_tolerance: float = 0.5  # radians, low-res
