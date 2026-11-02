"""Operating-system boundaries, including paths and proxy isolation."""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from polymech_api import desktop, paths, secrets_store
from polymech_api.services.origin import default_client
from polymech_api.settings import Settings


def test_windows_folders_use_roaming_data_and_local_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "漫游 数据"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "本地 缓存"))
    monkeypatch.delenv("POLYMECH_DATA_DIR", raising=False)
    assert Settings.from_env().data_dir == tmp_path / "漫游 数据" / "PolyMechStudio"
    assert paths.cache_dir() == tmp_path / "本地 缓存" / "PolyMechStudio"
    monkeypatch.setenv("POLYMECH_DATA_DIR", str(tmp_path / "独立验收"))
    assert Settings.from_env().data_dir == tmp_path / "独立验收"


def test_macos_folders_are_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.data_dir() == tmp_path / "Library/Application Support/PolyMechStudio"
    assert paths.cache_dir() == tmp_path / "Library/Caches/PolyMechStudio"


def test_windows_environment_keeps_semicolon_paths_and_explicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("PATH", r"C:\工具;C:\Windows\System32;C:\工具")
    monkeypatch.setenv("HTTPS_PROXY", "http://explicit.invalid:7890")
    monkeypatch.setattr(
        desktop,
        "getproxies",
        lambda: {"https": "http://system.invalid:7890", "http": "http://system.invalid:7890"},
    )
    shell = desktop.login_shell_env()
    assert shell["PATH"] == r"C:\工具;C:\Windows\System32;C:\工具"
    assert desktop.login_path(shell_env=shell) == r"C:\工具;C:\Windows\System32"
    env = desktop.network_env({"HTTPS_PROXY": shell["HTTPS_PROXY"]})
    assert env == {
        "HTTPS_PROXY": "http://explicit.invalid:7890",
        "http_proxy": "http://system.invalid:7890",
    }


def test_environment_secret_precedes_windows_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-environment-key")
    assert secrets_store.get_secret("anthropic_api_key") == "synthetic-environment-key"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("POLYMECH_NO_KEYCHAIN", "1")
    assert secrets_store.get_secret("anthropic_api_key") is None


def test_bridge_connection_bypasses_user_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    class Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"bridge-direct")

        def log_message(self, format: str, *args: object) -> None:
            pass

    for key in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    for key in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(key, "")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with default_client(f"http://127.0.0.1:{server.server_port}", 2) as client:
            assert client.get("/health").text == "bridge-direct"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
