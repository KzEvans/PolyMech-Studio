"""Database-layer errors (user-facing Chinese messages)."""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class."""


class MigrationError(DatabaseError):
    """Schema migration failed; the pre-migration backup path is included in the message."""


class StorageError(DatabaseError):
    """Archive / curve file could not be written or read."""


class NotFoundError(DatabaseError):
    """Requested record does not exist."""
