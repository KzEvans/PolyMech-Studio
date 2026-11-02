"""Per-user folders shared by the API and frozen desktop backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    if sys.platform == "win32":
        return (
            Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
            / "PolyMechStudio"
        )
    return Path.home() / "Library" / "Application Support" / "PolyMechStudio"


def cache_dir() -> Path:
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "PolyMechStudio"
        )
    return Path.home() / "Library" / "Caches" / "PolyMechStudio"
