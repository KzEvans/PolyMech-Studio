"""Mac ↔ Bridge protocol test. The bridge app here is the real polymech_bridge server with an
injected queue executor; real Origin execution is covered by the VM self-test and the
end-to-end acceptance run (docs/ORIGIN_BRIDGE.md)."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from polymech_api.main import create_app
from polymech_api.services.origin import BridgeClient, OriginUnavailableError
from polymech_api.settings import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bridge" / "windows-origin"))
from polymech_bridge.schema import PlotJob
from polymech_bridge.server import create_app as create_bridge
from polymech_bridge.worker import OriginWorker

from .test_workflow import MANIFEST, ok, truth_mappings, upload

TOKEN = "bridge-test-token-0123456789abcdefghijklmn"
SUBMITTED: list[dict[str, Any]] = []


def executor(st: Any) -> dict[str, Any]:
    SUBMITTED.append(st.job.model_dump())
    (st.dir / f"{st.job.file_stem}.opju").write_bytes(b"placeholder written by queue test")
    (st.dir / f"{st.job.file_stem}_Graph1.png").write_bytes(b"\x89PNG placeholder")
    return {
        "made": {
            "opju": f"{st.job.file_stem}.opju",
            "exports": {"png": [f"{st.job.file_stem}_Graph1.png"]},
            "export_errors": {},
        },
        "verification": {"passed": True, "checks": []},
    }


@pytest.fixture
def apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, TestClient]]:
    monkeypatch.setenv("POLYMECH_NO_KEYCHAIN", "1")
    monkeypatch.setenv("POLYMECH_BRIDGE_TOKEN", TOKEN)
    bridge = create_bridge(
        TOKEN, tmp_path / "bridge", OriginWorker(tmp_path / "bridge", executor=executor)
    )
    with TestClient(bridge) as b, TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as c:
        c.app.state.polymech.local_origin = None  # type: ignore[attr-defined]  # remote protocol fixture
        c.app.state.bridge_client_factory = lambda base_url, timeout: b  # type: ignore[attr-defined]
        ok(c.put("/api/settings", json={"bridge_url": "http://bridge.test"}))
        yield c, b


def _uniaxial_run(c: TestClient) -> dict[str, Any]:
    name = "SYNTH_uniaxial_gbk_chinese.csv"
    f = upload(c, name)
    exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": f["raw_file_id"],
                "mappings": truth_mappings(name, f["tables"][0]),
                "material_name": "合成材料 SYN",
                "specimen_label": "U1",
                "test_type": "uniaxial",
                **MANIFEST[(name, None)]["metadata"],
            },
        )
    )
    return ok(c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={}))


def test_status_reports_bridge(apps: tuple[TestClient, TestClient]) -> None:
    c, _ = apps
    st = ok(c.get("/api/origin/status"))
    assert st["reachable"] is True
    assert st["token_configured"] is True
    assert st["capabilities"]["templates"]


def test_job_roundtrip_and_archive(apps: tuple[TestClient, TestClient]) -> None:
    c, _ = apps
    run = _uniaxial_run(c)
    job = ok(
        c.post(
            "/api/origin/jobs", json={"run_id": run["id"], "template_id": "nominal_stress_stretch"}
        )
    )
    for _ in range(100):
        job = ok(c.get(f"/api/origin/jobs/{job['id']}"))
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.02)
    assert job["status"] == "done"
    assert job["opju_file"].startswith(
        "SYN_uniaxial_"
    )  # Chinese material name → ASCII slug + id fallback
    assert job["opju_file"].endswith(f"_uniaxial-v{run['version']}.opju")
    assert job["png_file"] in job["files"]
    assert c.get(f"/api/origin/jobs/{job['id']}/files/{job['opju_file']}").status_code == 200
    sent = PlotJob.model_validate(SUBMITTED[-1])
    assert [b.name for b in sent.books] == ["RawData", "Processed", "Summary", "Metadata"]
    raw = sent.books[0].sheets[0].columns
    assert [c.long_name for c in raw] == ["时间", "力", "位移"]
    assert [c.units for c in raw] == ["s", "N", "mm"]  # original units, untouched
    proc = sent.books[1].sheets[0].columns
    assert proc[1].units == "MPa"
    assert max(v for v in proc[1].values if v is not None) == pytest.approx(
        run["result"]["max_stress_pa"] / 1e6
    )  # type: ignore[type-var]
    meta = dict(
        zip(
            sent.books[3].sheets[0].columns[0].values,
            sent.books[3].sheets[0].columns[1].values,
            strict=True,
        )
    )
    assert meta["result_sha256"] == run["result_sha256"]
    assert sent.graphs[0].template == "pm_thesis_line"  # default style = thesis figures
    assert sent.image_width_px == 3216


def _wait(c: TestClient, job: dict[str, Any]) -> dict[str, Any]:
    for _ in range(100):
        job = ok(c.get(f"/api/origin/jobs/{job['id']}"))
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.02)
    return job


def test_plot_studio_figure_becomes_editable_origin_graphs(
    apps: tuple[TestClient, TestClient],
) -> None:
    """Plot Studio → Origin: one workbook + one graph page per panel, every series plotted from
    its own columns at full resolution, with the figure's colours, line styles and axes."""
    c, _ = apps
    r1 = _uniaxial_run(c)
    r2 = ok(c.post(f"/api/experiments/{r1['experiment_id']}/analyses/uniaxial", json={}))
    spec = ok(
        c.post(
            "/api/plots/spec",
            json={
                "template_id": "nominal_stress_stretch",
                "runs": [[r1["id"], "v1"], [r2["id"], "v2"]],
            },
        )
    )
    a = spec["panels"][0]
    a["series"][0] |= {"kind": "line+markers", "marker": "circle"}
    a["series"][1] |= {"line_style": "dash"}
    a["x"] |= {"min": 1.0, "max": 3.0}
    b = {
        **a,
        "id": "b",
        "series": [a["series"][0] | {"kind": "line"}],
        "legend": a["legend"] | {"show": False},
    }
    spec["panels"] = [a, b]
    spec["layout"] |= {"cols": 2}
    job = ok(c.post("/api/origin/plot-jobs", json={"spec": spec, "name": "Fig 3.2"}))
    assert _wait(c, job)["status"] == "done"
    sent = PlotJob.model_validate(SUBMITTED[-1])
    assert sent.file_stem.startswith("Fig-3.2_")
    assert [bk.name for bk in sent.books] == ["DataA", "DataB", "Metadata"]
    ga, gb = sent.graphs
    assert (ga.name, ga.template, gb.template) == ("FigA", "pm_thesis_linesymb", "pm_thesis_line")
    assert [p.color for p in ga.plots] == ["#317CB7", "#DC6D57"]  # thesis palette, 2 series
    assert [p.kind for p in ga.plots] == ["linesymbol", "line"]
    assert ga.plots[0].symbol == "circle" and ga.plots[1].line_style == "dash"
    assert (ga.x.min, ga.x.max) == (1.0, 3.0) and ga.legend and not gb.legend
    cols = sent.books[0].sheets[0].columns
    assert [cl.designation for cl in cols] == ["X", "Y", "X", "Y"]
    assert cols[1].units == "MPa"
    assert len(cols[0].values) == r1["curves_total_points"]["stretch"]  # not the preview's LTTB
    assert max(v for v in cols[1].values if v is not None) == pytest.approx(
        r1["result"]["max_stress_pa"] / 1e6
    )  # type: ignore[type-var]
    meta = dict(
        zip(
            sent.books[2].sheets[0].columns[0].values,
            sent.books[2].sheets[0].columns[1].values,
            strict=True,
        )
    )
    assert f"#{r1['id']}" in meta["source_runs"] and f"#{r2['id']}" in meta["source_runs"]
    assert not any(cl.comments for cl in cols)  # Origin's legend would show comments
    assert f"#{r1['id']}" in meta[f"(a) {a['series'][0]['name']}"]  # per-series source


