"""User-requested deletion of experiments and analysis versions (confirmed in the UI; never
done automatically). Refused while another analysis uses the item as input, so no stored
result loses its provenance. Exported Origin projects and saved figures are kept; they only
lose their link to the deleted version."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from polymech_api.services.analysis import run_curves
from polymech_api.services.plot_data import stored_series
from polymech_database.models import (
    AnalysisRun,
    DataCorrection,
    Experiment,
    LiteratureMeasurement,
    Material,
    MechanicalProperty,
    OriginJob,
    PlotConfiguration,
    RawDataFile,
    ReferenceCitation,
    SampleBatch,
    Specimen,
)
from polymech_database.repository import get
from polymech_mechanics.errors import InvalidInputError
from polymech_plotting.spec import PlotSpec, SeriesSource


def _label(r: AnalysisRun) -> str:
    return f"#{r.id}（{r.experiment.specimen.label} {r.method} v{r.version}）"


def _dependents(s: Session, run_ids: set[int], exp_id: int | None = None) -> list[AnalysisRun]:
    """Runs outside the deleted set whose inputs refer to the deleted runs (or experiment)."""
    out = []
    for r in s.scalars(select(AnalysisRun)):
        if r.id in run_ids:
            continue
        inp = r.inputs or {}
        refs = {inp.get("steady_run_id"), *(inp.get("crack_growth_run_ids") or [])}
        if refs & run_ids or (exp_id is not None and inp.get("unnotched_experiment_id") == exp_id):
            out.append(r)
    return out


def _unlink(data_dir: Path, rel: str | None) -> None:
    if rel:
        path = data_dir / rel
        if os.name == "nt" and path.exists():
            # Archived raw files are read-only. Windows requires removing that attribute
            # when the user has explicitly requested deletion of this experiment.
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
        path.unlink(missing_ok=True)


def _delete_runs(s: Session, data_dir: Path, runs: list[AnalysisRun]) -> None:
    ids = [r.id for r in runs]
    by_id = {r.id: r for r in runs}
    curves = {}
    for config in s.scalars(select(PlotConfiguration)):
        spec = PlotSpec.model_validate(config.spec)
        changed = False
        for panel in spec.panels:
            for series in panel.series:
                rid = series.source.run_id
                if rid is None or rid not in by_id:
                    continue
                if rid not in curves:
                    curves[rid] = run_curves(data_dir, by_id[rid])
                x, y, err = stored_series(series.source, curves[rid])
                series.source = SeriesSource(
                    x=x.tolist(), y=y.tolist(), y_err=err.tolist() if err is not None else None
                )
                changed = True
        if changed:
            config.spec = spec.model_dump()
    s.execute(
        update(AnalysisRun).where(AnalysisRun.parent_run_id.in_(ids)).values(parent_run_id=None)
    )
    s.execute(
        update(PlotConfiguration)
        .where(PlotConfiguration.analysis_run_id.in_(ids))
        .values(analysis_run_id=None)
    )
    s.execute(
        update(OriginJob).where(OriginJob.analysis_run_id.in_(ids)).values(analysis_run_id=None)
    )
    for r in runs:
        for p in list(r.properties):
            s.delete(p)
        _unlink(data_dir, r.curves_path)
        s.delete(r)
    s.flush()


def delete_run(s: Session, data_dir: Path, run_id: int) -> dict[str, Any]:
    run = get(s, AnalysisRun, run_id)
    deps = _dependents(s, {run.id})
    if deps:
        raise InvalidInputError(
            f"不能删除：以下分析使用了这个结果作为输入：{'、'.join(_label(d) for d in deps)}。请先删除它们。"
        )
    out = {"deleted_run": run.id, "experiment_id": run.experiment_id}
    _delete_runs(s, data_dir, [run])
    return out


def delete_experiment(s: Session, data_dir: Path, experiment_id: int) -> dict[str, Any]:
    """The experiment, all its analysis versions and their properties, its column mappings and
    data corrections, and its archived raw files (a file shared with another import stays)."""
    exp = get(s, Experiment, experiment_id)
    runs = list(exp.runs)
    deps = _dependents(s, {r.id for r in runs}, exp.id)
    if deps:
        raise InvalidInputError(
            f"不能删除：其他实验的分析使用了这个实验的数据：{'、'.join(_label(d) for d in deps)}。请先删除它们。"
        )
    _delete_runs(s, data_dir, runs)
    raws = list(exp.raw_files)
    for raw in raws:
        for c in s.scalars(select(DataCorrection).where(DataCorrection.raw_file_id == raw.id)):
            s.delete(c)
        shared = s.scalar(
            select(RawDataFile.id).where(
                RawDataFile.archive_path == raw.archive_path, RawDataFile.id != raw.id
            )
        )
        if shared is None:
            _unlink(data_dir, raw.archive_path)
        s.delete(raw)
    specimen = exp.specimen
    s.delete(exp)
    s.flush()
    if s.scalar(select(Experiment.id).where(Experiment.specimen_id == specimen.id)) is None:
        material_id = specimen.material_id
        s.delete(specimen)
        s.flush()
        _drop_empty_material(s, material_id)
    return {
        "deleted_experiment": experiment_id,
        "deleted_runs": len(runs),
        "deleted_raw_files": len(raws),
    }


def _drop_empty_material(s: Session, material_id: int) -> None:
    """An experimental material with nothing left (no specimens, values or literature) goes too."""
    m = s.get(Material, material_id)
    if m is None or m.origin != "experiment":
        return
    used = (
        s.scalar(select(Specimen.id).where(Specimen.material_id == m.id))
        or s.scalar(select(MechanicalProperty.id).where(MechanicalProperty.material_id == m.id))
        or s.scalar(
            select(LiteratureMeasurement.id).where(LiteratureMeasurement.material_id == m.id)
        )
        or s.scalar(select(SampleBatch.id).where(SampleBatch.material_id == m.id))
        or s.scalar(select(ReferenceCitation.id).where(ReferenceCitation.material_id == m.id))
    )
    if used is None:
        s.delete(m)
