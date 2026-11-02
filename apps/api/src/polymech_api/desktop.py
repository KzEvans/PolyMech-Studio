"""Desktop entry point (the Tauri shell starts this as a child process).

    polymech-backend --static <web dist> [--data-dir DIR]

Binds 127.0.0.1 on a free port, prints `POLYMECH_PORT=<port>` once listening, serves the API
and the built web UI, and exits when the parent process (the app shell) goes away.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.request import getproxies

import uvicorn

from polymech_ai.providers import PROXY_VARS, set_network_env
from polymech_api.main import create_app
from polymech_api.settings import Settings

log = logging.getLogger("polymech.desktop")

# CLI tools the app calls (prlctl, codex, claude) live outside the minimal PATH that macOS
# gives to apps launched from Finder.
EXTRA_PATH = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "~/.local/bin",
    "~/.npm-global/bin",
    "~/.cargo/bin",
)


def login_shell_env(timeout_s: float = 5.0) -> dict[str, str]:
    """Environment of the user's login shell (empty if it cannot be read); never fails."""
    if sys.platform == "win32":
        return dict(os.environ)
    shell = os.environ.get("SHELL", "/bin/zsh")
    with contextlib.suppress(Exception):
        out = subprocess.run(
            [shell, "-ilc", 'printf "__ENV__"; env'],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        ).stdout
        if "__ENV__" in out:
            lines = out.rsplit("__ENV__", 1)[1].splitlines()
            return dict(line.split("=", 1) for line in lines if "=" in line)
    return {}


def login_path(timeout_s: float = 5.0, shell_env: dict[str, str] | None = None) -> str:
    """PATH as the user's login shell sets it, plus common tool folders; never fails."""
    env = login_shell_env(timeout_s) if shell_env is None else shell_env
    sep = ";" if sys.platform == "win32" else ":"
    parts = env.get("PATH", "").split(sep)
    parts += os.environ.get("PATH", "").split(sep)
    if sys.platform != "win32":
        parts += [os.path.expanduser(p) for p in EXTRA_PATH]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return sep.join(seen)


def network_env(shell_env: dict[str, str]) -> dict[str, str]:
    """AI proxies: explicit process settings take priority over Windows system proxies."""
    env = {k: v for k, v in shell_env.items() if k in PROXY_VARS and v}
    if sys.platform == "win32":
        for key, value in getproxies().items():
            name = "no_proxy" if key == "no" else f"{key}_proxy"
            if name in PROXY_VARS and name not in env and name.upper() not in env:
                env[name] = value
    return env


def watch_parent(interval_s: float = 1.0, on_exit: Callable[[], None] | None = None) -> None:
    """Exit when the owning shell disappears; Windows keeps its original parent PID."""
    parent = os.getppid()

    def run() -> None:
        if sys.platform == "win32":
            from polymech_api.native_windows import wait_for_process_exit

            try:
                wait_for_process_exit(parent)
            except OSError:
                log.exception("cannot watch parent process")
                os._exit(1)
        else:
            while os.getppid() == parent:
                time.sleep(interval_s)
        log.info("parent %s gone; exiting", parent)
        if on_exit is None:
            os._exit(0)
        else:
            on_exit()

    threading.Thread(target=run, daemon=True, name="parent-watch").start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="polymech-backend")
    ap.add_argument("--static", type=Path, required=True, help="built web UI (index.html)")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--port", type=int, default=0, help="0 = any free port")
    ap.add_argument("--no-parent-watch", action="store_true")
    ap.add_argument(
        "--control-stdin", action="store_true", help="owning desktop shell's shutdown pipe"
    )
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    shell_env = login_shell_env()
    os.environ["PATH"] = login_path(shell_env=shell_env)
    # proxy settings from the login shell for AI calls only (Codex/Claude reach cloud models
    # through them); the backend itself stays direct so the Origin Bridge on the LAN works
    proxies = network_env(shell_env)
    set_network_env(proxies)
    log.info(
        "AI network settings configured: %s",
        sorted(proxies) or "none",
    )
    settings = (
        Settings(data_dir=a.data_dir.expanduser().resolve()) if a.data_dir else Settings.from_env()
    )
    app = create_app(settings, static_dir=a.static)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", a.port))  # loopback only: never reachable from the network
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))

    def request_shutdown() -> None:
        server.should_exit = True

    if not a.no_parent_watch:
        watch_parent(on_exit=request_shutdown)
    if a.control_stdin:

        def control() -> None:
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    break
            request_shutdown()

        threading.Thread(target=control, daemon=True, name="shell-control").start()

    def announce() -> None:
        while not server.started:
            time.sleep(0.05)
        print(f"POLYMECH_PORT={port}", flush=True)
        log.info("serving %s on 127.0.0.1:%s, data %s", a.static, port, settings.data_dir)

    threading.Thread(target=announce, daemon=True).start()
    server.run(sockets=[sock])
    return 0


if __name__ == "__main__":
    sys.exit(main())
