"""Run engine analyses on stored experiments and turn results into versioned AnalysisRuns."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy.orm import Session

from polymech_api import __version__
from polymech_api.serialization import to_jsonable
from polymech_api.services import corrections
from polymech_database.models import AnalysisRun, Experiment, RawDataFile, Specimen
from polymech_database.repository import PropertyValue, get, record_analysis
from polymech_database.storage import read_archived, read_curves
from polymech_dataio.mapping import MappedColumn, Quantity
from polymech_dataio.normalize import NormalizedData, normalize
from polymech_dataio.reader import RawTable, read_bytes
from polymech_mechanics import cyclic, dma, fatigue, pure_shear, uniaxial
from polymech_mechanics.errors import InvalidInputError, MissingGeometryError
from polymech_mechanics.flags import Flag, warning

SOFTWARE_VERSION = f"polymech-studio {__version__}"
Q = Quantity
EXPERIMENT_METADATA_FIELDS = (
    "id",
    "test_type",
    "instrument",
    "test_date",
    "temperature_k",
    "stretch_rate_per_s",
    "cycle_frequency_hz",
    "fixture",
    "notes",
)


@dataclass
class Outcome:
    method: str
    params: dict[str, Any]
    inputs: dict[str, Any]
    input_arrays: dict[str, NDArray[np.float64]]
    result: dict[str, Any]
    flags: list[Flag]
    curves: dict[str, NDArray[np.float64]]
    status: str = "ok"
    properties: list[PropertyValue] = field(default_factory=list)


# --------------------------------------------------------------------------- loading
def load_table(data_dir: Path, raw: RawDataFile) -> RawTable:
    data = read_archived(data_dir, raw.archive_path, raw.sha256)
    tables = read_bytes(data, raw.original_name)
    if raw.sheet is None:
        return tables[0]
    for t in tables:
        if t.sheet == raw.sheet:
            return t
    raise InvalidInputError(f"文件中找不到工作表 {raw.sheet}")


def load_experiment_data(data_dir: Path, exp: Experiment) -> tuple[NormalizedData, RawDataFile]:
    if not exp.raw_files:
        raise InvalidInputError("该实验没有关联的原始数据文件")
    raw = exp.raw_files[0]
    if not raw.mappings:
        raise InvalidInputError("原始数据的列映射尚未确认")
    mapping = [MappedColumn(m.column_index, Quantity(m.quantity), m.unit) for m in raw.mappings]
    return corrections.apply_active(normalize(load_table(data_dir, raw), mapping), raw), raw


def _finite_mask(*arrays: NDArray[np.float64]) -> NDArray[np.bool_]:
    ok = np.ones(len(arrays[0]), dtype=bool)
    for a in arrays:
        ok &= np.isfinite(a)
    return ok


def _finite_rows(*arrays: NDArray[np.float64]) -> tuple[list[NDArray[np.float64]], int]:
    ok = _finite_mask(*arrays)
    return [a[ok] for a in arrays], int((~ok).sum())


def stress_stretch(
    data: NormalizedData, sp: Specimen, length_field: str
) -> tuple[uniaxial.StressStretchCurve, list[Flag], dict[str, str], NDArray[np.bool_]]:
    """σ_nom and λ from whatever columns exist; geometry is required only when needed.

    length_field: 'gauge_length_m' (tension) or 'height_m' (pure shear).
    Also returns the mask of data rows used (rows with missing values are excluded).
    """
    flags: list[Flag] = []
    how: dict[str, str] = {}
    if (s := data.get(Q.NOMINAL_STRESS)) is not None:
        stress, how["stress"] = s, "nominal_stress column"
    elif (f := data.get(Q.FORCE)) is not None:
        if not (sp.width_m and sp.thickness_m):
            raise MissingGeometryError("由力计算名义应力需要样品宽度和厚度，请在实验元数据中补充")
        stress, how["stress"] = f / (sp.width_m * sp.thickness_m), "force / (width × thickness)"
    else:
        raise InvalidInputError("数据中既没有名义应力列也没有力列")
    if (lam := data.get(Q.STRETCH)) is not None:
        stretch, how["stretch"] = lam, "stretch column"
    elif (e := data.get(Q.ENGINEERING_STRAIN)) is not None:
        stretch, how["stretch"] = 1.0 + e, "1 + engineering strain"
    elif (d := data.get(Q.DISPLACEMENT)) is not None:
        length = getattr(sp, length_field)
        if not length:
            label = "初始标距 L0" if length_field == "gauge_length_m" else "可拉伸高度 H0"
            raise MissingGeometryError(f"由位移计算拉伸比需要{label}，请在实验元数据中补充")
        stretch, how["stretch"] = 1.0 + d / length, f"1 + displacement / {length_field}"
    else:
        raise InvalidInputError("数据中没有拉伸比、应变或位移列")
    keep = _finite_mask(stretch, stress)
    if dropped := int((~keep).sum()):
        flags.append(
            warning("rows_excluded", f"{dropped} 行含缺失值，未参与计算（原始数据保留不变）")
        )
    return uniaxial.StressStretchCurve(stretch[keep], stress[keep]), flags, how, keep


def _conditions(exp: Experiment) -> dict[str, Any]:
    return {
        k: v
        for k, v in {
            "temperature_k": exp.temperature_k,
            "stretch_rate_per_s": exp.stretch_rate_per_s,
            "cycle_frequency_hz": exp.cycle_frequency_hz,
            "test_type": exp.test_type,
        }.items()
        if v is not None
    }


def _flags_json(flags: list[Flag]) -> list[dict[str, Any]]:
    return [to_jsonable(f) for f in flags]


# --------------------------------------------------------------------------- uniaxial
def run_uniaxial(data_dir: Path, exp: Experiment, params: dict[str, Any]) -> Outcome:
    data, raw = load_experiment_data(data_dir, exp)
    curve, flags, how, _ = stress_stretch(data, exp.specimen, "gauge_length_m")
    p = uniaxial.UniaxialParams(
        modulus_stretch_range=tuple(params.get("modulus_stretch_range", (1.0, 1.05))),
        break_drop_fraction=params.get("break_drop_fraction", 0.5),
        break_stretch=params.get("break_stretch"),
        smoothing_window=params.get("smoothing_window"),
    )
    r = uniaxial.analyze_uniaxial(curve, p)
    flags += list(r.flags)
    cond = _conditions(exp) | {"modulus_stretch_range": list(p.modulus_stretch_range)}
    result = to_jsonable(r)
    return Outcome(
        method="uniaxial",
        params=to_jsonable(p),
        inputs={"raw_file_id": raw.id, "raw_file_sha256": raw.sha256, "derived": how},
        input_arrays={"stretch": curve.stretch, "nominal_stress_pa": curve.nominal_stress_pa},
        result=result,
        flags=flags,
        curves={
            "stretch": r.stretch,
            "nominal_stress_pa": r.nominal_stress_pa,
            "true_stress_pa": r.true_stress_pa,
            "strain_energy_density_j_m3": r.strain_energy_density_j_m3,
            "differential_modulus_pa": r.differential_modulus_pa,
        },
        status="ok" if r.break_detected else "provisional",
        properties=[
            PropertyValue(
                "elastic_modulus",
                r.initial_modulus_pa,
                r.modulus_fit.slope_stderr,
                "se",
                conditions=cond,
            ),
            PropertyValue("tensile_strength", r.max_stress_pa, conditions=cond),
            PropertyValue("break_stress", r.break_stress_pa, conditions=cond),
            PropertyValue("ultimate_stretch", r.break_stretch, conditions=cond),
            PropertyValue(
                "work_of_fracture",
                r.work_of_fracture_j_m3,
                r.work_of_fracture_numerical_error_j_m3,
                "numerical",
                conditions=cond,
            ),
        ],
    )


# --------------------------------------------------------------------------- cyclic
def run_cyclic(data_dir: Path, exp: Experiment, params: dict[str, Any]) -> Outcome:
    data, raw = load_experiment_data(data_dir, exp)
    curve, flags, how, _ = stress_stretch(data, exp.specimen, "gauge_length_m")
    p = cyclic.CyclicParams(
        **{k: v for k, v in params.items() if k in cyclic.CyclicParams.__dataclass_fields__}
    )
    r = cyclic.analyze_cyclic(curve.stretch, curve.nominal_stress_pa, p)
    flags += list(r.flags)
    point_cycle = np.zeros(len(curve.stretch))
    for c in r.cycles:
        point_cycle[c.loading_slice[0] : c.loading_slice[1]] = c.index
        if c.unloading_slice:
            point_cycle[c.unloading_slice[0] : c.unloading_slice[1]] = c.index
    nan = float("nan")
    cond = _conditions(exp)
    props = []
    for g in r.amplitude_groups:
        first = next(c for c in r.cycles if c.index == g.cycle_indices[0])
        gc = cond | {"stretch_max": g.stretch_max, "cycle": first.index}
        if first.hysteresis_j_m3 is not None:
            props.append(
                PropertyValue(
                    "hysteresis_energy",
                    first.hysteresis_j_m3,
                    conditions=gc | {"closed": first.closed},
                )
            )
        if first.residual_strain is not None:
            props.append(PropertyValue("residual_strain", first.residual_strain, conditions=gc))
    return Outcome(
        method="cyclic",
        params=to_jsonable(p),
        inputs={"raw_file_id": raw.id, "raw_file_sha256": raw.sha256, "derived": how},
        input_arrays={"stretch": curve.stretch, "nominal_stress_pa": curve.nominal_stress_pa},
        result=to_jsonable(r),
        flags=flags,
        curves={
            "stretch": curve.stretch,
            "nominal_stress_pa": curve.nominal_stress_pa,
            "point_cycle": point_cycle,
            "cycle_index": np.array([c.index for c in r.cycles], dtype=float),
            "hysteresis_j_m3": np.array(
                [c.hysteresis_j_m3 if c.hysteresis_j_m3 is not None else nan for c in r.cycles]
            ),
            "residual_strain": np.array(
                [c.residual_strain if c.residual_strain is not None else nan for c in r.cycles]
            ),
            "peak_stress_pa": np.array([c.peak_stress_pa for c in r.cycles]),
            "stretch_max": np.array([c.stretch_max for c in r.cycles]),
        },
        properties=props,
    )


# --------------------------------------------------------------------------- DMA
def run_dma(data_dir: Path, exp: Experiment, params: dict[str, Any]) -> Outcome:
    data, raw = load_experiment_data(data_dir, exp)
    e1 = data.get(Q.STORAGE_MODULUS)
    if e1 is None:
        raise InvalidInputError("DMA 分析需要储能模量列")
    cols = {
        "temperature_k": data.get(Q.TEMPERATURE),
        "loss_modulus_pa": data.get(Q.LOSS_MODULUS),
        "loss_factor": data.get(Q.LOSS_FACTOR),
        "frequency_hz": data.get(Q.FREQUENCY),
    }
    present = {k: v for k, v in cols.items() if v is not None}
    arrays, dropped = _finite_rows(e1, *present.values())
    e1, present = arrays[0], dict(zip(present, arrays[1:], strict=True))
    fields = dma.DMAParams.__dataclass_fields__
    kw = {k: v for k, v in params.items() if k in fields}
    for k in ("tg_window_k", "onset_baseline_k", "reference_temperatures_k"):
        if kw.get(k) is not None:
            kw[k] = tuple(kw[k])
    p = dma.DMAParams(**kw)
    r = dma.analyze_dma(e1, params=p, **present)
    flags: list[Flag] = []
    if dropped:
        flags.append(
            warning("rows_excluded", f"{dropped} 行含缺失值，未参与计算（原始数据保留不变）")
        )
    flags += list(r.flags)

    o = r.order
    n = len(e1)
    nan = np.full(n, np.nan)
    spike = {q: np.zeros(n) for q in ("storage", "loss", "tan_delta")}
    for sp in r.spikes:
        spike[sp.quantity][sp.index] = 1.0
    curves = {
        "temperature_k": present.get("temperature_k", nan)[o],
        "frequency_hz": present.get("frequency_hz", nan)[o],
        "storage_modulus_pa": e1[o],
        "loss_modulus_pa": (nan if r.loss_modulus_pa is None else r.loss_modulus_pa)[o],
        "loss_factor": (nan if r.loss_factor is None else r.loss_factor)[o],
        "series_index": r.series_index[o].astype(float),
        "spike_storage": spike["storage"][o],
        "spike_loss": spike["loss"][o],
        "spike_tan_delta": spike["tan_delta"][o],
    }

    cond = _conditions(exp) | {"deformation_mode": p.deformation_mode}
    cond.pop("temperature_k", None)
    props: list[PropertyValue] = []
    for s_ in r.series:
        for c in s_.tg:
            if c.ambiguous:
                continue
            props.append(
                PropertyValue(
                    "glass_transition_temperature",
                    c.temperature_k,
                    conditions=cond
                    | {
                        "tg_definition": c.definition,
                        "frequency_hz": c.frequency_hz,
                        "detection": "automatic",
                    },
                )
            )
        for ref in s_.reference_values:
            rc = cond | {"temperature_k": ref.temperature_k, "frequency_hz": ref.frequency_hz}
            props.append(PropertyValue("storage_modulus", ref.storage_modulus_pa, conditions=rc))
            if ref.loss_modulus_pa is not None:
                props.append(PropertyValue("loss_modulus", ref.loss_modulus_pa, conditions=rc))
            if ref.loss_factor is not None:
                props.append(PropertyValue("loss_factor", ref.loss_factor, conditions=rc))
    result = to_jsonable(r)
    for k in ("order", "series_index", "loss_modulus_pa", "loss_factor"):
        result.pop(k, None)  # per-point arrays live in the curve file
    ambiguous = any(c.ambiguous for s_ in r.series for c in s_.tg)
    return Outcome(
        method="dma",
        params=to_jsonable(p),
        inputs={
            "raw_file_id": raw.id,
            "raw_file_sha256": raw.sha256,
            "columns": ["storage_modulus_pa", *present],
        },
        input_arrays={"storage_modulus_pa": e1, **present},
        result=result,
        flags=flags,
        curves=curves,
        status="provisional" if ambiguous else "ok",
        properties=props,
    )


# --------------------------------------------------------------------------- pure shear
def run_pure_shear(
    data_dir: Path, notched: Experiment, unnotched: Experiment, body: dict[str, Any]
) -> Outcome:
    if notched.specimen.material_id != unnotched.specimen.material_id:
        raise InvalidInputError("有裂纹与无裂纹样品必须属于同一材料")
    un_data, un_raw = load_experiment_data(data_dir, unnotched)
    un_curve, flags, how, _ = stress_stretch(un_data, unnotched.specimen, "height_m")
    no_data, no_raw = load_experiment_data(data_dir, notched)
    no_curve, no_flags, _, no_keep = stress_stretch(no_data, notched.specimen, "height_m")
    flags += no_flags
    sp = notched.specimen
    geom = pure_shear.PureShearGeometry(sp.height_m, sp.width_m, sp.thickness_m, sp.notch_length_m)
    cs = body.get("critical_stretch") or {}
    if "crack_onset_time_s" in cs:
        t = no_data.get(Q.TIME)
        if t is None:
            raise InvalidInputError("按时间确定临界拉伸比需要有裂纹样品的时间列")
        t_used = t[no_keep]
        ok = np.isfinite(t_used)
        tt, ll = t_used[ok], no_curve.stretch[ok]
        critical = pure_shear.critical_stretch_from_time(
            tt, ll, float(cs["crack_onset_time_s"]), cs.get("method", "time_sync")
        )
    elif "value" in cs:
        critical = pure_shear.CriticalStretch(
            float(cs["value"]),
            cs.get("method", "manual"),
            bool(cs.get("confirmed", False)),
            cs.get("note", ""),
        )
    else:
        critical = pure_shear.critical_stretch_candidate(no_curve)
    up = uniaxial.UniaxialParams(break_stretch=body.get("unnotched_break_stretch"))
    r = pure_shear.fracture_toughness(
        un_curve,
        geom,
        critical,
        body.get("lambda_c_definition", "crack_onset"),
        up,
        body.get("hysteresis_ratio"),
    )
    flags += list(r.flags)
    cond = _conditions(notched) | {
        "lambda_c_definition": r.lambda_c_definition,
        "lambda_c_method": critical.method,
        "height_m": r.height_m,
    }
    result = to_jsonable(r)
    result["unnotched"] = {
        k: result["unnotched"][k]
        for k in ("break_stretch", "work_of_fracture_j_m3", "break_detected")
    }
    return Outcome(
        method="pure_shear",
        params={
            "lambda_c_definition": r.lambda_c_definition,
            "critical_stretch": to_jsonable(critical),
            "unnotched_break_stretch": body.get("unnotched_break_stretch"),
        },
        inputs={
            "unnotched_experiment_id": unnotched.id,
            "unnotched_raw_file_sha256": un_raw.sha256,
            "unnotched_corrections": corrections.provenance(un_raw),
            "raw_file_id": no_raw.id,
            "raw_file_sha256": no_raw.sha256,
            "derived": how,
        },
        input_arrays={
            "unnotched_stretch": un_curve.stretch,
            "unnotched_stress": un_curve.nominal_stress_pa,
            "notched_stretch": no_curve.stretch,
            "notched_stress": no_curve.nominal_stress_pa,
        },
        result=result,
        flags=flags,
        curves={
            "stretch": r.unnotched.stretch,
            "nominal_stress_pa": r.unnotched.nominal_stress_pa,
            "strain_energy_density_j_m3": r.unnotched.strain_energy_density_j_m3,
            "notched_stretch": no_curve.stretch,
            "notched_stress_pa": no_curve.nominal_stress_pa,
        },
        status="provisional" if r.provisional else "ok",
        properties=[]
        if r.provisional
        else [PropertyValue("fracture_toughness", r.toughness_j_m2, conditions=cond)],
    )


# --------------------------------------------------------------------------- fatigue
def run_fatigue_steady(data_dir: Path, exp: Experiment, body: dict[str, Any]) -> Outcome:
    data, raw = load_experiment_data(data_dir, exp)
    curve, flags, how, _ = stress_stretch(data, exp.specimen, "height_m")
    if not exp.specimen.height_m:
        raise MissingGeometryError("计算能量释放率 G = H0·W 需要可拉伸高度 H0")
    st = fatigue.steady_state_energy(
        curve.stretch,
        curve.nominal_stress_pa,
        body.get("compare_back", 10),
        body.get("tolerance", 0.01),
    )
    flags += list(st.flags)
    loading = fatigue.loading_from_steady_state(
        st, exp.specimen.height_m, body.get("convention", "G_max"), exp.cycle_frequency_hz
    )
    res = to_jsonable(st) | {"loading": to_jsonable(loading)}
    return Outcome(
        method="fatigue_steady",
        params={
            "compare_back": body.get("compare_back", 10),
            "tolerance": body.get("tolerance", 0.01),
            "convention": loading.convention,
        },
        inputs={
            "raw_file_id": raw.id,
            "raw_file_sha256": raw.sha256,
            "height_m": exp.specimen.height_m,
            "derived": how,
        },
        input_arrays={"stretch": curve.stretch, "nominal_stress_pa": curve.nominal_stress_pa},
        result=res,
        flags=flags,
        curves={"stretch": curve.stretch, "nominal_stress_pa": curve.nominal_stress_pa},
        status="ok" if st.stabilized else "provisional",
    )


def _require_steady(steady: AnalysisRun) -> None:
    if steady.method != "fatigue_steady":
        raise InvalidInputError("请选择一个“稳态能量”分析结果作为加载条件")
    if steady.status != "ok" or not steady.result.get("stabilized"):
        raise InvalidInputError(
            f"稳态能量分析 #{steady.id} 未稳定，不能用于裂纹扩展或疲劳阈值分析；请先补充预循环并重新分析"
        )


def run_crack_growth(
    data_dir: Path, exp: Experiment, steady: AnalysisRun, body: dict[str, Any]
) -> Outcome:
    _require_steady(steady)
    data, raw = load_experiment_data(data_dir, exp)
    n = data.get(Q.CYCLE)
    c = data.get(Q.CRACK_LENGTH)
    if c is None and (ext := data.get(Q.CRACK_EXTENSION)) is not None:
        c = ext
    if n is None or c is None:
        raise InvalidInputError("裂纹扩展数据需要循环次数列和裂纹长度（或裂纹扩展量）列")
    (n, c), dropped = _finite_rows(n, c)
    resolution = body.get("resolution_m") or exp.extra.get("crack_resolution_m")
    if not resolution:
        raise MissingGeometryError("缺少裂纹位置测量分辨率，无法确定检测限")
    ld = steady.result["loading"]
    loading = fatigue.FatigueLoading(
        ld["stretch_min"],
        ld["stretch_max"],
        ld["energy_release_rate_j_m2"],
        ld["convention"],
        ld.get("frequency_hz"),
        ld.get("load_ratio"),
    )
    r = fatigue.crack_growth_rate(n, c, loading, float(resolution))
    flags: list[Flag] = []
    if dropped:
        flags.append(
            warning("rows_excluded", f"{dropped} 行含缺失值，未参与计算（原始数据保留不变）")
        )
    return Outcome(
        method="crack_growth",
        params={"resolution_m": float(resolution), "steady_run_id": steady.id},
        inputs={
            "raw_file_id": raw.id,
            "raw_file_sha256": raw.sha256,
            "steady_run_id": steady.id,
            "steady_result_sha256": steady.result_sha256,
        },
        input_arrays={"cycles": n, "crack_length_m": c},
        result=to_jsonable(r) | {"upper_bound_m_per_cycle": r.upper_bound_m_per_cycle},
        flags=flags,
        curves={"crack_cycles": n, "crack_length_m": c, "crack_extension_m": c - c[0]},
    )


def run_threshold(s: Session, runs: list[AnalysisRun], body: dict[str, Any]) -> Outcome:
    if not runs or any(r.method != "crack_growth" for r in runs):
        raise InvalidInputError("疲劳阈值需要一组“裂纹扩展速率”分析结果")
    rates = []
    for r in runs:
        if r.status != "ok":
            raise InvalidInputError(f"裂纹扩展分析 #{r.id} 为临时结果，不能用于正式疲劳阈值分析")
        _require_steady(get(s, AnalysisRun, r.inputs["steady_run_id"]))
        res = r.result
        ld = res["loading"]
        rates.append(
            fatigue.CrackGrowthRate(
                fatigue.FatigueLoading(
                    ld["stretch_min"],
                    ld["stretch_max"],
                    ld["energy_release_rate_j_m2"],
                    ld["convention"],
                    ld.get("frequency_hz"),
                    ld.get("load_ratio"),
                ),
                res["status"],
                res["dc_dn_m_per_cycle"],
                res["detection_limit_m_per_cycle"],
                res["delta_c_m"],
                res["delta_n_cycles"],
                res["n_observations"],
                res["regression_slope_m_per_cycle"],
                res["regression_stderr_m_per_cycle"],
                res["resolution_m"],
            )
        )
    g_range = tuple(body["g_range_j_m2"]) if body.get("g_range_j_m2") else None
    fit = fatigue.fit_threshold(
        rates, g_range, n_bootstrap=body.get("n_bootstrap", 2000), seed=body.get("seed", 0)
    )
    br = fatigue.threshold_bracket(rates)
    flags = list(fit.flags) + list(br.flags)
    if not fit.reportable:
        flags.append(
            warning("threshold_refused", "线性外推阈值未报告：" + "；".join(fit.refusal_reasons))
        )
    meas = [x for x in rates if x.status == "measured"]
    cens = [x for x in rates if x.status != "measured"]
    conv = fit.convention
    props = []
    if fit.reportable and fit.threshold_j_m2 is not None:
        props.append(
            PropertyValue(
                "fatigue_threshold",
                fit.threshold_j_m2,
                fit.threshold_stderr_j_m2,
                "se",
                lower_bound=fit.ci95_j_m2[0] if fit.ci95_j_m2 else None,
                upper_bound=fit.ci95_j_m2[1] if fit.ci95_j_m2 else None,
                conditions={
                    "method": "linear_extrapolation",
                    "G_definition": conv,
                    "g_range_j_m2": list(g_range) if g_range else None,
                },
            )
        )
    if br.lower_bound_j_m2 is not None or br.upper_bound_j_m2 is not None:
        props.append(
            PropertyValue(
                "fatigue_threshold",
                None,
                lower_bound=br.lower_bound_j_m2,
                upper_bound=br.upper_bound_j_m2,
                conditions={
                    "method": "experimental_bracket",
                    "G_definition": conv,
                    "cycles_at_lower_bound": br.cycles_at_lower_bound,
                    "detection_limit_m_per_cycle": br.detection_limit_at_lower_bound_m_per_cycle,
                },
            )
        )
    curves = {
        "g_j_m2": np.array([x.loading.energy_release_rate_j_m2 for x in meas]),
        "dc_dn_m_per_cycle": np.array([x.dc_dn_m_per_cycle for x in meas], dtype=float),
        "censored_g_j_m2": np.array([x.loading.energy_release_rate_j_m2 for x in cens]),
        "censored_upper_m_per_cycle": np.array([x.detection_limit_m_per_cycle for x in cens]),
    }
    if fit.fit is not None and fit.threshold_j_m2 is not None:
        gx = np.linspace(fit.threshold_j_m2, float(curves["g_j_m2"].max()), 50)
        curves["fit_g_j_m2"], curves["fit_dc_dn_m_per_cycle"] = gx, fit.fit.predict(gx)
    return Outcome(
        method="fatigue_threshold",
        params={
            "g_range_j_m2": list(g_range) if g_range else None,
            "n_bootstrap": fit.bootstrap_samples,
            "seed": fit.bootstrap_seed,
        },
        inputs={
            "crack_growth_run_ids": [r.id for r in runs],
            "result_sha256": [r.result_sha256 for r in runs],
        },
        input_arrays={k: v for k, v in curves.items() if not k.startswith("fit_")},
        result={"fit": to_jsonable(fit), "bracket": to_jsonable(br)},
        flags=flags,
        curves=curves,
        status="ok" if fit.reportable else "provisional",
        properties=props,
    )


# --------------------------------------------------------------------------- persistence
def persist(
    s: Session,
    data_dir: Path,
    exp: Experiment,
    o: Outcome,
    operator: str,
    parent_run_id: int | None,
) -> AnalysisRun:
    """Store the outcome as a new version. The specimen geometry used is recorded as an input
    (and enters the input hash), so later metadata edits never change an old run's meaning."""
    sp = exp.specimen
    geometry = {
        g: getattr(sp, g)
        for g in ("thickness_m", "width_m", "gauge_length_m", "height_m", "notch_length_m")
    }
    # corrections are part of the inputs only when the run read this experiment's raw file
    raw = next((r for r in exp.raw_files if r.id == o.inputs.get("raw_file_id")), None)
    used = {"corrections": corrections.provenance(raw)} if raw is not None else {}
    return record_analysis(
        s,
        data_dir,
        experiment=exp,
        method=o.method,
        params=o.params,
        inputs=o.inputs
        | {
            "geometry": geometry,
            "experiment": {k: getattr(exp, k) for k in EXPERIMENT_METADATA_FIELDS},
        }
        | used,
        input_arrays=o.input_arrays,
        result=o.result,
        flags=_flags_json(o.flags),
        curves=o.curves,
        software_version=SOFTWARE_VERSION,
        status=o.status,
        operator=operator,
        parent_run_id=parent_run_id,
        properties=o.properties,
    )


def run_curves(data_dir: Path, run: AnalysisRun) -> dict[str, NDArray[np.float64]]:
    return read_curves(data_dir, run.curves_path) if run.curves_path else {}
