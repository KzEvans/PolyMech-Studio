"""Bridge HTTP/queue/schema tests. Origin itself is exercised only by the real-VM tests
(scripts/vm/bridge_selftest.sh); here an injected executor stands in for the queue logic."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from polymech_bridge import templates
from polymech_bridge.schema import PlotJob, safe_text
from polymech_bridge.server import cleanup_old_jobs, create_app
from polymech_bridge.worker import OriginWorker
from pydantic import ValidationError

TOKEN = "t" * 43
H = {"Authorization": f"Bearer {TOKEN}"}


def job(**over: Any) -> dict[str, Any]:
    base = {
        "file_stem": "SYN_uniaxial_20261025_v1",
        "books": [
            {
                "name": "RawData",
                "long_name": "Raw Data",
                "sheets": [
                    {
                        "name": "Raw",
                        "columns": [
                            {"long_name": "Stretch", "designation": "X", "values": [1.0, 1.5, 2.0]},
                            {
                                "long_name": "Nominal stress",
                                "units": "MPa",
                                "values": [0.0, 0.3, None],
                            },
                        ],
                    }
                ],
            }
        ],
        "graphs": [
            {
                "name": "Graph1",
                "long_name": "σ–λ",
                "x": {"title": "Stretch"},
                "y": {"title": "Stress (MPa)"},
                "plots": [{"book": "RawData", "x": 0, "y": 1}],
            }
        ],
    }
    return base | over


def fake_executor(st: Any) -> dict[str, Any]:
    (st.dir / f"{st.job.file_stem}.opju").write_bytes(b"not an origin file - queue test only")
    time.sleep(0.05)
    return {"made": {"opju": f"{st.job.file_stem}.opju"}, "verification": {"passed": True}}


@pytest.fixture
def client(tmp_path: Path):
    w = OriginWorker(tmp_path / "jobs", executor=fake_executor)
    with TestClient(create_app(TOKEN, tmp_path / "jobs", w)) as c:
        yield c


def wait(c: TestClient, jid: str) -> dict[str, Any]:
    for _ in range(100):
        st = c.get(f"/v1/plot-jobs/{jid}", headers=H).json()
        if st["status"] in ("done", "failed", "cancelled"):
            return st
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_health_is_public_everything_else_needs_token(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/v1/capabilities").status_code == 401
    assert (
        client.get("/v1/capabilities", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert client.get("/v1/templates", headers=H).status_code == 200


def test_job_lifecycle_and_artifact_whitelist(client: TestClient) -> None:
    st = client.post("/v1/plot-jobs", json=job(), headers=H).json()
    done = wait(client, st["id"])
    assert done["status"] == "done"
    assert "SYN_uniaxial_20261025_v1.opju" in done["artifacts"]
    r = client.get(f"/v1/plot-jobs/{st['id']}/artifacts/SYN_uniaxial_20261025_v1.opju", headers=H)
    assert r.status_code == 200
    for bad in ("..%2F..%2Ftoken.txt", "token.txt", "%2E%2E"):
        assert client.get(f"/v1/plot-jobs/{st['id']}/artifacts/{bad}", headers=H).status_code == 404
    assert client.get("/v1/plot-jobs/nope", headers=H).status_code == 404


def test_jobs_run_serially(client: TestClient) -> None:
    ids = [
        client.post("/v1/plot-jobs", json=job(file_stem=f"J{i}"), headers=H).json()["id"]
        for i in range(3)
    ]
    results = [wait(client, i) for i in ids]
    starts = [r["finished_at"] for r in results]
    assert all(r["status"] == "done" for r in results)
    assert starts == sorted(starts)


def test_body_limit(client: TestClient) -> None:
    r = client.post(
        "/v1/plot-jobs",
        content=b"x",
        headers=H | {"content-length": str(65 * 1024 * 1024), "content-type": "application/json"},
    )
    assert r.status_code == 413


@pytest.mark.parametrize(
    "over",
    [
        {"file_stem": "../evil"},
        {"file_stem": "C:\\x"},
        {"file_stem": "a b"},
        {
            "graphs": [
                {
                    "name": "G1",
                    "long_name": "x",
                    "x": {"title": "x"},
                    "y": {"title": "y"},
                    "plots": [{"book": "Nope", "x": 0, "y": 1}],
                }
            ]
        },
        {
            "graphs": [
                {
                    "name": "G1",
                    "long_name": "x",
                    "x": {"title": "x"},
                    "y": {"title": "y"},
                    "plots": [{"book": "RawData", "x": 0, "y": 9}],
                }
            ]
        },
        {
            "graphs": [
                {
                    "name": "G1",
                    "long_name": "x",
                    "x": {"title": "x"},
                    "y": {"title": "y"},
                    "plots": [{"book": "RawData", "x": 0, "y": 1, "color": "red; run -pyf evil"}],
                }
            ]
        },
        {
            "books": [
                {
                    "name": "1bad",
                    "long_name": "",
                    "sheets": [{"name": "s", "columns": [{"long_name": "a", "values": [1.0]}]}],
                }
            ]
        },
        {"script": "type -b hello"},
        {
            "graphs": [
                {
                    "name": "G1",
                    "long_name": "x",
                    "template": "..\\..\\evil.otpu",
                    "x": {"title": "x"},
                    "y": {"title": "y"},
                    "plots": [{"book": "RawData", "x": 0, "y": 1}],
                }
            ]
        },
    ],
)
def test_schema_rejects_unsafe_or_inconsistent_jobs(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlotJob.model_validate(job(**over))


def test_labtalk_text_is_sanitised() -> None:
    assert safe_text('Stress"; type -b pwn; %(x) $(y)') == "Stress type -b pwn (x) (y)"
    assert safe_text("拉伸比 λ (MPa)") == "拉伸比 λ (MPa)"


def test_cancel_queued_job(tmp_path: Path) -> None:
    w = OriginWorker(tmp_path / "jobs", executor=fake_executor)  # not started → stays queued
    st = w.submit(PlotJob.model_validate(job()))
    assert w.cancel(st.id).status == "cancelled"  # type: ignore[union-attr]


def test_cleanup_only_old_dirs_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    (root / "old").mkdir(parents=True)
    (root / "new").mkdir()
    old = time.time() - 30 * 24 * 3600
    os.utime(root / "old", (old, old))
    outside = tmp_path / "keep"
    outside.mkdir()
    os.utime(outside, (old, old))
    assert cleanup_old_jobs(root) == 1
    assert (root / "new").exists()
    assert outside.exists()


REPO_TEMPLATES = Path(__file__).resolve().parents[3] / "templates" / "origin"


def _template_dir(tmp_path: Path) -> Path:
    d = tmp_path / "templates"
    shutil.copytree(REPO_TEMPLATES, d)
    return d


def test_registry_lists_real_otpu_files_with_spec_fields() -> None:
    reg = templates.load_registry(REPO_TEMPLATES)
    kinds = ("line", "scatter", "linesymb", "doubley")
    assert set(reg) == {f"pm_{k}" for k in kinds} | {f"pm_thesis_{k}" for k in kinds}
    for k in kinds:  # thesis variants carry their style; the journal ones default to it
        assert templates.resolve(f"pm_thesis_{k}", REPO_TEMPLATES).style == "thesis"
        assert templates.resolve(f"pm_{k}", REPO_TEMPLATES).style == "journal"
    for t in reg.values():
        assert {
            "id",
            "name",
            "file",
            "chart_types",
            "min_origin_version",
            "required_columns",
            "style",
            "version",
            "sha256",
        } <= set(t)
        assert (REPO_TEMPLATES / t["file"]).stat().st_size > 1000
    assert all(t["available"] for t in templates.available(REPO_TEMPLATES))


def test_template_resolution_native_missing_tampered_unknown(tmp_path: Path) -> None:
    d = _template_dir(tmp_path)
    r = templates.resolve("pm_doubley", d)
    assert r.mode == "native" and r.template.endswith("pm_doubley.otpu") and r.base == "doubley"
    assert templates.resolve("scatter", d).mode == "builtin"
    (d / "pm_line.otpu").unlink()
    r = templates.resolve("pm_line", d)
    assert (r.mode, r.template) == ("programmatic", "line") and "缺失" in r.warning
    (d / "pm_scatter.otpu").write_bytes(b"tampered")
    r = templates.resolve("pm_scatter", d)
    assert r.mode == "programmatic" and "哈希" in r.warning
    r = templates.resolve("no_such_template", d)
    assert r.mode == "programmatic" and "未注册" in r.warning
    listed = {t["id"]: t for t in templates.available(d)}
    assert not listed["pm_line"]["available"] and listed["pm_line"]["problem"]


def test_templates_endpoint(client: TestClient) -> None:
    out = client.get("/v1/templates", headers=H).json()
    ids = {t["id"] for t in out}
    assert {"line", "doubley"} <= ids


def test_cleanup_refuses_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    from polymech_bridge import worker

    calls: list[object] = []
    monkeypatch.setattr(worker, "automation_instances", lambda: {42: "new creation time"})
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: calls.append(a))
    worker.kill_pid(42, "original creation time")
    assert calls == []


def test_origin_can_reconnect_after_its_process_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polymech_bridge import worker

    stale = object()

    class Origin:
        po = SimpleNamespace(_app=stale)
        exit_called = False

        def lt_exec(self, command: str) -> None:
            raise RuntimeError("SYNTHETIC disconnected COM pointer")

        def exit(self) -> None:
            self.exit_called = True
            raise RuntimeError("SYNTHETIC disconnected COM pointer")

        def set_show(self, visible: bool) -> None:
            assert self.po._app is None, "OriginExt would reuse the disconnected pointer"
            self.po._app = object()

        def lt_float(self, expression: str) -> float:
            return 10.25

    op = Origin()
    monkeypatch.setitem(sys.modules, "originpro", op)
    monkeypatch.setattr(worker, "automation_instances", dict)
    monkeypatch.setattr(worker, "origin_pids", set)  # tasklist exists only on Windows
    w = OriginWorker(tmp_path / "jobs")
    w._op = op
    w.close_origin()
    assert op.exit_called
    assert w._ensure_origin().po._app is not stale
