"""Application state: database and user settings (non-secret, JSON in the data directory)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polymech_api.services.local_origin import LocalOriginManager

from polymech_ai.providers import EFFORTS
from polymech_database.db import Database
from polymech_database.storage import atomic_write

DEFAULT_SETTINGS: dict[str, Any] = {
    "operator": "",
    "ai_enabled": True,
    "ai_provider": "codex",  # codex | claude | api
    "ai_api_kind": "anthropic",  # anthropic | openai_compatible
    "ai_api_base_url": "",
    "ai_model": "",
    "ai_effort": "",  # "" = provider default | low | medium | high | xhigh | max
    "ai_send_rows": 5,  # sample rows sent with headers for column mapping
    "bridge_url": "",
    "bridge_timeout_s": 30,
    "theme": "system",  # system | light | dark
    "reduce_transparency": False,
    "plot_font_size_pt": 20,
    "plot_width_mm": 272.288,
    "stress_display_unit": "MPa",
}


@dataclass
class AppState:
    db: Database
    settings_path: Path
    local_origin: LocalOriginManager | None = None

    @property
    def data_dir(self) -> Path:
        return self.db.data_dir

    def settings(self) -> dict[str, Any]:
        stored: dict[str, Any] = {}
        if self.settings_path.exists():
            stored = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return DEFAULT_SETTINGS | {k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"未知的设置项：{sorted(unknown)}")
        if patch.get("ai_effort", "") not in ("", *EFFORTS):
            raise ValueError(f"推理强度只能是默认或 {'/'.join(EFFORTS)}")
        merged = self.settings() | patch
        atomic_write(self.settings_path, json.dumps(merged, ensure_ascii=False, indent=1).encode())
        return merged
