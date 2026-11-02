"""User-requested deletion of analysis versions and experiments."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .test_workflow import _cyclic_bytes, make_experiment, ok, upload
from .test_workflow import client as client


def _uniaxial(c: TestClient) -> tuple[dict, dict, dict]:
    exp = make_experiment(
        c,
        "SYNTH_uniaxial_gbk_chinese.csv",
        "uniaxial",
        "DEL-1",
        thickness_m=1e-3,
        width_m=2e-3,
        gauge_length_m=0.02,
    )
    v1 = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    v2 = ok(
        c.post(
            f"/api/analyses/{v1['id']}/rerun",
            json={"params": {"modulus_stretch_range": [1.0, 1.02]}},
        )
    )
    return exp, v1, v2


def test_delete_one_version_keeps_the_others(client: TestClient, tmp_path: Path) -> None:
    c = client
    exp, v1, v2 = _uniaxial(c)
    assert v2["parent_run_id"] == v1["id"]
    props_before = ok(c.get("/api/properties"))
    assert {p["source"]["run_id"] for p in props_before} == {v1["id"], v2["id"]}
    out = ok(c.delete(f"/api/analyses/{v1['id']}"))
    assert out["deleted_run"] == v1["id"]
    assert c.get(f"/api/analyses/{v1['id']}").status_code == 404
    left = ok(c.get(f"/api/analyses/{v2['id']}"))
    assert left["parent_run_id"] is None  # link to the deleted version cleared
    assert {p["source"]["run_id"] for p in ok(c.get("/api/properties"))} == {v2["id"]}
    assert [r["id"] for r in ok(c.get(f"/api/experiments/{exp['id']}"))["runs"]] == [v2["id"]]


def test_delete_experiment_removes_runs_raw_files_and_empty_material(
    client: TestClient, tmp_path: Path
) -> None:
    c = client
    data = tmp_path / "data"
    exp, _, _ = _uniaxial(c)
    raw_files = [p for p in (data / "raw").rglob("*") if p.is_file()]
    curves = [p for p in data.rglob("*.parquet")]
    assert raw_files and curves
    out = ok(c.delete(f"/api/experiments/{exp['id']}"))
    assert out == {"deleted_experiment": exp["id"], "deleted_runs": 2, "deleted_raw_files": 1}
    assert c.get(f"/api/experiments/{exp['id']}").status_code == 404
    assert ok(c.get("/api/experiments")) == []
    assert ok(c.get("/api/properties")) == []
    assert not any(p.exists() for p in raw_files + curves)
    assert all(m["name"] != "SYN-MAT" for m in ok(c.get("/api/materials")))


def test_shared_raw_file_survives_deleting_one_experiment(
    client: TestClient, tmp_path: Path
) -> None:
    c = client
    a = make_experiment(
        c,
        "SYNTH_uniaxial_gbk_chinese.csv",
        "uniaxial",
        "A",
        thickness_m=1e-3,
        width_m=2e-3,
        gauge_length_m=0.02,
    )
    make_experiment(
        c,
        "SYNTH_uniaxial_gbk_chinese.csv",
        "uniaxial",
        "B",
        thickness_m=1e-3,
        width_m=2e-3,
        gauge_length_m=0.02,
    )
    raw = [p for p in (tmp_path / "data" / "raw").rglob("*") if p.is_file()]
    assert len(raw) == 1  # same content → same archived file
    ok(c.delete(f"/api/experiments/{a['id']}"))
    assert raw[0].exists()


def test_inputs_of_other_analyses_cannot_be_deleted(client: TestClient) -> None:
    c = client
    f = upload(c, "steady.csv", _cyclic_bytes(1.4))
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
                "specimen_label": "U",
                "test_type": "fatigue_unnotched_cyclic",
                "height_m": 0.01,
                "width_m": 0.06,
                "thickness_m": 1e-3,
            },
        )
    )
    steady = ok(c.post(f"/api/experiments/{exp['id']}/analyses/fatigue_steady", json={}))
    body = "Cycles,Crack length (mm)\n0,15\n10000,15.2\n20000,15.4\n30000,15.6\n"
    f2 = upload(c, "crack.csv", body.encode())
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
                "specimen_label": "N",
                "test_type": "fatigue_crack_growth",
                "crack_resolution_m": 20e-6,
            },
        )
    )
    cg = ok(
        c.post(f"/api/experiments/{exp2['id']}/crack-growth", json={"steady_run_id": steady["id"]})
    )
    for url in (f"/api/analyses/{steady['id']}", f"/api/experiments/{exp['id']}"):
        r = c.delete(url)
        assert r.status_code == 422 and f"#{cg['id']}" in r.json()["detail"]
    assert ok(c.get(f"/api/analyses/{steady['id']}"))["id"] == steady["id"]  # nothing removed
    ok(c.delete(f"/api/experiments/{exp2['id']}"))  # dependent gone → now allowed
    ok(c.delete(f"/api/experiments/{exp['id']}"))


@pytest.mark.parametrize("whole_experiment", [False, True])
def test_saved_plots_keep_their_data_after_deletion_and_id_reuse(
    client: TestClient, whole_experiment: bool
) -> None:
    c = client
    exp, v1, v2 = _uniaxial(c)
    spec = ok(
        c.post(
            "/api/plots/spec",
            json={
                "template_id": "nominal_stress_stretch",
                "runs": [[v1["id"], "Original v1"], [v2["id"], "Original v2"]],
            },
        )
    )
    spec["panels"].append(spec["panels"][0] | {"id": "b"})
    spec["layout"]["cols"] = 2
    saved = [
        ok(
            c.post(
                "/api/plot-configs",
                json={"name": kind, "kind": kind, "spec": spec, "analysis_run_id": v1["id"]},
            )
        )
        for kind in ("config", "template")
    ]
    before = ok(c.post("/api/plots/resolve?max_points=1000000", json=spec))
    csv_before = c.post("/api/plots/data.csv", json={"spec": spec}).content
    if whole_experiment:
        ok(c.delete(f"/api/experiments/{exp['id']}"))
        exp = make_experiment(
            c,
            "SYNTH_uniaxial_gbk_chinese.csv",
            "uniaxial",
            "REPLACEMENT",
            thickness_m=1e-3,
            width_m=4e-3,
            gauge_length_m=0.02,
        )
    else:
        ok(c.delete(f"/api/analyses/{v2['id']}"))
        ok(c.patch(f"/api/experiments/{exp['id']}", json={"width_m": 4e-3}))
    replacement = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    assert replacement["id"] in {v1["id"], v2["id"]}  # SQLite reuses the deleted maximum ID
    for config in saved:
        loaded = ok(c.get(f"/api/plot-configs/{config['id']}"))["spec"]
        assert ok(c.post("/api/plots/resolve?max_points=1000000", json=loaded)) == before
        assert c.post("/api/plots/data.csv", json={"spec": loaded}).content == csv_before
        for panel in loaded["panels"]:
            assert panel["series"][1]["source"]["run_id"] is None
            assert len(panel["series"][1]["source"]["x"]) == v2["curves_total_points"]["stretch"]
