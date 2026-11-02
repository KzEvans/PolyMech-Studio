"""Structured quality / applicability flags attached to every analysis result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class Flag:
    """A machine-readable code plus a Chinese message for the UI and reports."""

    code: str
    severity: Severity
    message: str


def info(code: str, message: str) -> Flag:
    return Flag(code, "info", message)


def warning(code: str, message: str) -> Flag:
    return Flag(code, "warning", message)
