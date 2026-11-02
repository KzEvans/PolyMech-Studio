"""Runtime settings, read from environment variables (never hard-coded user paths)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from polymech_api.paths import data_dir


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("POLYMECH_DATA_DIR")
        return cls(data_dir=Path(raw).expanduser().resolve() if raw else data_dir())
