"""One ephemeral, loopback-only Origin bridge owned by this backend (Windows)."""

from __future__ import annotations

import importlib
import os
import queue
import secrets
import subprocess
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx

from polymech_api.paths import cache_dir
from polymech_api.services.origin import BridgeClient, OriginUnavailableError


def detect_origin() -> dict[str, Any]:
    winreg = importlib.import_module("winreg")

    # Origin 2025b registers LocalServer32 in the 32-bit registry view even for x64 Origin.
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        for name in ("Origin.Application", "Origin.ApplicationSI"):
            try:
                access = winreg.KEY_READ | view
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + r"\CLSID", 0, access) as key:
                    clsid = winreg.QueryValueEx(key, None)[0]
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32", 0, access
                ) as key:
                    command = str(winreg.QueryValueEx(key, None)[0]).strip()
                executable = (
                    command.split('"')[1] if command.startswith('"') else command.split(" /", 1)[0]
                )
                executable = executable.removesuffix(" -Embedding").strip()
                if Path(executable).is_file():
                    return {"installed": True, "executable": executable}
            except OSError:
                continue
    return {
        "installed": False,
        "error": "未检测到已注册的本机 Origin，请安装 x64 Origin 并完成许可激活。",
    }


class LocalOriginManager:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self._client: BridgeClient | None = None

    def client(self) -> BridgeClient:
        with self.lock:
            if self.process is not None and self.process.poll() is None and self._client:
                return self._client
            detected = detect_origin()
            if not detected["installed"]:
                raise OriginUnavailableError(detected["error"])
            if not self.executable.is_file():
                raise OriginUnavailableError("本机 Origin 组件缺失，请重新安装 PolyMech Studio。")
            token = secrets.token_urlsafe(32)
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith("POLYMECH_")
                and key.upper()
                not in {
                    "ANTHROPIC_API_KEY",
                    "OPENAI_API_KEY",
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "ALL_PROXY",
                }
            }
            env["POLYMECH_LOCAL_TOKEN"] = token
            root = cache_dir() / "origin-bridge"
            root.mkdir(parents=True, exist_ok=True)
            log = root / "bridge.log"
            with log.open("a", encoding="utf-8") as stderr:
                proc = subprocess.Popen(
                    [
                        str(self.executable),
                        "--work-root",
                        str(root / "jobs"),
                        "--parent-pid",
                        str(os.getpid()),
                    ],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=stderr,
                    text=True,
                    encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            self.process = proc
            ready: queue.Queue[str] = queue.Queue()

            def read_port() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if line.startswith("POLYMECH_BRIDGE_PORT="):
                        ready.put(line.strip().split("=", 1)[1])
                ready.put("")

            threading.Thread(target=read_port, daemon=True).start()
            try:
                port = int(ready.get(timeout=45))
                if not 1 <= port <= 65535:
                    raise ValueError("invalid port")
            except (queue.Empty, ValueError) as exc:
                proc.terminate()
                proc.wait(timeout=10)
                raise OriginUnavailableError(f"本机 Origin 组件启动失败。诊断日志：{log}") from exc
            # Cold Origin startup took 76 s in the ARM VM while Rust compiled. The UI polls
            # the same job; a 30 s remote-Bridge timeout produces spurious connection errors.
            self._client = BridgeClient(
                f"http://127.0.0.1:{port}",
                token,
                timeout=120,
                local=True,
                factory=lambda url, timeout: httpx.Client(
                    base_url=url,
                    timeout=timeout,
                    trust_env=False,
                    limits=httpx.Limits(max_keepalive_connections=0),
                ),
            )
            return self._client

    def close(self) -> None:
        with self.lock:
            proc, client = self.process, self._client
            self.process, self._client = None, None
            if proc is None:
                return
            if proc.poll() is None:
                if client:
                    with suppress(Exception):
                        client.http.post(
                            "/v1/shutdown",
                            headers={"Authorization": f"Bearer {client.token}"},
                            timeout=5,
                        )
                try:
                    proc.wait(timeout=70)
                except subprocess.TimeoutExpired:
                    proc.terminate()  # only the bridge process this manager created
                    proc.wait(timeout=10)
            if client:
                client.http.close()
