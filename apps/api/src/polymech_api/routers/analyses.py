"""Run analyses (each run = a new immutable version), fetch, compare, export, statistics."""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from polymech_api.deps import get_state
from polymech_api.serialization import downsample_curves, to_jsonable
from polymech_api.services import analysis as svc
from polymech_api.services import deletion, report
from polymech_api.state import AppState
from polymech_database.models import AnalysisRun, Experiment, Material, Specimen
from polymech_database.repository import compare_runs, get
from polymech_mechanics.dma import TG_LABELS
from polymech_mechanics.errors import InvalidInputError
from polymech_mechanics.statistics import summarize

router = APIRouter(prefix="/api", tags=["analyses"])
State = Annotated[AppState, Depends(get_state)]

PREVIEW_KEYS = {
    "uniaxial": ("stretch", "nominal_stress_pa"),
    "cyclic": ("stretch", "nominal_stress_pa"),
    "pure_shear": ("stretch", "nominal_stress_pa"),
    "fatigue_steady": ("stretch", "nominal_stress_pa"),
    "crack_growth": ("crack_cycles", "crack_length_m"),
    "fatigue_threshold": ("g_j_m2", "dc_dn_m_per_cycle"),
    "dma": ("temperature_k", "storage_modulus_pa"),
}


def run_json(state: AppState, run: AnalysisRun, points: int = 2000) -> dict[str, Any]:
    curves = svc.run_curves(state.data_dir, run)
    x_key, y_key = PREVIEW_KEYS.get(run.method, (None, None))
    if run.method == "dma" and run.result.get("mode") == "frequency_sweep":
        x_key = "frequency_hz"
    if curves and x_key in curves and y_key in curves and len(curves[x_key]) > points:
        shown = downsample_curves(curves, x_key, y_key, points)
    else:
        shown = {k: to_jsonable(v) for k, v in curves.items()}
    return {
        "id": run.id,
        "experiment_id": run.experiment_id,
        "method": run.method,
        "version": run.version,
        "status": run.status,
        "parent_run_id": run.parent_run_id,
        "params": run.params,
        "inputs": run.inputs,
        "result": run.result,
        "flags": run.flags,
        "software_version": run.software_version,
        "operator": run.operator,
        "created_at": run.created_at.isoformat(),
        "input_sha256": run.input_sha256,
        "result_sha256": run.result_sha256,
        "properties": [
            {
                "id": p.id,
                "quantity": p.quantity,
                "value": p.value,
                "unit": p.unit,
                "uncertainty": p.uncertainty,
                "uncertainty_kind": p.uncertainty_kind,
                "lower_bound": p.lower_bound,
                "upper_bound": p.upper_bound,
                "conditions": p.conditions,
            }
            for p in run.properties
        ],
        "curves": shown,
        "curves_total_points": {k: len(v) for k, v in curves.items()},
    }


class RunIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    operator: str = ""
    parent_run_id: int | None = None


class PureShearIn(RunIn):
    unnotched_experiment_id: int
    critical_stretch: dict[str, Any] = Field(default_factory=dict)
    lambda_c_definition: Literal["crack_onset", "steady_propagation"] = "crack_onset"
    unnotched_break_stretch: float | None = None
    hysteresis_ratio: float | None = None


class CrackGrowthIn(RunIn):
    steady_run_id: int
    resolution_m: float | None = Field(default=None, gt=0)


class ThresholdIn(BaseModel):
    crack_growth_run_ids: list[int] = Field(min_length=1)
    attach_experiment_id: int
    g_range_j_m2: tuple[float, float] | None = None
    n_bootstrap: int = Field(default=2000, ge=200, le=20000)
    seed: int = 0
    operator: str = ""
    parent_run_id: int | None = None


SIMPLE = {
    "uniaxial": svc.run_uniaxial,
    "cyclic": svc.run_cyclic,
    "fatigue_steady": svc.run_fatigue_steady,
    "dma": svc.run_dma,
}


def _store(state: AppState, s: Any, exp: Experiment, o: svc.Outcome, body: Any) -> dict[str, Any]:
    run = svc.persist(
        s, state.data_dir, exp, o, body.operator or state.settings()["operator"], body.parent_run_id
    )
    s.refresh(run)
    return run_json(state, run)


@router.post("/experiments/{experiment_id}/analyses/{method}")
def run_simple(
    state: State,
    experiment_id: int,
    method: Literal["uniaxial", "cyclic", "fatigue_steady", "dma"],
    body: RunIn,
) -> dict[str, Any]:
    fn = SIMPLE[method]
    with state.db.session() as s:
        exp = get(s, Experiment, experiment_id)
        return _store(state, s, exp, fn(state.data_dir, exp, body.params), body)


