"""Desktop mode: the built UI is served next to the API; tool PATH for Finder-launched apps."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polymech_api import desktop
from polymech_api.main import create_app
from polymech_api.settings import Settings


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POLYMECH_NO_KEYCHAIN", "1")
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (web / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"), static_dir=web)) as c:
        yield c


def test_ui_routes_assets_and_api_precedence(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    for route in ("/", "/analysis/12", "/plots"):
        r = client.get(route)
        assert r.status_code == 200 and "id=root" in r.text, route
    assert client.get("/assets/app.js").text == "console.log(1)"
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404 and "id=root" not in missing.text
    assert (
        "outside" not in client.get("/%2e%2e/secret.txt").text
    )  # never serves outside the UI root


def test_missing_ui_build_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_app(Settings(data_dir=tmp_path / "d"), static_dir=tmp_path / "nope")


def test_login_path_keeps_system_and_tool_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("SHELL", "/nonexistent/shell")  # login shell unavailable → still works
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(desktop.os.path, "expanduser", lambda p: p.replace("~", "/Users/SYNTHETIC"))
    parts = desktop.login_path(timeout_s=1).split(":")
    assert parts[:2] == ["/usr/bin", "/bin"]
    assert "/opt/homebrew/bin" in parts and "/usr/local/bin" in parts
    assert len(parts) == len(set(parts))


@pytest.mark.skipif(sys.platform == "win32", reason="macOS login-shell environment")
def test_login_shell_env_carries_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apps started from Finder lack the shell's proxy variables; they are read from the login
    shell so AI CLIs can reach their cloud services."""
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")
    env = desktop.login_shell_env(timeout_s=5)
    assert env.get("https_proxy") == "http://127.0.0.1:7890"
    assert "PATH" in env
