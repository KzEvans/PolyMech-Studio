"""Start the bridge:  pythonw -m polymech_bridge [--host IP] [--port 8766]

Binds to one address only (default: this VM's primary IPv4, i.e. the Parallels Shared
network adapter) — never 0.0.0.0. The token is generated on first start and stored in a
file only this Windows user can read; the Mac side reads it once during pairing.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import socket
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from polymech_bridge.server import create_app

ROOT = Path(os.environ.get("LOCALAPPDATA", ".")) / "PolyMechBridge"


def primary_ipv4() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # TEST-NET address: no packet is sent for UDP connect
        return str(s.getsockname()[0])
    finally:
        s.close()


def load_token(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    tok = secrets.token_urlsafe(32)
    path.write_text(tok, encoding="utf-8")
    return tok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None, help="bind address (default: primary IPv4)")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args()
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        ROOT / "logs" / "bridge.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = args.host or primary_ipv4()
    app = create_app(load_token(ROOT / "token.txt"), ROOT / "jobs")
    (ROOT / "bridge-endpoint.txt").write_text(f"http://{host}:{args.port}\n", encoding="utf-8")
    config = uvicorn.Config(app, host=host, port=args.port, log_config=None, access_log=False)
    server = uvicorn.Server(config)

    def watch() -> None:
        app.state.shutdown_event.wait()
        server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    logging.getLogger("polymech_bridge").info("listening on %s:%s", host, args.port)
    server.run()


if __name__ == "__main__":
    main()
