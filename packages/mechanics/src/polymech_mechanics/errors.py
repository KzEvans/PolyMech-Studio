"""Exception hierarchy of the calculation engine.

Every error carries a Chinese user-facing message (shown in the UI) and is raised instead of
guessing a value: missing geometry, impossible units or unusable data stop the calculation.
"""

from __future__ import annotations


class MechanicsError(Exception):
    """Base class for all calculation-engine errors."""


class MissingGeometryError(MechanicsError):
    """A specimen dimension required by the requested quantity is missing or non-positive."""


class UnitDimensionError(MechanicsError):
    """A quantity has the wrong physical dimension (e.g. N/m where Pa is required)."""


class InsufficientDataError(MechanicsError):
    """Too few (valid) points for the requested operation."""


class InvalidInputError(MechanicsError):
    """Input arrays are malformed (length mismatch, NaN, out-of-range parameters...)."""


class CycleSegmentationError(MechanicsError):
    """Loading/unloading cycles could not be identified."""


class OutOfRangeError(MechanicsError):
    """A requested evaluation point lies outside the measured data (no extrapolation)."""