def test_plot_job_without_visible_series_is_refused(apps: tuple[TestClient, TestClient]) -> None:
    c, _ = apps
    run = _uniaxial_run(c)
    spec = ok(
        c.post(
            "/api/plots/spec",
            json={"template_id": "nominal_stress_stretch", "runs": [[run["id"], "v1"]]},
        )
    )
    spec["panels"][0]["series"][0]["visible"] = False
    r = c.post("/api/origin/plot-jobs", json={"spec": spec})
    assert r.status_code == 422 and "可见" in r.json()["detail"]


def test_unreachable_bridge_is_clear_and_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLYMECH_NO_KEYCHAIN", "1")
    with TestClient(create_app(Settings(data_dir=tmp_path / "d"))) as c:
        c.app.state.polymech.local_origin = None  # type: ignore[attr-defined]  # remote failure mode
        st = ok(c.get("/api/origin/status"))
        assert st["reachable"] is False
        assert "地址" in st["error"]
        ok(c.put("/api/settings", json={"bridge_url": "http://127.0.0.1:9", "bridge_timeout_s": 2}))
        st = ok(c.get("/api/origin/status"))
        assert st["reachable"] is False
        assert "无法连接" in st["error"]
        run = _uniaxial_run(c)  # the rest of the app is unaffected
        r = c.post(
            "/api/origin/jobs", json={"run_id": run["id"], "template_id": "nominal_stress_stretch"}
        )
        assert r.status_code == 503
        assert "防火墙" in r.json()["detail"]


