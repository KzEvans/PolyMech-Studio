"""Measured evaluation for the course report (SPEC §12.3) — SYNTHETIC data only.

1. Quality checks: inject one known anomaly at a time into clean synthetic uniaxial records and
   count detections (recall) and false alarms on the untouched records (specificity).
2. Batch efficiency: time import → rule mapping → normalisation → quality → analysis for every
   uniaxial/cyclic fixture table (no network, no Origin).
3. Program vs hand calculation: closed-form results for the analytic benchmarks.

Run:  uv run python scripts/eval_quality_and_batch.py
Writes reports/data/eval/quality_batch_<date>.json
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from polymech_dataio.mapping import MappedColumn, Quantity, suggest_mapping
from polymech_dataio.metadata import TestType
from polymech_dataio.normalize import NormalizedData, normalize
from polymech_dataio.quality import check_quality
from polymech_dataio.reader import read_bytes, read_file
from polymech_mechanics import cyclic, uniaxial
from polymech_mechanics.pure_shear import CriticalStretch, PureShearGeometry, fracture_toughness

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures" / "import"
OUT = ROOT / "reports" / "data" / "eval"
RNG = np.random.default_rng(20261026)
MU = 0.4e6


def clean_record(lam_b: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """time [s], force [N], displacement [mm] for a 2 mm × 1 mm × 20 mm specimen."""
    lam = np.linspace(1.0, lam_b, 500)
    sig = MU * (lam - lam**-2) * (1 + 0.003 * RNG.standard_normal(lam.size))
    sig[0] = 0.0
    lam = np.concatenate([lam, lam_b + 0.005 * np.arange(1, 6)])
    sig = np.concatenate([sig, np.abs(RNG.normal(0, 1e3, 5))])
    return (lam - 1) / 0.05, sig * 2e-6, (lam - 1) * 20.0


def to_data(t: np.ndarray, f: np.ndarray, d: np.ndarray) -> tuple[Any, NormalizedData]:
    rows = ["Time (s),Force (N),Displacement (mm)"] + [
        ",".join("" if not np.isfinite(v) else f"{v:.6g}" for v in r)
        for r in zip(t, f, d, strict=True)
    ]
    (table,) = read_bytes("\n".join(rows).encode(), "x.csv")
    data = normalize(
        table,
        [
            MappedColumn(0, Quantity.TIME, "s"),
            MappedColumn(1, Quantity.FORCE, "N"),
            MappedColumn(2, Quantity.DISPLACEMENT, "mm"),
        ],
    )
    return table, data


def inject(kind: str, t: np.ndarray, f: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, ...]:
    t, f, d = t.copy(), f.copy(), d.copy()
    n = len(f)
    imax = int(np.argmax(f))
    k = int(RNG.integers(n // 4, imax - 10))
    if kind == "possible_slip":
        f[k : imax + 1] *= 0.85  # sudden 15 % load drop during loading, then loading continues
    elif kind == "baseline_offset":
        f += 0.1 * f.max()
    elif kind == "saturation":
        cap = 0.9 * f.max()
        f = np.minimum(f, cap)
    elif kind == "signal_jump":
        d[k] += 0.3 * (d.max() - d.min())
    elif kind == "time_not_monotonic":
        t[k] = t[k - 1] - 1.0
    elif kind == "missing_values":
        f[k] = np.nan
    elif kind == "duplicate_rows":
        t = np.insert(t, k, t[k])
        f = np.insert(f, k, f[k])
        d = np.insert(d, k, d[k])
    elif kind == "unit_suspect":
        f = f * 1e6  # force recorded in µN but labelled N
    elif kind == "break_not_found":
        keep = n - 5
        t, f, d = t[:keep], f[:keep], d[:keep]
    return t, f, d


def quality_eval(n_records: int = 30) -> dict[str, Any]:
    kinds = [
        "possible_slip",
        "baseline_offset",
        "saturation",
        "signal_jump",
        "time_not_monotonic",
        "missing_values",
        "duplicate_rows",
        "unit_suspect",
        "break_not_found",
    ]
    per: dict[str, dict[str, int]] = {k: {"injected": 0, "detected": 0} for k in kinds}
    false_alarm_records = 0
    false_alarm_codes: dict[str, int] = {}
    for _ in range(n_records):
        rec = clean_record(float(RNG.uniform(3.0, 6.0)))
        table, data = to_data(*rec)
        warn = {
            i.code for i in check_quality(data, TestType.UNIAXIAL, table) if i.severity != "info"
        }
        if warn:
            false_alarm_records += 1
            for c in warn:
                false_alarm_codes[c] = false_alarm_codes.get(c, 0) + 1
        for kind in kinds:
            table, data = to_data(*inject(kind, *rec))
            codes = {i.code for i in check_quality(data, TestType.UNIAXIAL, table)}
            per[kind]["injected"] += 1
            per[kind]["detected"] += kind in codes
    return {
        "records": n_records,
        "detection_rate": {k: round(v["detected"] / v["injected"], 3) for k, v in per.items()},
        "clean_records_with_any_warning": false_alarm_records,
        "false_alarm_codes": false_alarm_codes,
    }


def batch_eval() -> dict[str, Any]:
    manifest = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for entry in manifest:
        if entry["test_type"] not in ("uniaxial", "cyclic"):
            continue
        t0 = time.perf_counter()
        tables = [t for t in read_file(FIX / entry["file"]) if entry["sheet"] in (None, t.sheet)]
        table = tables[0]
        t_read = time.perf_counter()
        sugg = suggest_mapping(table)
        t_map = time.perf_counter()
        mapping = [
            MappedColumn(
                s.column_index,
                Quantity(entry["columns"][s.header]["quantity"]),
                entry["columns"][s.header]["unit"],
            )
            for s in sugg
        ]
        data = normalize(table, mapping)
        check_quality(data, TestType(entry["test_type"]), table)
        t_q = time.perf_counter()
        geom = entry["metadata"]
        if Quantity.NOMINAL_STRESS in data.columns:
            stress = data.columns[Quantity.NOMINAL_STRESS]
        else:
            stress = data.columns[Quantity.FORCE] / (geom["width_m"] * geom["thickness_m"])
        if Quantity.STRETCH in data.columns:
            lam = data.columns[Quantity.STRETCH]
        elif Quantity.ENGINEERING_STRAIN in data.columns:
            lam = 1 + data.columns[Quantity.ENGINEERING_STRAIN]
        else:
            lam = 1 + data.columns[Quantity.DISPLACEMENT] / geom["gauge_length_m"]
        ok = np.isfinite(lam) & np.isfinite(stress)
        if entry["test_type"] == "uniaxial":
            uniaxial.analyze_uniaxial(uniaxial.StressStretchCurve(lam[ok], stress[ok]))
        else:
            cyclic.analyze_cyclic(lam[ok], stress[ok])
        t_end = time.perf_counter()
        rows.append(
            {
                "table": table.source,
                "rows": table.n_rows,
                "read_ms": round((t_read - t0) * 1e3, 1),
                "mapping_ms": round((t_map - t_read) * 1e3, 1),
                "normalise_quality_ms": round((t_q - t_map) * 1e3, 1),
                "analysis_ms": round((t_end - t_q) * 1e3, 1),
                "total_ms": round((t_end - t0) * 1e3, 1),
            }
        )
    totals = [r["total_ms"] for r in rows]
    return {
        "tables": rows,
        "n": len(rows),
        "median_total_ms": statistics.median(totals),
        "max_total_ms": max(totals),
        "sum_total_ms": round(sum(totals), 1),
    }


def hand_vs_program() -> list[dict[str, Any]]:
    """Closed-form ('hand') values vs engine output for the analytic benchmarks."""
    out = []
    lam = np.linspace(1.0, 4.0, 3001)
    sig = MU * (lam - lam**-2)
    curve = uniaxial.StressStretchCurve(
        np.concatenate([lam, [4.001, 4.002]]), np.concatenate([sig, [0, 0]])
    )
    r = uniaxial.analyze_uniaxial(curve)
    hand = MU * (16 / 2 + 1 / 4 - 1.5)
    out.append(
        {
            "quantity": "neo-Hookean W_f (λ=4)",
            "hand": hand,
            "program": r.work_of_fracture_j_m3,
            "rel_error": abs(r.work_of_fracture_j_m3 - hand) / hand,
        }
    )
    lin = np.linspace(1.0, 2.0, 1001)
    r = uniaxial.analyze_uniaxial(
        uniaxial.StressStretchCurve(
            np.concatenate([lin, [2.001]]), np.concatenate([1e6 * (lin - 1), [0]])
        )
    )
    out.append(
        {
            "quantity": "linear E",
            "hand": 1e6,
            "program": r.initial_modulus_pa,
            "rel_error": abs(r.initial_modulus_pa - 1e6) / 1e6,
        }
    )
    up = np.linspace(1.0, 2.0, 501)
    down = up[::-1][1:]
    rec_l = np.concatenate([up, down])
    rec_s = np.concatenate([1e6 * (up - 1) + 2e6 * (up - 1) * (2 - up), 1e6 * (down - 1)])
    c = cyclic.analyze_cyclic(rec_l, rec_s).cycles[0]
    hand = 2e6 / 6
    out.append(
        {
            "quantity": "closed-loop W_hys",
            "hand": hand,
            "program": c.hysteresis_j_m3,
            "rel_error": abs((c.hysteresis_j_m3 or 0) - hand) / hand,
        }
    )
    ps_l = np.linspace(1.0, 5.0, 4001)
    ps_s = 0.3e6 * (ps_l - ps_l**-3)
    g = fracture_toughness(
        uniaxial.StressStretchCurve(np.concatenate([ps_l, [5.001]]), np.concatenate([ps_s, [0]])),
        PureShearGeometry(height_m=0.01, width_m=0.06, thickness_m=1e-3),
        CriticalStretch(2.7, "manual", True),
    )
    hand = 0.01 * 0.3e6 * (2.7**2 / 2 + 2.7**-2 / 2 - 1)
    out.append(
        {
            "quantity": "pure-shear Gc (λc=2.7)",
            "hand": hand,
            "program": g.toughness_j_m2,
            "rel_error": abs(g.toughness_j_m2 - hand) / hand,
        }
    )
    return out


if __name__ == "__main__":
    res = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data": "SYNTHETIC",
        "quality": quality_eval(),
        "batch": batch_eval(),
        "hand_vs_program": hand_vs_program(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"quality_batch_{datetime.now().strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in res.items() if k != "batch"}
            | {"batch": {k: v for k, v in res["batch"].items() if k != "tables"}},
            ensure_ascii=False,
            indent=1,
        )
    )
