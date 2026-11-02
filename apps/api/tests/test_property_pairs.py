"""Property–property pairs for the materials database comparison chart."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .test_workflow import client as client
from .test_workflow import make_experiment, ok


def test_property_pairs_for_comparison_chart(client: TestClient) -> None:
    c = client
    geo = {"thickness_m": 1e-3, "width_m": 2e-3, "gauge_length_m": 0.02}
    for mat in ("MAT-A", "MAT-B"):
        e = make_experiment(
            c, "SYNTH_uniaxial_gbk_chinese.csv", "uniaxial", "tmpMyFile", material_name=mat, **geo
        )
        v1 = ok(c.post(f"/api/experiments/{e['id']}/analyses/uniaxial", json={}))
        ok(
            c.post(
                f"/api/analyses/{v1['id']}/rerun",
                json={"params": {"modulus_stretch_range": [1.0, 1.02]}},
            )
        )
    qs = {q["quantity"] for q in ok(c.get("/api/properties/quantities"))}
    assert {"elastic_modulus", "work_of_fracture"} <= qs
    url = "/api/properties/pairs?x=elastic_modulus&y=work_of_fracture"
    latest = ok(c.get(url))
    assert latest["x_unit"] == "Pa" and len(latest["points"]) == 2  # one per experiment: v2 only
    assert all(p["same_entry"] for p in latest["points"])
    assert {p["label"] for p in latest["points"]} == {"MAT-A v2", "MAT-B v2"}
    assert {p["material"] for p in latest["points"]} == {"MAT-A", "MAT-B"}
    all_versions = ok(c.get(url + "&latest_only=false"))["points"]
    assert {p["label"] for p in all_versions} == {"MAT-A v1", "MAT-A v2", "MAT-B v1", "MAT-B v2"}
    mat = ok(c.get(url + "&latest_only=false&pairing=material"))
    assert len(mat["points"]) == 8 and "不同的实验" in mat["caution"]  # 2×2 per material
    assert "MAT-A v1 × MAT-A v2" in {p["label"] for p in mat["points"]}
    assert c.get("/api/properties/pairs?x=elastic_modulus&y=elastic_modulus").status_code == 422
