"""End-to-end API workflow on SYNTHETIC fixtures (SPEC §9.4, §11.2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from polymech_api.main import create_app
from polymech_api.serialization import to_jsonable
from polymech_api.settings import Settings
from polymech_database.models import AnalysisRun
from polymech_mechanics import fatigue

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "import"
MANIFEST = {
    (e["file"], e["sheet"]): e
    for e in json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
}
MU = 0.4e6  # synthetic modulus used by scripts/make_fixtures.py


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POLYMECH_NO_KEYCHAIN", "1")
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as c:
        yield c


def ok(r: Any) -> Any:
    assert r.status_code == 200, r.text
    return r.json()


def upload(c: TestClient, name: str, data: bytes | None = None) -> dict[str, Any]:
    payload = data if data is not None else (FIX / name).read_bytes()
    out = ok(c.post("/api/imports", files=[("files", (name, payload))]))
    assert not out["errors"], out["errors"]
    return out["files"][0]


def truth_mappings(
    name: str, table: dict[str, Any], sheet: str | None = None
) -> list[dict[str, Any]]:
    entry = MANIFEST[(name, sheet)]
    return [{"column_index": c["index"], **entry["columns"][c["header"]]} for c in table["columns"]]


def make_experiment(
    c: TestClient, name: str, test_type: str, label: str, **meta: Any
) -> dict[str, Any]:
    f = upload(c, name)
    t = f["tables"][0]
    body = {
        "raw_file_id": f["raw_file_id"],
        "table_index": 0,
        "mappings": truth_mappings(name, t),
        "material_name": "SYN-MAT",
        "specimen_label": label,
        "test_type": test_type,
        **meta,
    }
    return ok(c.post("/api/experiments", json=body))


def test_uniaxial_workflow(client: TestClient) -> None:
    c = client
    name = "SYNTH_uniaxial_gbk_chinese.csv"
    f = upload(c, name)
    t = f["tables"][0]
    assert [s["quantity"] for s in t["suggestions"]] == ["time", "force", "displacement"]
    assert t["preamble_fields"]["样品厚度"] == "1.00 mm"
    chk = ok(
        c.post(
            f"/api/imports/{f['raw_file_id']}/tables/0/check",
            json={"test_type": "uniaxial", "mappings": truth_mappings(name, t)},
        )
    )
    assert not [i for i in chk["issues"] if i["severity"] != "info"]
    assert chk["x_quantity"] == "displacement"

    exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": f["raw_file_id"],
                "table_index": 0,
                "mappings": truth_mappings(name, t),
                "material_name": "SYN-MAT",
                "specimen_label": "U1",
                "test_type": "uniaxial",
                **MANIFEST[(name, None)]["metadata"],
            },
        )
    )
    assert exp["missing_metadata"] == []
    run1 = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={"params": {}}))
    assert run1["version"] == 1
    assert run1["status"] == "ok"
    e = run1["result"]["modulus_fit"]["slope"]
    assert e == pytest.approx(3 * MU, rel=0.06)  # fit over λ∈[1, 1.05] of μ(λ−λ⁻²)
    assert run1["result"]["break_stretch"] == pytest.approx(4.0, abs=0.01)
    assert run1["inputs"]["geometry"]["width_m"] == 2e-3
    assert {p["quantity"] for p in run1["properties"]} >= {"elastic_modulus", "work_of_fracture"}

    run2 = ok(
        c.post(
            f"/api/analyses/{run1['id']}/rerun",
            json={"params": {"modulus_stretch_range": [1.0, 1.02]}},
        )
    )
    assert run2["version"] == 2
    assert run2["parent_run_id"] == run1["id"]
    listed = ok(c.get("/api/analyses?method=uniaxial&limit=2"))
    assert [(r["id"], r["material_name"], r["specimen"]) for r in listed] == [
        (run2["id"], "SYN-MAT", "U1"),
        (run1["id"], "SYN-MAT", "U1"),
    ]
    cmp = ok(c.get(f"/api/analyses/compare?a={run1['id']}&b={run2['id']}"))
    assert cmp["same_input_data"]
    assert "modulus_stretch_range" in cmp["params"]
    again1 = ok(c.get(f"/api/analyses/{run1['id']}"))
    assert again1["result"] == run1["result"]  # the old version is untouched

    csv = c.get(f"/api/analyses/{run1['id']}/curves.csv")
    assert csv.status_code == 200
    assert "nominal_stress_pa" in csv.content.decode("utf-8-sig").splitlines()[1]

    spec = ok(
        c.post(
            "/api/plots/spec",
            json={"template_id": "nominal_stress_stretch", "runs": [[run1["id"], "U1"]]},
        )
    )
    resolved = ok(c.post("/api/plots/resolve", json=spec))
    assert len(resolved["panels"][0]["series"][0]["source"]["x"]) > 100
    png = c.post("/api/plots/export", json={"spec": spec, "format": "png", "filename": "u1"})
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")
    named = c.post("/api/plots/export", json={"spec": spec, "filename": "PEHA 交联剂系列"})
    assert named.status_code == 200  # non-latin-1 names must not break the header
    assert (
        "filename*=UTF-8''PEHA%E4%BA%A4%E8%81%94%E5%89%82%E7%B3%BB%E5%88%97.png"
        in (named.headers["content-disposition"])
    )
    cfg = ok(c.post("/api/plot-configs", json={"name": "U1 曲线", "spec": spec}))
    assert ok(c.get(f"/api/plot-configs/{cfg['id']}"))["spec"] == spec

    # two-panel figure: (a) nominal stress, (b) energy density; export + plotted data as CSV
    w_spec = ok(
        c.post(
            "/api/plots/spec",
            json={"template_id": "nominal_stress_stretch", "runs": [[run2["id"], "U1 v2"]]},
        )
    )
    p2 = w_spec["panels"][0] | {"id": "b", "y": spec["panels"][0]["y"] | {"label": "复制轴"}}
    multi = spec | {
        "panels": [spec["panels"][0], p2],
        "layout": spec["layout"] | {"cols": 2, "width_mm": 170},
    }
    assert spec["panels"][0]["template_id"] == "nominal_stress_stretch"
    svg = c.post("/api/plots/export", json={"spec": multi, "format": "svg"})
    assert svg.status_code == 200 and b"(b)" in svg.content  # panel labels, text kept editable
    data = c.post("/api/plots/data.csv", json={"spec": multi}).content.decode("utf-8-sig")
    rows = data.splitlines()
    assert rows[1] == "panel,series,x,x_unit,y,y_unit,y_err"
    assert {r.split(",")[0] for r in rows[2:]} == {"(a)", "(b)"}
    too_many = multi | {"layout": multi["layout"] | {"cols": 1}}
    assert c.post("/api/plots/export", json={"spec": too_many}).status_code == 422
    tpl = ok(
        c.post("/api/plot-configs", json={"name": "期刊双栏", "spec": multi, "kind": "template"})
    )
    assert [x["id"] for x in ok(c.get("/api/plot-configs?kind=template"))] == [tpl["id"]]
    assert tpl["id"] not in [x["id"] for x in ok(c.get("/api/plot-configs"))]
    ok(c.delete(f"/api/plot-configs/{tpl['id']}"))

    rep = c.get(f"/api/analyses/{run1['id']}/report.html")
    assert rep.status_code == 200
    assert "单轴拉伸分析报告" in rep.text and "data:image/png;base64," in rep.text
    assert "不包含 AI" in rep.text
    rj = ok(c.get(f"/api/analyses/{run1['id']}/report.json"))
    assert rj["provenance"]["result_sha256"] == run1["result_sha256"]
    assert rj["ai_content"] is None

    dash = ok(c.get("/api/dashboard"))
    assert dash["counts"]["analyses"] == 2


def test_missing_geometry_is_refused_with_message(client: TestClient) -> None:
    exp = make_experiment(
        client, "SYNTH_uniaxial_bom_kN.tsv", "uniaxial", "U2", gauge_length_m=0.02
    )
    assert {m["field"] for m in exp["missing_metadata"]} == {"width_m", "thickness_m"}
    r = client.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={})
    assert r.status_code == 422
    assert "宽度" in r.json()["detail"]
    ok(client.patch(f"/api/experiments/{exp['id']}", json={"width_m": 2e-3, "thickness_m": 1e-3}))
    run = ok(client.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    assert any(f["code"] == "rows_excluded" for f in run["flags"])  # the injected blank value


@pytest.mark.parametrize("legacy", [False, True])
def test_reports_use_analysis_time_conditions_after_metadata_edits(
    client: TestClient, legacy: bool
) -> None:
    c = client
    exp = make_experiment(
        c,
        "SYNTH_uniaxial_gbk_chinese.csv",
        "uniaxial",
        "SYN-REPORT",
        thickness_m=1e-3,
        width_m=2e-3,
        gauge_length_m=0.02,
        temperature_k=295.0,
        stretch_rate_per_s=0.1,
        cycle_frequency_hz=2.0,
        instrument="SYN instrument A",
        notes="Original conditions",
    )
    run = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    if legacy:
        # Older builds stored property conditions, but no complete experiment snapshot.
        with c.app.state.polymech.db.session() as s:
            stored = s.get_one(AnalysisRun, run["id"])
            stored.inputs = {k: v for k, v in stored.inputs.items() if k != "experiment"}
    ok(
        c.patch(
            f"/api/experiments/{exp['id']}",
            json={
                "temperature_k": 330.0,
                "stretch_rate_per_s": 0.5,
                "cycle_frequency_hz": 5.0,
                "instrument": "SYN instrument B",
                "notes": "Updated conditions",
            },
        )
    )
    rep = ok(c.get(f"/api/analyses/{run['id']}/report.json"))
    assert rep["experiment"]["temperature_k"] == 295.0
    assert rep["experiment"]["stretch_rate_per_s"] == 0.1
    assert rep["experiment"]["cycle_frequency_hz"] == 2.0
    if legacy:
        assert rep["experiment"]["instrument"] is None
        assert rep["experiment"]["notes"] is None
        assert any(f["code"] == "legacy_experiment_metadata" for f in rep["quality_flags"])
    else:
        assert rep["experiment"]["instrument"] == "SYN instrument A"
        assert rep["experiment"]["notes"] == "Original conditions"
    again = ok(c.get(f"/api/analyses/{run['id']}"))
    assert again["input_sha256"] == run["input_sha256"]
    assert again["result_sha256"] == run["result_sha256"]
    latest = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    new_rep = ok(c.get(f"/api/analyses/{latest['id']}/report.json"))
    assert new_rep["experiment"]["temperature_k"] == 330.0
    assert new_rep["experiment"]["instrument"] == "SYN instrument B"


def test_multisheet_creates_one_experiment_per_sheet(client: TestClient) -> None:
    name = "SYNTH_uniaxial_multisheet.xlsx"
    f = upload(client, name)
    ids = []
    for t in f["tables"]:
        exp = ok(
            client.post(
                "/api/experiments",
                json={
                    "raw_file_id": f["raw_file_id"],
                    "table_index": t["index"],
                    "mappings": truth_mappings(name, t, t["sheet"]),
                    "material_name": "SYN-MAT",
                    "specimen_label": t["sheet"],
                    "test_type": "uniaxial",
                    **MANIFEST[(name, t["sheet"])]["metadata"],
                },
            )
        )
        ids.append(exp["id"])
    runs = [ok(client.post(f"/api/experiments/{i}/analyses/uniaxial", json={})) for i in ids]
    assert runs[0]["result"]["break_stretch"] != runs[1]["result"]["break_stretch"]
    stats = ok(client.post("/api/statistics", json={"run_ids": [r["id"] for r in runs]}))
    assert stats["initial_modulus_pa"]["n"] == 2


def test_cyclic(client: TestClient) -> None:
    exp = make_experiment(client, "SYNTH_cyclic_steps.csv", "cyclic", "C1")
    run = ok(client.post(f"/api/experiments/{exp['id']}/analyses/cyclic", json={}))
    cycles = run["result"]["cycles"]
    assert [round(c["stretch_max"], 3) for c in cycles] == [1.5, 1.5, 2.0, 2.0, 2.5]
    assert all(c["hysteresis_j_m3"] > 0 for c in cycles)
    assert len(run["result"]["amplitude_groups"]) == 3


def test_pure_shear_toughness(client: TestClient) -> None:
    meta = MANIFEST[("SYNTH_pure_shear_unnotched.csv", None)]["metadata"]
    un = make_experiment(
        client, "SYNTH_pure_shear_unnotched.csv", "pure_shear_unnotched", "PS-U", **meta
    )
    no = make_experiment(
        client, "SYNTH_pure_shear_notched.csv", "pure_shear_notched", "PS-N", **meta
    )
    cand = ok(
        client.post(
            f"/api/experiments/{no['id']}/pure-shear", json={"unnotched_experiment_id": un["id"]}
        )
    )
    assert cand["status"] == "provisional"
    assert cand["properties"] == []
    lc = 2.2
    conf = ok(
        client.post(
            f"/api/experiments/{no['id']}/pure-shear",
            json={
                "unnotched_experiment_id": un["id"],
                "critical_stretch": {"value": lc, "method": "photo", "confirmed": True},
            },
        )
    )
    w = MU * (lc**2 / 2 + lc**-2 / 2 - 1)
    assert conf["status"] == "ok"
    assert conf["result"]["toughness_j_m2"] == pytest.approx(meta["height_m"] * w, rel=1e-3)
    timed = ok(
        client.post(
            f"/api/experiments/{no['id']}/pure-shear",
            json={
                "unnotched_experiment_id": un["id"],
                "critical_stretch": {"crack_onset_time_s": 24.0, "method": "video_frame"},
            },
        )
    )
    assert timed["result"]["critical_stretch"]["value"] == pytest.approx(1 + 0.05 * 24.0, rel=1e-3)


def _cyclic_bytes(amp: float, n_cycles: int = 30) -> bytes:
    rows = ["Stretch,Nominal stress (MPa)"]
    for k in range(n_cycles):
        f = 1 - 0.2 * np.exp(-k / 3)
        up = np.linspace(1.0, amp, 60)
        down = up[::-1][1:]
        for lam in up if k == 0 else up[1:]:
            rows.append(f"{lam:.6f},{f * MU * (lam - lam**-3) / 1e6:.6g}")
        for lam in down:
            rows.append(f"{lam:.6f},{0.7 * f * MU * (lam - lam**-3) / 1e6:.6g}")
    return ("\n".join(rows) + "\n").encode()


def test_unstable_fatigue_inputs_are_refused_including_legacy_growth_runs(
    client: TestClient,
) -> None:
    c = client
    raw = upload(c, "SYN-unstable.csv", _cyclic_bytes(1.6, n_cycles=3))
    exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": raw["raw_file_id"],
                "mappings": [
                    {"column_index": 0, "quantity": "stretch", "unit": "dimensionless"},
                    {"column_index": 1, "quantity": "nominal_stress", "unit": "MPa"},
                ],
                "material_name": "SYN-FAT",
                "specimen_label": "SYN-UNSTABLE",
                "test_type": "fatigue_unnotched_cyclic",
                "height_m": 0.01,
            },
        )
    )
    steady = ok(c.post(f"/api/experiments/{exp['id']}/analyses/fatigue_steady", json={}))
    assert steady["status"] == "provisional"
    assert not steady["result"]["stabilized"]
    raw = upload(c, "SYN-crack.csv", b"Cycles,Crack length (mm)\n0,15\n10000,16\n20000,17\n")
    crack_exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": raw["raw_file_id"],
                "mappings": [
                    {"column_index": 0, "quantity": "cycle_number", "unit": "dimensionless"},
                    {"column_index": 1, "quantity": "crack_length", "unit": "mm"},
                ],
                "material_name": "SYN-FAT",
                "specimen_label": "SYN-NOTCHED",
                "test_type": "fatigue_crack_growth",
                "crack_resolution_m": 20e-6,
            },
        )
    )
    refused = c.post(
        f"/api/experiments/{crack_exp['id']}/crack-growth", json={"steady_run_id": steady["id"]}
    )
    assert refused.status_code == 422 and "未稳定" in refused.json()["detail"]
    rate = fatigue.crack_growth_rate(
        [0, 10000, 20000],
        [0.015, 0.016, 0.017],
        fatigue.FatigueLoading(**steady["result"]["loading"]),
        20e-6,
    )
    # Simulate a growth run saved by the older build, which lost the upstream warning.
    with c.app.state.polymech.db.session() as s:
        old = AnalysisRun(
            experiment_id=crack_exp["id"],
            method="crack_growth",
            version=1,
            status="ok",
            inputs={"steady_run_id": steady["id"]},
            result=to_jsonable(rate),
            input_sha256="0" * 64,
            result_sha256="0" * 64,
            software_version="SYN legacy",
        )
        s.add(old)
        s.flush()
        old_id = old.id
    refused = c.post(
        "/api/fatigue/threshold",
        json={"crack_growth_run_ids": [old_id], "attach_experiment_id": crack_exp["id"]},
    )
    assert refused.status_code == 422 and "未稳定" in refused.json()["detail"]
    assert ok(c.get("/api/analyses?method=fatigue_threshold")) == []


def test_fatigue_threshold_chain(client: TestClient) -> None:
    c = client
    h0, k, g0 = 0.01, 2e-12, 60.0  # m, m/cycle per J/m², J/m²
    growth_runs = []
    attach = None
    for i, amp in enumerate((1.15, 1.3, 1.45, 1.6, 1.75)):
        f = upload(c, f"steady_{i}.csv", _cyclic_bytes(amp))
        exp = ok(
            c.post(
                "/api/experiments",
                json={
                    "raw_file_id": f["raw_file_id"],
                    "mappings": [
                        {"column_index": 0, "quantity": "stretch", "unit": "dimensionless"},
                        {"column_index": 1, "quantity": "nominal_stress", "unit": "MPa"},
                    ],
                    "material_name": "SYN-FAT",
                    "specimen_label": f"F-U{i}",
                    "test_type": "fatigue_unnotched_cyclic",
                    "height_m": h0,
                    "width_m": 0.06,
                    "thickness_m": 1e-3,
                },
            )
        )
        steady = ok(c.post(f"/api/experiments/{exp['id']}/analyses/fatigue_steady", json={}))
        assert steady["status"] == "ok"
        g = steady["result"]["loading"]["energy_release_rate_j_m2"]
        rate = max(k * (g - g0), 0.0)
        n = np.arange(0, 50_001, 10_000)
        cl = 15e-3 + rate * n
        body = "Cycles,Crack length (mm)\n" + "\n".join(
            f"{a},{b * 1e3:.9f}" for a, b in zip(n, cl, strict=True)
        )
        f2 = upload(c, f"crack_{i}.csv", body.encode())
        exp2 = ok(
            c.post(
                "/api/experiments",
                json={
                    "raw_file_id": f2["raw_file_id"],
                    "mappings": [
                        {"column_index": 0, "quantity": "cycle_number", "unit": "dimensionless"},
                        {"column_index": 1, "quantity": "crack_length", "unit": "mm"},
                    ],
                    "material_name": "SYN-FAT",
                    "specimen_label": f"F-N{i}",
                    "test_type": "fatigue_crack_growth",
                    "crack_resolution_m": 20e-6,
                },
            )
        )
        attach = attach or exp2["id"]
        cg = ok(
            c.post(
                f"/api/experiments/{exp2['id']}/crack-growth", json={"steady_run_id": steady["id"]}
            )
        )
        if g < g0 + 20e-6 / 50_000 / k:
            assert cg["result"]["status"] == "below_detection_limit"
            assert cg["result"]["dc_dn_m_per_cycle"] is None
        growth_runs.append(cg["id"])
    th = ok(
        c.post(
            "/api/fatigue/threshold",
            json={"crack_growth_run_ids": growth_runs, "attach_experiment_id": attach},
        )
    )
    fit = th["result"]["fit"]
    assert fit["reportable"], fit["refusal_reasons"]
    assert fit["threshold_j_m2"] == pytest.approx(g0, rel=1e-3)
    assert th["result"]["bracket"]["upper_bound_j_m2"] is not None


def _dma_bytes(tp_c: float, freq: float) -> bytes:
    t = np.linspace(-70, 100, 171)
    e1 = 1e3 / (1 + np.exp((t - tp_c + 5) / 6)) + 2.0
    tan = 0.05 + 1.2 * np.exp(-(((t - tp_c) / 10) ** 2))
    rows = ["Temperature (°C),Frequency (Hz),Storage Modulus (MPa),Tan Delta"]
    rows += [f"{a:.6g},{freq},{b:.8g},{c:.8g}" for a, b, c in zip(t, e1, tan, strict=True)]
    return ("\n".join(rows) + "\n").encode()


def test_dma_tg_definitions_and_comparison(client: TestClient) -> None:
    c = client
    exp = make_experiment(c, "SYNTH_dma.csv", "dma", "D-1")
    run = ok(c.post(f"/api/experiments/{exp['id']}/analyses/dma", json={}))
    assert run["status"] == "ok"
    (series,) = run["result"]["series"]
    tg = {x["definition"]: x["temperature_k"] for x in series["tg"]}
    assert tg["tan_delta_peak"] == pytest.approx(273.15 - 15, abs=0.05)  # fixture peak −15 °C
    assert tg["loss_modulus_peak"] < tg["tan_delta_peak"]
    assert run["result"]["consistency_deviation"] < 1e-3
    props = [p for p in run["properties"] if p["quantity"] == "glass_transition_temperature"]
    assert {p["conditions"]["tg_definition"] for p in props} == set(tg)
    assert all(p["unit"] == "K" for p in props)
    ref = next(p for p in run["properties"] if p["quantity"] == "loss_factor")
    assert ref["conditions"]["temperature_k"] == pytest.approx(298.15)
    assert len(run["curves"]["temperature_k"]) == 171

    # a second specimen measured at 10 Hz: grouped separately, never pooled with 1 Hz
    mappings = [
        {"column_index": 0, "quantity": "temperature", "unit": "°C"},
        {"column_index": 1, "quantity": "frequency", "unit": "Hz"},
        {"column_index": 2, "quantity": "storage_modulus", "unit": "MPa"},
        {"column_index": 3, "quantity": "loss_factor", "unit": "dimensionless"},
    ]
    runs = [run["id"]]
    for i, (tp, fr) in enumerate(((-15.0, 1.0), (-9.0, 10.0))):
        f = upload(c, f"dma_{i}.csv", _dma_bytes(tp, fr))
        e = ok(
            c.post(
                "/api/experiments",
                json={
                    "raw_file_id": f["raw_file_id"],
                    "mappings": mappings,
                    "material_name": "SYN-MAT",
                    "specimen_label": f"D-{i + 2}",
                    "test_type": "dma",
                },
            )
        )
        runs.append(ok(c.post(f"/api/experiments/{e['id']}/analyses/dma", json={}))["id"])
    cmp_ = ok(c.post("/api/dma/compare", json={"run_ids": runs}))
    tan_groups = [g for g in cmp_["groups"] if g["definition"] == "tan_delta_peak"]
    assert {g["frequency_hz"] for g in tan_groups} == {None, 1.0, 10.0}
    assert any("频率" in n for n in cmp_["notes"])
    one_hz = next(g for g in tan_groups if g["frequency_hz"] == 1.0)
    assert one_hz["summary"]["n"] == 1
    assert one_hz["rows"][0]["temperature_k"] == pytest.approx(258.15, abs=0.05)

    rr = ok(
        c.post(f"/api/analyses/{run['id']}/rerun", json={"params": {"tg_window_k": [200, 250]}})
    )
    assert rr["version"] == 2 and rr["parent_run_id"] == run["id"]
    assert all(x["definition"] != "tan_delta_peak" for x in rr["result"]["series"][0]["tg"])

    html_ = c.get(f"/api/analyses/{run['id']}/report.html")
    assert (
        html_.status_code == 200
        and "tan δ = E″/E′" in html_.text
        and "data:image/png" in html_.text
    )

    bad = c.post("/api/dma/compare", json={"run_ids": [run["id"], 99999]})
    assert bad.status_code == 404


def test_corrections_apply_to_new_versions_only(client: TestClient) -> None:
    c = client
    name = "SYNTH_uniaxial_gbk_chinese.csv"
    exp = make_experiment(c, name, "uniaxial", "C-1", **MANIFEST[(name, None)]["metadata"])
    v1 = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    assert v1["inputs"]["corrections"] == []
    lst = ok(c.get(f"/api/experiments/{exp['id']}/corrections"))
    assert {q["id"] for q in lst["quantities"]} == {"time", "force", "displacement"}

    zero = {"algorithm": "zero_offset", "quantity": "force", "n_points": 5}
    prev = ok(
        c.post(f"/api/experiments/{exp['id']}/corrections/preview", json={"correction": zero})
    )
    assert prev["x_key"] == "displacement" and len(prev["before"]) == len(prev["after"])
    offset = prev["record"]["params"]["offset"]
    assert prev["after"][0] == pytest.approx(prev["before"][0] - offset)
    assert (
        ok(c.get(f"/api/experiments/{exp['id']}/corrections"))["corrections"] == []
    )  # nothing saved

    saved = ok(
        c.post(
            f"/api/experiments/{exp['id']}/corrections",
            json={"correction": zero, "operator": "tester"},
        )
    )
    assert saved["active"] and saved["operator"] == "tester" and saved["params"]["n_points"] == 5
    smooth = {"algorithm": "savgol", "quantity": "force", "window": 11, "polyorder": 3}
    ok(c.post(f"/api/experiments/{exp['id']}/corrections", json={"correction": smooth}))
    v2 = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    assert [x["algorithm"] for x in v2["inputs"]["corrections"]] == ["zero_offset", "savgol"]
    assert v2["input_sha256"] != v1["input_sha256"]
    assert ok(c.get(f"/api/analyses/{v1['id']}"))["result"] == v1["result"]  # v1 untouched

    ok(c.post(f"/api/corrections/{saved['id']}/deactivate"))
    v3 = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    assert [x["algorithm"] for x in v3["inputs"]["corrections"]] == ["savgol"]
    hist = ok(c.get(f"/api/experiments/{exp['id']}/corrections"))["corrections"]
    assert [h["active"] for h in hist] == [False, True]  # history kept

    base = {
        "algorithm": "linear_baseline",
        "quantity": "force",
        "x_quantity": "displacement",
        "x_min": 0.0,
        "x_max": 2e-3,
    }
    assert (
        ok(c.post(f"/api/experiments/{exp['id']}/corrections/preview", json={"correction": base}))[
            "record"
        ]["params"]["stop"]
        > 2
    )
    contact = {"algorithm": "shift_to_contact", "quantity": "displacement", "threshold": 0.05}
    assert (
        "contact_index"
        in ok(
            c.post(
                f"/api/experiments/{exp['id']}/corrections/preview", json={"correction": contact}
            )
        )["record"]["params"]
    )
    bad = [
        {"algorithm": "savgol", "quantity": "force", "window": 10},  # even window
        base | {"x_min": 1.0, "x_max": 0.5},
        {"algorithm": "zero_offset", "quantity": "stretch", "n_points": 3},  # column absent
        {
            "algorithm": "shift_to_contact",
            "quantity": "force",
            "threshold": 1.0,
        },  # only displacement
    ]
    for b in bad:
        assert (
            c.post(
                f"/api/experiments/{exp['id']}/corrections/preview", json={"correction": b}
            ).status_code
            == 422
        ), b


def test_bad_upload_and_unknown_records(client: TestClient) -> None:
    out = ok(
        client.post(
            "/api/imports", files=[("files", ("x.csv", (FIX / "SYNTH_corrupt.csv").read_bytes()))]
        )
    )
    assert out["files"] == []
    assert "编码" in out["errors"][0]["error"]
    assert client.get("/api/experiments/999").status_code == 404
    assert client.get("/api/analyses/999").status_code == 404


def test_settings_never_return_secrets(client: TestClient) -> None:
    s = ok(client.get("/api/settings"))
    assert s["ai_provider"] == "codex"
    assert s["secrets"]["bridge_token"] is False
    s = ok(client.put("/api/settings", json={"bridge_url": "http://10.0.0.5:8765"}))
    assert s["bridge_url"] == "http://10.0.0.5:8765"
    assert client.put("/api/settings", json={"nope": 1}).status_code == 422


def test_required_metadata_endpoint(client: TestClient) -> None:
    r = ok(client.get("/api/metadata/required?test_type=uniaxial&quantities=force,displacement"))
    assert [f["field"] for f in r] == ["material_name", "width_m", "thickness_m", "gauge_length_m"]
    r = ok(
        client.get(
            "/api/metadata/required?test_type=pure_shear_notched&quantities=nominal_stress,stretch"
        )
    )
    assert {f["field"] for f in r} == {"material_name", "height_m", "notch_length_m"}