def test_local_origin_unavailable_keeps_analysis_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polymech_api.services import local_origin

    monkeypatch.setattr(
        local_origin,
        "detect_origin",
        lambda: {
            "installed": False,
            "error": "未检测到本机 Origin",
        },
    )
    with TestClient(create_app(Settings(data_dir=tmp_path / "data"))) as c:
        c.app.state.polymech.local_origin = local_origin.LocalOriginManager(
            tmp_path / "missing.exe"
        )  # type: ignore[attr-defined]
        status = ok(c.get("/api/origin/status"))
        assert status["mode"] == "local" and not status["reachable"]
        assert status["vms"] == [] and status["token_configured"] is False
        assert "未检测到本机 Origin" in status["error"]
        run = _uniaxial_run(c)
        assert run["status"] != "failed"
        spec = ok(
            c.post(
                "/api/plots/spec",
                json={
                    "template_id": "nominal_stress_stretch",
                    "runs": [[run["id"], "SYNTHETIC"]],
                },
            )
        )
        exported = c.post("/api/plots/export", json={"spec": spec, "format": "png"})
        assert exported.status_code == 200 and exported.content.startswith(b"\x89PNG")


@pytest.mark.parametrize("local", [False, True])
def test_origin_connection_errors_describe_the_selected_mode(local: bool) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SYNTHETIC timeout", request=request)

    client = BridgeClient(
        "http://bridge.test",
        TOKEN,
        local=local,
        factory=lambda base_url, timeout_s: httpx.Client(
            base_url=base_url, timeout=timeout_s, transport=httpx.MockTransport(timeout)
        ),
    )
    try:
        with pytest.raises(OriginUnavailableError) as error:
            client.health()
        assert ("本机 Origin" if local else "虚拟机") in str(error.value)
        if local:
            assert "虚拟机" not in str(error.value)
    finally:
        client.http.close()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_restart_finishes_only_ephemeral_local_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    from polymech_database.models import OriginJob

    monkeypatch.setattr(sys, "platform", platform)
    cfg = Settings(data_dir=tmp_path / "data")
    with (
        TestClient(create_app(cfg)) as c,
        c.app.state.polymech.db.session() as session,  # type: ignore[attr-defined]
    ):
        for status in ("queued", "running", "done"):
            session.add(OriginJob(template_id="line", bridge_job_id=status, status=status))
    with TestClient(create_app(cfg)) as c:
        jobs = {job["id"]: job for job in ok(c.get("/api/origin/jobs"))}
        assert jobs[3]["status"] == "done"
        for job_id, previous in ((1, "queued"), (2, "running")):
            job = jobs[job_id]
            assert job["status"] == ("failed" if platform == "win32" else previous)
            if platform == "win32":
                assert "重新导出" in job["error"] and job["finished_at"]
