"""Import-layer errors (messages are user-facing Chinese)."""

from __future__ import annotations


class DataIOError(Exception):
    """Base class for import errors."""


class FileFormatError(DataIOError):
    """The file cannot be read as a data table (corrupt, binary, no numeric block...)."""


class MappingError(DataIOError):
    """A column mapping is inconsistent (unknown quantity, wrong unit dimension, duplicates)."""
