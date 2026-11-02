"""Smoke test of a running desktop backend (frozen or not) over HTTP.

    uv run python scripts/desktop/smoke.py http://127.0.0.1:<port>

Exercises the parts most likely to break when frozen: migrations (fresh DB), file import,
Pint units, the calculation engine, Matplotlib export, literature import, report HTML,
the served UI and the CLI tools on PATH. Uses SYNTHETIC fixtures only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "fixtures" / "import"


def main(base: str) -> int:
    c = httpx.Client(base_url=base, timeout=120)
    t0 = time.time()
    steps: list[tuple[str, object]] = []

    def ok(r: httpx.Response) -> dict:
        assert r.status_code == 200, (
            f"{r.request.method} {r.request.url} → {r.status_code} {r.text[:300]}"
        )
        return r.json()

    steps.append(("health", ok(c.get("/api/health"))))
    html = c.get("/analysis/1").text
    assert '<div id="root">' in html, "UI not served"
    steps.append(("ui", "index.html served for client routes"))
    name = "SYNTH_uniaxial_gbk_chinese.csv"
    up = ok(c.post("/api/imports", files=[("files", (name, (FIX / name).read_bytes()))]))
    t = up["files"][0]["tables"][0]
    maps = [
        {"column_index": i, "quantity": q, "unit": u}
        for i, (q, u) in enumerate([("time", "s"), ("force", "N"), ("displacement", "mm")])
    ]
    assert [s["quantity"] for s in t["suggestions"]] == ["time", "force", "displacement"]
    exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": up["files"][0]["raw_file_id"],
                "mappings": maps,
                "material_name": "SYN-DESKTOP",
                "specimen_label": "D-1",
                "test_type": "uniaxial",
                "thickness_m": 1e-3,
                "width_m": 2e-3,
                "gauge_length_m": 0.02,
            },
        )
    )
    run = ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))
    steps.append(("uniaxial modulus MPa", round(run["result"]["modulus_fit"]["slope"] / 1e6, 4)))
    spec = ok(
        c.post(
            "/api/plots/spec",
            json={"template_id": "nominal_stress_stretch", "runs": [[run["id"], "D-1"]]},
        )
    )
    png = c.post("/api/plots/export", json={"spec": spec, "format": "png"})
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG", png.text[:200]
    svg = c.post("/api/plots/export", json={"spec": spec, "format": "svg"})
    assert svg.status_code == 200 and b"<svg" in svg.content
    steps.append(("matplotlib export", f"png {len(png.content)} B, svg {len(svg.content)} B"))
    rep = c.get(f"/api/analyses/{run['id']}/report.html")
    assert rep.status_code == 200 and "data:image/png" in rep.text
    lit = json.loads((ROOT / "literature" / "theses_chen2024_liu2026.json").read_text("utf-8"))
    steps.append(("literature", ok(c.post("/api/literature/import", json=lit))))
    dma_name = "SYNTH_dma.csv"
    up2 = ok(c.post("/api/imports", files=[("files", (dma_name, (FIX / dma_name).read_bytes()))]))
    exp2 = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": up2["files"][0]["raw_file_id"],
                "material_name": "SYN-DESKTOP",
                "specimen_label": "D-2",
                "test_type": "dma",
                "mappings": [
                    {"column_index": 0, "quantity": "temperature", "unit": "°C"},
                    {"column_index": 1, "quantity": "storage_modulus", "unit": "MPa"},
                    {"column_index": 2, "quantity": "loss_modulus", "unit": "MPa"},
                    {"column_index": 3, "quantity": "loss_factor", "unit": "dimensionless"},
                ],
            },
        )
    )
    dma = ok(c.post(f"/api/experiments/{exp2['id']}/analyses/dma", json={}))
    tg = next(x for x in dma["result"]["series"][0]["tg"] if x["definition"] == "tan_delta_peak")
    steps.append(("DMA tan δ peak °C", round(tg["temperature_k"] - 273.15, 2)))
    assert c.put("/api/settings", json={"ai_effort": "extreme"}).status_code == 422
    steps.append(
        ("AI effort setting", ok(c.put("/api/settings", json={"ai_effort": "low"}))["ai_effort"])
    )
    prov = ok(c.get("/api/ai/providers"))
    steps.append(("AI providers", {p["name"]: p.get("installed") for p in prov["providers"]}))
    steps.append(("origin status", ok(c.get("/api/origin/status")).get("reachable")))
    for k, v in steps:
        print(f"  {k}: {v}")
    print(f"SMOKE PASSED in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
