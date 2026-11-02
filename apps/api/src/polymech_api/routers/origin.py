"""Origin connection status and jobs. Everything else in the app keeps working when the
VM or bridge is unavailable — these endpoints report that clearly instead."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from polymech_api.deps import get_state
from polymech_api.routers.plots import resolver as plots_resolver
from polymech_api.secrets_store import has_secret, set_secret
from polymech_api.services import origin as svc
from polymech_api.state import AppState
from polymech_database.models import AnalysisRun, Material, OriginJob
from polymech_database.repository import get
from polymech_mechanics.errors import InvalidInputError
from polymech_plotting.spec import PlotSpec

router = APIRouter(prefix="/api/origin", tags=["origin"])
State = Annotated[AppState, Depends(get_state)]


def client(request: Request, state: AppState) -> svc.BridgeClient:
    if state.local_origin is not None and not hasattr(request.app.state, "bridge_client_factory"):
        return state.local_origin.client()
    factory = getattr(request.app.state, "bridge_client_factory", svc.default_client)
    return svc.make_client(state.settings(), factory)


def job_json(j: OriginJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "analysis_run_id": j.analysis_run_id,
        "template_id": j.template_id,
        "status": j.status,
        "requested_at": j.requested_at.isoformat(),
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        "opju_file": Path(j.opju_path).name if j.opju_path else None,
        "png_file": Path(j.png_path).name if j.png_path else None,
        "error": j.error,
        "verification": j.verification,
    }


@router.get("/status")
def status(state: State, request: Request) -> dict[str, Any]:
    s = state.settings()
    out: dict[str, Any] = {
        "mode": "local" if state.local_origin else "remote",
        "vms": [] if state.local_origin else svc.vm_status(),
        "bridge_url": s.get("bridge_url", ""),
        "token_configured": has_secret("bridge_token"),
    }
    if state.local_origin:
        from polymech_api.services.local_origin import detect_origin

        out["local_origin"] = detect_origin()
        out["bridge_url"] = ""
        out["token_configured"] = False
    try:
        c = client(request, state)
        out["health"] = c.health()
        out["capabilities"] = c.capabilities()
        out["reachable"] = True
    except svc.OriginUnavailableError as e:
        out["reachable"] = False
        out["error"] = str(e)
    return out


Export = Literal["png", "pdf", "svg"]


def _default_exports() -> list[Export]:
    return ["png", "pdf"]


class PairIn(BaseModel):
    vm_name: str = "Windows 11"


@router.post("/pair")
def pair(state: State, body: PairIn) -> dict[str, Any]:
    """Read endpoint + token from the VM via prlctl, store the token in the Keychain."""
    if state.local_origin:
        raise InvalidInputError("Windows 版直接使用本机 Origin，无需虚拟机配对。")
    url, token = svc.pair_via_prlctl(body.vm_name)
    set_secret("bridge_token", token)
    state.update_settings({"bridge_url": url})
    return {"bridge_url": url, "token_configured": True}


class JobIn(BaseModel):
    run_id: int
    template_id: str
    exports: list[Export] = Field(default_factory=_default_exports)


@router.post("/jobs")
def submit(state: State, request: Request, body: JobIn) -> dict[str, Any]:
    with state.db.session() as s:
        run = get(s, AnalysisRun, body.run_id)
        material = s.get_one(Material, run.experiment.specimen.material_id)
        job = svc.build_job(
            state.data_dir, run, material.name, body.template_id, list(body.exports)
        )
    st = client(request, state).submit(job)
    with state.db.session() as s:
        row = OriginJob(
            analysis_run_id=body.run_id,
            template_id=body.template_id,
            bridge_job_id=st["id"],
            status=st["status"],
        )
        s.add(row)
        s.flush()
        return job_json(row)


class PlotJobIn(BaseModel):
    spec: PlotSpec
    name: str = Field(default="", max_length=200)
    exports: list[Export] = Field(default_factory=_default_exports)


@router.post("/plot-jobs")
def submit_plot(state: State, request: Request, body: PlotJobIn) -> dict[str, Any]:
    """Export the current Plot Studio figure as an editable Origin project."""
    run_ids = {s.source.run_id for p in body.spec.panels for s in p.series if s.source.run_id}
    with state.db.session() as s:
        labels = {
            r.id: f"{r.experiment.specimen.label} {r.method} v{r.version}"
            for r in s.scalars(select(AnalysisRun).where(AnalysisRun.id.in_(run_ids)))
        }
    job = svc.build_plot_job(
        body.spec, plots_resolver(state, None), body.name, list(body.exports), labels
    )
    st = client(request, state).submit(job)
    with state.db.session() as s:
        row = OriginJob(
            analysis_run_id=min(run_ids) if run_ids else None,
            template_id=job["graphs"][0]["template"],
            bridge_job_id=st["id"],
            status=st["status"],
        )
        s.add(row)
        s.flush()
        return job_json(row)


@router.get("/jobs")
def jobs(state: State) -> list[dict[str, Any]]:
    with state.db.session() as s:
        return [
            job_json(j)
            for j in s.scalars(select(OriginJob).order_by(OriginJob.id.desc()).limit(50))
        ]


@router.get("/jobs/{job_id}")
def job(state: State, request: Request, job_id: int) -> dict[str, Any]:
    with state.db.session() as s:
        j = get(s, OriginJob, job_id)
        if j.status in ("queued", "running"):
            svc.refresh_job(state.data_dir, j, client(request, state))
        out = job_json(j)
        folder = state.data_dir / "origin" / f"job{j.id}"
        out["files"] = sorted(p.name for p in folder.iterdir()) if folder.exists() else []
        return out


@router.get("/jobs/{job_id}/files/{name}")
def job_file(state: State, job_id: int, name: str) -> FileResponse:
    folder = state.data_dir / "origin" / f"job{job_id}"
    allowed = {p.name: p for p in folder.iterdir()} if folder.exists() else {}
    if name not in allowed:
        raise InvalidInputError("文件不存在")
    return FileResponse(allowed[name], filename=name)
