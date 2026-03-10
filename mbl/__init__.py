"""mbl — grid-first DSL for hanging mobile generation."""

from mbl.config import MobileConfig
from mbl.dsl import (
    Arc, Cell, Leaf, Mobile, Space,
    Vector, Text, Svg, Txt, stencil_cut,
    Circle, Star, Burst, Heart, Shopify, Peace,
    Cup, Eclipse, Octopus, Smile, Sun,
)
from mbl.errors import (
    MobileArcError,
    MobileEmptyError,
    MobileError,
    MobilePivotError,
    MobileShapeError,
    MobileSimulationError,
    MobileWeightError,
)


def generate(*args, **kwargs):
    from mbl.generate import generate as _generate

    return _generate(*args, **kwargs)


def resolve(*args, **kwargs):
    from mbl.resolve import resolve as _resolve

    return _resolve(*args, **kwargs)


def simulate_mobile(*args, **kwargs):
    from mbl.simulate import simulate_mobile as _simulate_mobile

    return _simulate_mobile(*args, **kwargs)


__all__ = [
    "Arc",
    "Burst",
    "Cell",
    "Circle",
    "Cup",
    "Eclipse",
    "Heart",
    "Leaf",
    "Mobile",
    "MobileArcError",
    "MobileConfig",
    "MobileEmptyError",
    "MobileError",
    "MobilePivotError",
    "MobileShapeError",
    "MobileSimulationError",
    "MobileWeightError",
    "Octopus",
    "Peace",
    "Shopify",
    "Smile",
    "Space",
    "Star",
    "Sun",
    "Svg",
    "Text",
    "Txt",
    "Vector",
    "generate",
    "resolve",
    "simulate_mobile",
    "stencil_cut",
]
