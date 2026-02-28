"""mbl.errors — Exception hierarchy for the mobile DSL."""


class MobileError(Exception):
    """Base exception for all mobile errors."""


class MobileShapeError(MobileError):
    """Invalid row matrix shape (hole continuity mismatch, empty rows, etc.)."""


class MobileArcError(MobileError):
    """Invalid arc configuration."""


class MobileWeightError(MobileError):
    """Negative net volume (too many cutouts)."""


class MobilePivotError(MobileError):
    """Requested angle implies an impossible pivot location."""


class MobileSimulationError(MobileError):
    """COM-based pivot solver failed (missing STL or convergence failure)."""


class MobileEmptyError(MobileError):
    """Empty mobile (no levels)."""
