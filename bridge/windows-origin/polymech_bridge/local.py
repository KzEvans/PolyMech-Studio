"""Desktop-only entry point. No persistent token, remote bind, or old Bridge files."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading

import uvicorn

from polymech_api.native_windows import wait_for_process_exit
from polymech_bridge.server import create_app


def main() -> None:
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()
    token = os.environ.pop("POLYMECH_LOCAL_TOKEN")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    app = create_app(token, args.work_root)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))

    def parent_watch() -> None:
        wait_for_process_exit(args.parent_pid)
        app.state.shutdown_event.set()

    def shutdown_watch() -> None:
        app.state.shutdown_event.wait()
        server.should_exit = True
        # COM may be blocked. Only this worker's verified automation PIDs may be killed.
        if not finished.wait(45):
            app.state.worker.terminate_owned()

    finished = threading.Event()
    threading.Thread(target=parent_watch, daemon=True).start()
    threading.Thread(target=shutdown_watch, daemon=True).start()

    # Readiness is emitted after ASGI startup, not merely after binding the port.
    def ready() -> None:
        while not server.started and not finished.wait(0.05):
            pass
        if server.started:
            print(f"POLYMECH_BRIDGE_PORT={sock.getsockname()[1]}", flush=True)

    threading.Thread(target=ready, daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        finished.set()
        sock.close()


if __name__ == "__main__":
    main()
