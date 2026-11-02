"""FastAPI application: `uvicorn polymech_api.main:app` (data dir from POLYMECH_DATA_DIR)."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import update

from polymech_api import __version__
from polymech_api.routers import (
    ai,
    analyses,
    experiments,
    imports,
    materials,
    origin,
    plots,
    settings,
)
from polymech_api.services.ai import AIDisabledError
from polymech_api.services.origin import OriginUnavailableError
from polymech_api.settings import Settings
from polymech_api.state import AppState
from polymech_database.db import Database
from polymech_database.errors import DatabaseError, NotFoundError
from polymech_database.literature import LiteratureImportError
from polymech_database.models import OriginJob
from polymech_dataio.errors import DataIOError
from polymech_mechanics.errors import MechanicsError

log = logging.getLogger("polymech")


def create_app(settings_: Settings | None = None, static_dir: Path | None = None) -> FastAPI:
    """static_dir: the built web UI (desktop app); served after all /api routes."""
    cfg = settings_ or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(cfg.data_dir)
        state = AppState(db=db, settings_path=cfg.data_dir / "settings.json")
        if sys.platform == "win32":
            from polymech_api.services.local_origin import LocalOriginManager

            state.local_origin = LocalOriginManager(
                Path(os.environ.get("POLYMECH_LOCAL_BRIDGE_EXE", "polymech-bridge.exe"))
            )
            # Local Bridge jobs belong to the previous application process and cannot resume.
            with db.session() as session:
                session.execute(
                    update(OriginJob)
                    .where(OriginJob.status.in_(("queued", "running")))
                    .values(
                        status="failed",
                        error="上次应用退出中断了本机 Origin 导出，请重新导出。",
                        finished_at=datetime.now(UTC),
                    )
                )
        app.state.polymech = state
        try:
            yield
        finally:
            if state.local_origin:
                state.local_origin.close()
            db.dispose()

    app = FastAPI(title="PolyMech Studio API", version=__version__, lifespan=lifespan)

    def problem(status: int, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status, content={"detail": str(exc), "code": type(exc).__name__}
        )

    @app.exception_handler(MechanicsError)
    async def _mech(_: Request, exc: MechanicsError) -> JSONResponse:
        return problem(422, exc)

    @app.exception_handler(DataIOError)
    async def _io(_: Request, exc: DataIOError) -> JSONResponse:
        return problem(422, exc)

    @app.exception_handler(LiteratureImportError)
    async def _lit(_: Request, exc: LiteratureImportError) -> JSONResponse:
        return problem(422, exc)

    @app.exception_handler(NotFoundError)
    async def _nf(_: Request, exc: NotFoundError) -> JSONResponse:
        return problem(404, exc)

    @app.exception_handler(DatabaseError)
    async def _db(_: Request, exc: DatabaseError) -> JSONResponse:
        log.exception("database error")
        return problem(500, exc)

    @app.exception_handler(OriginUnavailableError)
    async def _origin(_: Request, exc: OriginUnavailableError) -> JSONResponse:
        return problem(503, exc)

    @app.exception_handler(AIDisabledError)
    async def _ai_off(_: Request, exc: AIDisabledError) -> JSONResponse:
        return problem(409, exc)

    @app.exception_handler(ValueError)
    async def _val(_: Request, exc: ValueError) -> JSONResponse:
        return problem(422, exc)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    for r in (imports, experiments, analyses, plots, materials, settings, origin, ai):
        app.include_router(r.router)
    if static_dir is not None:
        _serve_ui(app, static_dir.resolve())
    return app


def _serve_ui(app: FastAPI, root: Path) -> None:
    index = root / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"界面文件缺失：{index}")

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        f = (root / path).resolve()
        # client-side routes (/analysis/12) fall back to index.html; never serve outside root
        if path and f.is_file() and f.is_relative_to(root):
            return FileResponse(f)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
