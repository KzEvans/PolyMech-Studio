"""Secrets live in the macOS Keychain, Windows Credential Manager or environment variables —
never in the database, settings file, logs or API responses (SPEC §2.1 AI, §6.8)."""

from __future__ import annotations

import os
import subprocess
import sys

SERVICE = "PolyMechStudio"
ENV = {
    "bridge_token": "POLYMECH_BRIDGE_TOKEN",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}


def _keychain_available() -> bool:
    return sys.platform == "darwin" and os.environ.get("POLYMECH_NO_KEYCHAIN") != "1"


def get_secret(name: str) -> str | None:
    if v := os.environ.get(ENV.get(name, ""), ""):
        return v
    if sys.platform == "win32" and os.environ.get("POLYMECH_NO_KEYCHAIN") != "1":
        from polymech_api.native_windows import get_credential

        return get_credential(name)
    if not _keychain_available():
        return None
    r = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout.strip() or None if r.returncode == 0 else None


def set_secret(name: str, value: str) -> None:
    if sys.platform == "win32" and os.environ.get("POLYMECH_NO_KEYCHAIN") != "1":
        from polymech_api.native_windows import set_credential

        set_credential(name, value)
        return
    if not _keychain_available():
        raise RuntimeError(
            "当前环境无法使用系统凭据存储，请通过环境变量 " + ENV.get(name, name) + " 提供"
        )
    # -U updates an existing item; the value is passed as an argument to `security` only
    subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-U", "-s", SERVICE, "-a", name, "-w", value],
        capture_output=True,
        check=True,
    )


def has_secret(name: str) -> bool:
    return get_secret(name) is not None