@router.post("/experiments/{experiment_id}/pure-shear")
def run_pure_shear(state: State, experiment_id: int, body: PureShearIn) -> dict[str, Any]:
    with state.db.session() as s:
        notched = get(s, Experiment, experiment_id)
        unnotched = get(s, Experiment, body.unnotched_experiment_id)
        o = svc.run_pure_shear(state.data_dir, notched, unnotched, body.model_dump())
        return _store(state, s, notched, o, body)


@router.post("/experiments/{experiment_id}/crack-growth")
def run_crack_growth(state: State, experiment_id: int, body: CrackGrowthIn) -> dict[str, Any]:
    with state.db.session() as s:
        exp = get(s, Experiment, experiment_id)
        steady = get(s, AnalysisRun, body.steady_run_id)
        o = svc.run_crack_growth(state.data_dir, exp, steady, {"resolution_m": body.resolution_m})
        return _store(state, s, exp, o, body)


@router.post("/fatigue/threshold")
def run_threshold(state: State, body: ThresholdIn) -> dict[str, Any]:
    with state.db.session() as s:
        runs = [get(s, AnalysisRun, i) for i in body.crack_growth_run_ids]
        exp = get(s, Experiment, body.attach_experiment_id)
        o = svc.run_threshold(s, runs, body.model_dump())
        return _store(state, s, exp, o, body)


@router.post("/analyses/{run_id}/rerun")
def rerun(state: State, run_id: int, body: RunIn) -> dict[str, Any]:
    """Same method and inputs, new parameters → new version linked to its parent."""
    with state.db.session() as s:
        old = get(s, AnalysisRun, run_id)
        exp = old.experiment
        params = old.params | body.params
        nb = RunIn(params=params, operator=body.operator, parent_run_id=old.id)
        if old.method in SIMPLE:
            fn = SIMPLE[old.method]
            return _store(state, s, exp, fn(state.data_dir, exp, params), nb)
        if old.method == "pure_shear":
            unnotched = get(s, Experiment, old.inputs["unnotched_experiment_id"])
            o = svc.run_pure_shear(state.data_dir, exp, unnotched, params)
            return _store(state, s, exp, o, nb)
        if old.method == "crack_growth":
            steady = get(s, AnalysisRun, params["steady_run_id"])
            return _store(
                state, s, exp, svc.run_crack_growth(state.data_dir, exp, steady, params), nb
            )
        if old.method == "fatigue_threshold":
            runs = [get(s, AnalysisRun, i) for i in old.inputs["crack_growth_run_ids"]]
            return _store(state, s, exp, svc.run_threshold(s, runs, params), nb)
        raise InvalidInputError(f"不支持重新运行 {old.method}")


@router.get("/analyses")
def list_analyses(state: State, method: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with state.db.session() as s:
        q = (
            select(AnalysisRun, Material.name)
            .join(AnalysisRun.experiment)
            .join(Experiment.specimen)
            .join(Material, Specimen.material_id == Material.id)
            .order_by(AnalysisRun.id.desc())
            .limit(limit)
        )
        if method:
            q = q.where(AnalysisRun.method == method)
        return [
            {
                "id": r.id,
                "experiment_id": r.experiment_id,
                "method": r.method,
                "version": r.version,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "material": r.experiment.specimen.material_id,
                "material_name": material_name,
                "specimen": r.experiment.specimen.label,
            }
            for r, material_name in s.execute(q)
        ]


@router.get("/analyses/compare")
def compare(state: State, a: int, b: int) -> dict[str, Any]:
    with state.db.session() as s:
        out: dict[str, Any] = to_jsonable(
            compare_runs(get(s, AnalysisRun, a), get(s, AnalysisRun, b))
        )
        return out


@router.get("/analyses/{run_id}")
def fetch(
    state: State, run_id: int, points: Annotated[int, Query(ge=100, le=100000)] = 2000
) -> dict[str, Any]:
    with state.db.session() as s:
        return run_json(state, get(s, AnalysisRun, run_id), points)


@router.delete("/analyses/{run_id}")
def delete_run(state: State, run_id: int) -> dict[str, Any]:
    """User-confirmed deletion of one analysis version; refused while another analysis uses it."""
    with state.db.session() as s:
        return deletion.delete_run(s, state.data_dir, run_id)


@router.get("/analyses/{run_id}/report.json")
def report_json(state: State, run_id: int) -> Response:
    with state.db.session() as s:
        rep = report.build_report(s, state.data_dir, get(s, AnalysisRun, run_id))
    body = json.dumps(to_jsonable(rep), ensure_ascii=False, indent=1)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="report_run{run_id}.json"'},
    )


@router.get("/analyses/{run_id}/report.html")
def report_html(state: State, run_id: int) -> Response:
    with state.db.session() as s:
        run = get(s, AnalysisRun, run_id)
        rep = report.build_report(s, state.data_dir, run)
        fig = report.figure(state.data_dir, run)
    return Response(
        report.render_html(to_jsonable(rep), fig), media_type="text/html; charset=utf-8"
    )


