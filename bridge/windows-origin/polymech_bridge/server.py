"""Bridge HTTP API (SPEC §6.4). Token-authenticated, size-limited, job-directory isolated."""

from __future__ import annotations

import hmac
import logging
import shutil
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from polymech_bridge import __version__
from polymech_bridge import templates as tpl
from polymech_bridge.schema import PlotJob
from polymech_bridge.worker import OriginWorker

log = logging.getLogger("polymech_bridge")
MAX_BODY_BYTES = 64 * 1024 * 1024
RETENTION_S = 7 * 24 * 3600


def cleanup_old_jobs(work_root: Path, retention_s: float = RETENTION_S) -> int:
    """Delete job directories older than the retention period — only inside work_root."""
    n = 0
    now = time.time()
    for d in work_root.iterdir() if work_root.exists() else []:
        if d.is_dir() and d.parent == work_root and now - d.stat().st_mtime > retention_s:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def create_app(token: str, work_root: Path, worker: OriginWorker | None = None) -> FastAPI:
    work_root.mkdir(parents=True, exist_ok=True)
    w = worker or OriginWorker(work_root)
    shutdown_event = threading.Event()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        removed = cleanup_old_jobs(work_root)
        if removed:
            log.info("removed %d expired job directories", removed)
        if not w.is_alive():
            w.start()
        yield
        w.stop()
        w.join(timeout=60)

    app = FastAPI(title="PolyMech Origin Bridge", version=__version__, lifespan=lifespan)
    app.state.worker = w
    app.state.shutdown_event = shutdown_event

    @app.middleware("http")
    async def limit_body(request: Request, call_next: Any) -> Any:
        length = request.headers.get("content-length")
        if length is not None and int(length) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "请求体超过 64 MB 上限"})
        return await call_next(request)

    def auth(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(
            authorization.encode(), expected.encode()
        ):
            raise HTTPException(status_code=401, detail="缺少或错误的 Bridge 认证 Token")

    require_token = Depends(auth)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "polymech-origin-bridge", "version": __version__}

    @app.get("/v1/capabilities", dependencies=[require_token])
    def capabilities() -> dict[str, Any]:
        import platform
        import struct
        import sys

        try:
            import originpro  # noqa: F401

            originpro_ok = True
        except Exception as e:  # report, don't hide
            originpro_ok = False
            log.warning("originpro import failed: %s", e)
        return {
            "bridge_version": __version__,
            "python": sys.version.split()[0],
            "python_bits": struct.calcsize("P") * 8,
            "machine": platform.machine(),
            "originpro_importable": originpro_ok,
            "origin": w.origin_info,  # filled once a job has started Origin
            "exports": ["png", "pdf", "svg"],
            "templates": [t["id"] for t in tpl.available() if t["available"]],
            "queue_length": w.q.qsize(),
        }

    @app.get("/v1/templates", dependencies=[require_token])
    def templates() -> list[dict[str, Any]]:
        return tpl.available()

    @app.post("/v1/plot-jobs", dependencies=[require_token])
    def submit(job: PlotJob) -> dict[str, Any]:
        return w.submit(job).public()

    @app.get("/v1/plot-jobs/{job_id}", dependencies=[require_token])
    def status(job_id: str) -> dict[str, Any]:
        st = w.get(job_id)
        if st is None:
            raise HTTPException(404, "任务不存在")
        return st.public()

    @app.get("/v1/plot-jobs/{job_id}/artifacts", dependencies=[require_token])
    def artifacts(job_id: str) -> list[dict[str, Any]]:
        st = w.get(job_id)
        if st is None:
            raise HTTPException(404, "任务不存在")
        return [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(st.dir.iterdir())
            if p.is_file()
        ]

    @app.get("/v1/plot-jobs/{job_id}/artifacts/{name}", dependencies=[require_token])
    def artifact(job_id: str, name: str) -> FileResponse:
        st = w.get(job_id)
        if st is None:
            raise HTTPException(404, "任务不存在")
        allowed = {p.name: p for p in st.dir.iterdir() if p.is_file()}
        if name not in allowed:  # whitelist: only files that exist in this job's directory
            raise HTTPException(404, "文件不存在")
        return FileResponse(allowed[name], filename=name)

    @app.post("/v1/plot-jobs/{job_id}/cancel", dependencies=[require_token])
    def cancel(job_id: str) -> dict[str, Any]:
        st = w.cancel(job_id)
        if st is None:
            raise HTTPException(404, "任务不存在")
        return st.public()

    @app.post("/v1/shutdown", dependencies=[require_token])
    def shutdown() -> dict[str, str]:
        shutdown_event.set()
        return {"status": "shutting down"}

    return app
