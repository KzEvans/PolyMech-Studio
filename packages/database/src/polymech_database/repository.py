"""Data-access operations used by the API. All functions take an open Session; the caller's
`Database.session()` context provides the transaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polymech_database.errors import NotFoundError
from polymech_database.hashing import hash_arrays, hash_json
from polymech_database.models import (
    AnalysisRun,
    DataColumnMapping,
    DataCorrection,
    Experiment,
    ImportProfileRecord,
    LiteratureMeasurement,
    LiteratureSource,
    Material,
    MechanicalProperty,
    RawDataFile,
    Specimen,
)
from polymech_database.storage import archive_raw, write_curves

# Property vocabulary (SPEC §7.2) → SI unit of the stored value.
PROPERTY_UNITS: dict[str, str] = {
    "elastic_modulus": "Pa",
    "tensile_strength": "Pa",
    "break_stress": "Pa",  # nominal
    "true_break_stress": "Pa",
    "ultimate_stretch": "1",
    "elongation_at_break": "1",  # fraction (3.2 = 320 %); kept apart from λ as reported
    "work_of_fracture": "J/m^3",
    "fracture_toughness": "J/m^2",
    "fatigue_threshold": "J/m^2",
    "hysteresis_energy": "J/m^3",
    "residual_strain": "1",
    "storage_modulus": "Pa",
    "loss_modulus": "Pa",
    "loss_factor": "1",
    "glass_transition_temperature": "K",
    "interfacial_toughness": "J/m^2",
}


def get_or_create_material(s: Session, name: str, **fields: Any) -> Material:
    m = s.scalar(select(Material).where(Material.name == name))
    if m is None:
        m = Material(name=name, **fields)
        s.add(m)
        s.flush()
    return m


def create_specimen(s: Session, material: Material, label: str, **geometry: Any) -> Specimen:
    sp = Specimen(material_id=material.id, label=label, **geometry)
    s.add(sp)
    s.flush()
    return sp


def create_experiment(s: Session, specimen: Specimen, test_type: str, **fields: Any) -> Experiment:
    e = Experiment(specimen_id=specimen.id, test_type=test_type, **fields)
    s.add(e)
    s.flush()
    return e


def get(s: Session, model: type[Any], id_: int) -> Any:
    obj = s.get(model, id_)
    if obj is None:
        raise NotFoundError(f"{model.__tablename__} #{id_} 不存在")
    return obj


def add_raw_file(
    s: Session,
    data_dir: Path,
    data: bytes,
    original_name: str,
    experiment_id: int | None = None,
    **fields: Any,
) -> RawDataFile:
    digest, rel = archive_raw(data_dir, data, original_name)
    rf = RawDataFile(
        experiment_id=experiment_id,
        original_name=Path(original_name).name,
        sha256=digest,
        size_bytes=len(data),
        archive_path=rel,
        **fields,
    )
    s.add(rf)
    s.flush()
    return rf


def set_mappings(s: Session, raw_file: RawDataFile, mappings: Sequence[Mapping[str, Any]]) -> None:
    """Replace the confirmed mapping of a raw file (mappings are inputs, not results)."""
    raw_file.mappings.clear()
    s.flush()
    for m in mappings:
        raw_file.mappings.append(DataColumnMapping(**m))
    s.flush()


def save_profile(s: Session, name: str, instrument: str, rules: list[Any]) -> ImportProfileRecord:
    p = s.scalar(select(ImportProfileRecord).where(ImportProfileRecord.name == name))
    if p is None:
        p = ImportProfileRecord(name=name, instrument=instrument, rules=rules)
        s.add(p)
    else:
        p.instrument, p.rules = instrument, rules
    s.flush()
    return p


def add_correction(
    s: Session, raw_file_id: int, quantity: str, record: Mapping[str, Any]
) -> DataCorrection:
    c = DataCorrection(raw_file_id=raw_file_id, quantity=quantity, **record)
    s.add(c)
    s.flush()
    return c


@dataclass(frozen=True)
class PropertyValue:
    quantity: str
    value: float | None
    uncertainty: float | None = None
    uncertainty_kind: str = ""
    n_replicates: int | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    conditions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity not in PROPERTY_UNITS:
            raise ValueError(f"unknown property {self.quantity!r}")


def _clean(obj: Any) -> Any:
    """JSON-safe copy: NaN/inf → None (JSON has no NaN), numpy scalars → Python."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return f if np.isfinite(f) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def record_analysis(
    s: Session,
    data_dir: Path,
    *,
    experiment: Experiment,
    method: str,
    params: Mapping[str, Any],
    inputs: Mapping[str, Any],
    input_arrays: Mapping[str, NDArray[np.float64]],
    result: Mapping[str, Any],
    flags: Sequence[Mapping[str, Any]],
    curves: Mapping[str, NDArray[np.float64]],
    software_version: str,
    status: str = "ok",
    operator: str = "",
    parent_run_id: int | None = None,
    properties: Sequence[PropertyValue] = (),
    notes: str = "",
) -> AnalysisRun:
    """Append a new version; earlier runs of the same experiment/method are untouched."""
    version = (
        s.scalar(
            select(func.max(AnalysisRun.version)).where(
                AnalysisRun.experiment_id == experiment.id, AnalysisRun.method == method
            )
        )
        or 0
    ) + 1
    clean_params, clean_result = _clean(dict(params)), _clean(dict(result))
    input_hash = hash_arrays(input_arrays, {"params": clean_params, "inputs": _clean(dict(inputs))})
    result_hash = hash_json({"result": clean_result, "flags": _clean(list(flags))})
    curves_rel = None
    if curves:
        curves_rel = f"curves/exp{experiment.id}_{method}_v{version}_{result_hash[:12]}.parquet"
        write_curves(data_dir, curves_rel, curves)
    run = AnalysisRun(
        experiment_id=experiment.id,
        method=method,
        version=version,
        parent_run_id=parent_run_id,
        params=clean_params,
        inputs=_clean(dict(inputs)),
        result=clean_result,
        flags=_clean(list(flags)),
        status=status,
        input_sha256=input_hash,
        result_sha256=result_hash,
        curves_path=curves_rel,
        software_version=software_version,
        operator=operator,
        notes=notes,
    )
    s.add(run)
    s.flush()
    material_id = experiment.specimen.material_id
    for p in properties:
        s.add(
            MechanicalProperty(
                material_id=material_id,
                quantity=p.quantity,
                value=_clean(p.value),
                unit=PROPERTY_UNITS[p.quantity],
                uncertainty=_clean(p.uncertainty),
                uncertainty_kind=p.uncertainty_kind,
                n_replicates=p.n_replicates,
                lower_bound=_clean(p.lower_bound),
                upper_bound=_clean(p.upper_bound),
                conditions=_clean(p.conditions),
                analysis_run_id=run.id,
            )
        )
    s.flush()
    return run