@router.get("/analyses/{run_id}/curves.csv")
def curves_csv(state: State, run_id: int) -> Response:
    with state.db.session() as s:
        run = get(s, AnalysisRun, run_id)
    curves = svc.run_curves(state.data_dir, run)
    keys = list(curves)
    n = max((len(v) for v in curves.values()), default=0)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            f"# PolyMech Studio run {run.id} ({run.method} v{run.version}), {run.software_version}, SI units"
        ]
    )
    w.writerow(keys)
    for i in range(n):
        w.writerow(
            [
                ""
                if i >= len(curves[k]) or not np.isfinite(curves[k][i])
                else repr(float(curves[k][i]))
                for k in keys
            ]
        )
    name = f"run{run.id}_{run.method}_v{run.version}.csv"
    return Response(
        buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


class StatsIn(BaseModel):
    run_ids: list[int] = Field(min_length=1)


STAT_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "uniaxial": {
        "initial_modulus_pa": ("modulus_fit", "slope"),
        "max_stress_pa": ("max_stress_pa",),
        "break_stress_pa": ("break_stress_pa",),
        "break_stretch": ("break_stretch",),
        "work_of_fracture_j_m3": ("work_of_fracture_j_m3",),
    },
    "pure_shear": {"toughness_j_m2": ("toughness_j_m2",)},
}


@router.post("/statistics")
def statistics(state: State, body: StatsIn) -> dict[str, Any]:
    with state.db.session() as s:
        runs = [get(s, AnalysisRun, i) for i in body.run_ids]
    methods = {r.method for r in runs}
    if len(methods) != 1 or (m := methods.pop()) not in STAT_KEYS:
        raise InvalidInputError("重复样品统计需要同一种分析（单轴拉伸或纯剪切）的结果")
    if any(r.status != "ok" for r in runs):
        raise InvalidInputError("存在临时或未确认的结果，不能进行重复统计")
    if m == "pure_shear" and len({r.result["lambda_c_definition"] for r in runs}) > 1:
        raise InvalidInputError("不同 λc 定义的断裂韧性不能合并统计")
    out: dict[str, Any] = {"method": m, "run_ids": body.run_ids}
    for key, path in STAT_KEYS[m].items():
        vals = []
        for r in runs:
            v: Any = r.result
            for p in path:
                v = v[p]
            vals.append(float(v))
        out[key] = to_jsonable(summarize(vals))
    return out


class DMACompareIn(BaseModel):
    run_ids: list[int] = Field(min_length=1)


@router.post("/dma/compare")
def dma_compare(state: State, body: DMACompareIn) -> dict[str, Any]:
    """Tg of several DMA runs, grouped by (definition, frequency, deformation mode).

    Groups are never merged: Tg from tan δ peak, E″ peak and E′ onset differ systematically,
    and Tg shifts with frequency (SPEC §4.5)."""
    with state.db.session() as s:
        runs = [get(s, AnalysisRun, i) for i in body.run_ids]
        if any(r.method != "dma" for r in runs):
            raise InvalidInputError("样品比较只接受 DMA 分析结果")
        labels = {r.id: f"{r.experiment.specimen.label}（#{r.id} v{r.version}）" for r in runs}
    groups: dict[tuple[str, float | None, str], list[dict[str, Any]]] = {}
    for r in runs:
        mode = r.result["deformation_mode"]
        for series in r.result["series"]:
            for c in series["tg"]:
                key = (c["definition"], c["frequency_hz"], mode)
                groups.setdefault(key, []).append(
                    {
                        "run_id": r.id,
                        "label": labels[r.id],
                        "temperature_k": c["temperature_k"],
                        "ambiguous": c["ambiguous"],
                    }
                )
    out_groups: list[dict[str, Any]] = []
    for (definition, freq, mode), rows in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0.0, kv[0][2])
    ):
        vals = [x["temperature_k"] for x in rows if not x["ambiguous"]]
        out_groups.append(
            {
                "definition": definition,
                "definition_label": TG_LABELS[definition],
                "frequency_hz": freq,
                "deformation_mode": mode,
                "rows": rows,
                "summary": to_jsonable(summarize(vals)) if vals else None,
            }
        )
    notes = []
    if len({g["definition"] for g in out_groups}) > 1:
        notes.append("不同 Tg 定义分组列出，组间不直接比较")
    if len({g["frequency_hz"] for g in out_groups}) > 1:
        notes.append("不同频率的 Tg 分组列出（Tg 随频率升高而升高）")
    if len({g["deformation_mode"] for g in out_groups}) > 1:
        notes.append("拉伸（E）与剪切（G）模式的结果分组列出")
    if any(x["ambiguous"] for g in out_groups for x in g["rows"]):
        notes.append("存在多峰的 Tg 候选：列出但不计入统计")
    return {
        "runs": [{"id": r.id, "label": labels[r.id], "mode": r.result["mode"]} for r in runs],
        "groups": out_groups,
        "notes": notes,
    }
