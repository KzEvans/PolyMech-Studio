"""Plot templates, PlotSpec resolution (inline data for preview), static export, saved configs."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from polymech_api.deps import get_state
from polymech_api.serialization import lttb, to_jsonable
from polymech_api.services.analysis import run_curves
from polymech_api.services.plot_data import stored_series
from polymech_api.state import AppState
from polymech_database.models import AnalysisRun, Material, MechanicalProperty, PlotConfiguration
from polymech_database.repository import get
from polymech_mechanics.errors import InvalidInputError
from polymech_plotting.render import render, to_display
from polymech_plotting.spec import PlotSpec, SeriesSource
from polymech_plotting.templates import TEMPLATES, make_spec

router = APIRouter(prefix="/api", tags=["plots"])
State = Annotated[AppState, Depends(get_state)]


@router.get("/plot-templates")
def templates() -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "version": t.version,
            "x": t.x.model_dump(),
            "y": t.y.model_dump(),
            "y2": t.y2.model_dump() if t.y2 else None,
            "x_key": t.x_key,
            "y_key": t.y_key,
            "y2_key": t.y2_key,
            "x_property": t.x_property,
            "y_property": t.y_property,
            "origin_template": t.origin_template,
            "description": t.description,
        }
        for t in TEMPLATES.values()
    ]


class SpecFromRuns(BaseModel):
    template_id: str
    runs: list[tuple[int, str]] = Field(min_length=1)  # (run_id, series name)
    title: str = ""


@router.post("/plots/spec")
def spec_from_runs(body: SpecFromRuns) -> dict[str, Any]:
    t = TEMPLATES.get(body.template_id)
    if t is None:
        raise InvalidInputError(f"未知模板 {body.template_id}")
    if t.x_key is None or t.y_key is None:
        raise InvalidInputError("该模板用于材料性能对比，请使用材料数据库生成数据")
    series = [
        (name, SeriesSource(run_id=rid, x_key=t.x_key, y_key=t.y_key)) for rid, name in body.runs
    ]
    y2 = (
        [
            (f"{name} (右轴)", SeriesSource(run_id=rid, x_key=t.x_key, y_key=t.y2_key))
            for rid, name in body.runs
        ]
        if t.y2_key
        else []
    )
    return make_spec(t.id, series, body.title, y2).model_dump()


class PropertySpecIn(BaseModel):
    template_id: str
    material_ids: list[int] | None = None  # None → every material with both quantities


@router.post("/plots/property-spec")
def property_spec(state: State, body: PropertySpecIn) -> dict[str, Any]:
    """Material comparison scatter (SPEC §7.4): one series per material, values from stored
    properties (analysis or literature). Every (x, y) pair of the same material is drawn —
    nothing is averaged or picked; bounds-only values cannot be placed and are listed."""
    t = TEMPLATES.get(body.template_id)
    if t is None or not t.x_property or not t.y_property:
        raise InvalidInputError("该模板不是材料性能对比模板")
    with state.db.session() as s:
        stmt = select(Material).order_by(Material.name)
        if body.material_ids is not None:
            stmt = stmt.where(Material.id.in_(body.material_ids))
        series: list[tuple[str, SeriesSource]] = []
        omitted: list[str] = []
        notes: dict[str, str] = {}
        for m in s.scalars(stmt):
            props = s.scalars(
                select(MechanicalProperty).where(MechanicalProperty.material_id == m.id)
            ).all()
            xs = [p for p in props if p.quantity == t.x_property]
            ys = [p for p in props if p.quantity == t.y_property]
            if not xs or not ys:
                continue
            pts = [
                (px, py) for px in xs for py in ys if px.value is not None and py.value is not None
            ]
            bounds = [p for p in xs + ys if p.value is None]
            if bounds:
                omitted.append(f"{m.name}：{len(bounds)} 条只有上/下界的数值未绘出")
            if not pts:
                continue
            err = [py.uncertainty for _, py in pts]
            series.append(
                (
                    m.name,
                    SeriesSource(
                        x=[float(px.value) for px, _ in pts],  # type: ignore[arg-type]
                        y=[float(py.value) for _, py in pts],  # type: ignore[arg-type]
                        y_err=[float(e) if e is not None else 0.0 for e in err]
                        if any(e is not None for e in err)
                        else None,
                    ),
                )
            )
            if len(pts) > 1:
                notes[m.name] = f"同一材料有 {len(pts)} 组数值，全部绘出"
    if not series:
        raise InvalidInputError("没有同时具有这两项性能的材料")
    spec = make_spec(t.id, series)
    for sp in spec.panels[0].series:
        sp.note = notes.get(sp.name, "")
    return {
        "spec": spec.model_dump(),
        "omitted": omitted,
        "caution": "图中数值来自不同来源与测试条件，直接比较前请使用“可比性检查”",
    }


class DataIn(BaseModel):
    spec: PlotSpec


@router.post("/plots/data.csv")
def plot_data(state: State, body: DataIn) -> Response:
    """Every plotted point at full resolution, in the axes' display units (long format)."""
    res = resolver(state, None)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"# PolyMech Studio plot data, template {body.spec.template_id}"])
    w.writerow(["panel", "series", "x", "x_unit", "y", "y_unit", "y_err"])
    for k, panel in enumerate(body.spec.panels):
        for s in panel.series:
            x, y, err = res(s.source)
            yax = panel.y2 if s.y_axis == "y2" and panel.y2 else panel.y
            xd, yd = to_display(x, panel.x), to_display(y, yax)
            ed = err * yax.factor_offset[0] if err is not None else None
            for i in range(len(xd)):
                w.writerow(
                    [
                        f"({chr(ord('a') + k)})",
                        s.name,
                        repr(float(xd[i])),
                        panel.x.unit,
                        repr(float(yd[i])),
                        yax.unit,
                        "" if ed is None else repr(float(ed[i])),
                    ]
                )
    return Response(
        buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="plot_data.csv"'},
    )