def list_runs(s: Session, experiment_id: int, method: str | None = None) -> list[AnalysisRun]:
    q = select(AnalysisRun).where(AnalysisRun.experiment_id == experiment_id)
    if method:
        q = q.where(AnalysisRun.method == method)
    return list(s.scalars(q.order_by(AnalysisRun.method, AnalysisRun.version)))


def _diff(
    a: Mapping[str, Any], b: Mapping[str, Any], prefix: str = ""
) -> dict[str, tuple[Any, Any]]:
    out: dict[str, tuple[Any, Any]] = {}
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        key = f"{prefix}{k}"
        if isinstance(va, Mapping) and isinstance(vb, Mapping):
            out.update(_diff(va, vb, key + "."))
        elif va != vb:
            out[key] = (va, vb)
    return out


def compare_runs(a: AnalysisRun, b: AnalysisRun) -> dict[str, Any]:
    """Parameter and result differences between two analysis versions."""
    return {
        "runs": [a.id, b.id],
        "versions": [a.version, b.version],
        "same_input_data": a.inputs.get("raw_file_sha256") == b.inputs.get("raw_file_sha256"),
        "params": _diff(a.params, b.params),
        "result": _diff(a.result, b.result),
        "status": (a.status, b.status),
    }


def add_literature_value(
    s: Session,
    *,
    source: LiteratureSource,
    material: Material,
    extraction_method: str,
    page: str,
    figure: str = "",
    table: str = "",
    test_type: str = "",
    notes: str = "",
    values: Sequence[PropertyValue],
) -> LiteratureMeasurement:
    """Only explicitly reported numbers may use extraction_method='reported'."""
    lm = LiteratureMeasurement(
        source_id=source.id,
        material_id=material.id,
        page=page,
        figure=figure,
        table=table,
        extraction_method=extraction_method,
        test_type=test_type,
        notes=notes,
    )
    s.add(lm)
    s.flush()
    for p in values:
        s.add(
            MechanicalProperty(
                material_id=material.id,
                quantity=p.quantity,
                value=p.value,
                unit=PROPERTY_UNITS[p.quantity],
                uncertainty=p.uncertainty,
                uncertainty_kind=p.uncertainty_kind,
                n_replicates=p.n_replicates,
                lower_bound=p.lower_bound,
                upper_bound=p.upper_bound,
                conditions=dict(p.conditions),
                literature_measurement_id=lm.id,
            )
        )
    s.flush()
    return lm
