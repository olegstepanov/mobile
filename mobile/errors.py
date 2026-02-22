"""mobile.errors — Exception hierarchy for the mobile DSL."""


class MobileError(Exception):
    """Base exception for all mobile errors."""


class MobileShapeError(MobileError):
    """Holes in level N ≠ nodes in level N+1."""


class MobileArcError(MobileError):
    """Node without arc and no level default."""


class MobileWeightError(MobileError):
    """Negative net volume (too many cutouts)."""


class MobilePivotError(MobileError):
    """Requested angle implies an impossible pivot location."""


class MobileEmptyError(MobileError):
    """Empty mobile (no levels)."""