def resolver(state: AppState, max_points: int | None) -> Any:
    cache: dict[int, dict[str, np.ndarray]] = {}

    def resolve(src: SeriesSource) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        if src.x is not None and src.y is not None:
            err = np.asarray(src.y_err, dtype=float) if src.y_err is not None else None
            return np.asarray(src.x, dtype=float), np.asarray(src.y, dtype=float), err
        assert src.run_id is not None and src.x_key and src.y_key
        if src.run_id not in cache:
            with state.db.session() as s:
                cache[src.run_id] = run_curves(state.data_dir, get(s, AnalysisRun, src.run_id))
        x, y, err = stored_series(src, cache[src.run_id])
        if max_points and len(x) > max_points:
            idx = lttb(x, y, max_points)
            x, y = x[idx], y[idx]
            err = err[idx] if err is not None else None
        return x, y, err

    return resolve


@router.post("/plots/resolve")
def resolve_spec(state: State, spec: PlotSpec, max_points: int = 2000) -> dict[str, Any]:
    """Return the spec with every series' data inline (downsampled for the interactive preview)."""
    res = resolver(state, max_points)
    out = spec.model_copy(deep=True)
    for panel in out.panels:
        for s in panel.series:
            x, y, err = res(s.source)
            s.source = SeriesSource(
                x=to_jsonable(x),
                y=to_jsonable(y),
                y_err=to_jsonable(err) if err is not None else None,
            )
    return out.model_dump()


class ExportIn(BaseModel):
    spec: PlotSpec
    format: Literal["png", "svg", "pdf"] = "png"
    filename: str = "figure"


@router.post("/plots/export")
def export(state: State, body: ExportIn) -> Response:
    """Static export always uses the full-resolution data (no preview downsampling)."""
    data = render(body.spec, body.format, resolver(state, None))
    media = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[body.format]
    safe = "".join(c for c in body.filename if c.isalnum() or c in "-_.") or "figure"
    # HTTP headers are latin-1: Chinese names go in filename* (RFC 6266), ASCII in filename
    ascii_name = "".join(c for c in safe if c.isascii()) or "figure"
    return Response(
        data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}.{body.format}"; '
            f"filename*=UTF-8''{quote(safe)}.{body.format}"
        },
    )


class ConfigIn(BaseModel):
    name: str
    spec: PlotSpec
    analysis_run_id: int | None = None
    kind: Literal["config", "template"] = "config"


@router.get("/plot-configs")
def list_configs(
    state: State, kind: Literal["config", "template"] = "config"
) -> list[dict[str, Any]]:
    with state.db.session() as s:
        return [
            {
                "id": c.id,
                "name": c.name,
                "kind": c.kind,
                "template_id": c.template_id,
                "n_panels": len(c.spec.get("panels", [])),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in s.scalars(
                select(PlotConfiguration)
                .where(PlotConfiguration.kind == kind)
                .order_by(PlotConfiguration.updated_at.desc())
            )
        ]


@router.post("/plot-configs")
def save_config(state: State, body: ConfigIn) -> dict[str, Any]:
    with state.db.session() as s:
        c = PlotConfiguration(
            name=body.name,
            kind=body.kind,
            template_id=body.spec.template_id,
            template_version=body.spec.template_version,
            analysis_run_id=body.analysis_run_id,
            spec=body.spec.model_dump(),
        )
        s.add(c)
        s.flush()
        return {"id": c.id, "name": c.name}


@router.put("/plot-configs/{config_id}")
def update_config(state: State, config_id: int, body: ConfigIn) -> dict[str, Any]:
    with state.db.session() as s:
        c = get(s, PlotConfiguration, config_id)
        c.name, c.spec, c.updated_at = body.name, body.spec.model_dump(), datetime.now(UTC)
        return {"id": c.id, "name": c.name}


@router.get("/plot-configs/{config_id}")
def load_config(state: State, config_id: int) -> dict[str, Any]:
    with state.db.session() as s:
        c = get(s, PlotConfiguration, config_id)
        return {
            "id": c.id,
            "name": c.name,
            "kind": c.kind,
            "spec": PlotSpec.model_validate(c.spec).model_dump(),
        }


@router.delete("/plot-configs/{config_id}")
def delete_config(state: State, config_id: int) -> dict[str, Any]:
    """Saved figures/templates are user settings, not data: deleting one is allowed."""
    with state.db.session() as s:
        s.delete(get(s, PlotConfiguration, config_id))
        return {"deleted": config_id}
