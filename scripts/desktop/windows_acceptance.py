"""Exercise frozen Windows programs using isolated SYNTHETIC data and real Origin exports."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--backend", type=Path, required=True)
parser.add_argument("--bridge", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--origin", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
if (args.work / "data" / "polymech.sqlite").exists():
    raise SystemExit("Choose a fresh SYNTHETIC work directory.")
args.work.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / "bridge/windows-origin"))
from polymech_bridge.worker import origin_pids  # noqa: E402

before = origin_pids()
owned: set[int] = set()
env = os.environ | {
    "POLYMECH_DATA_DIR": str(args.work / "data"),
    "POLYMECH_NO_KEYCHAIN": "1",
    "POLYMECH_LOCAL_BRIDGE_EXE": str(args.bridge),
    "PYTHONUTF8": "1",
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
    "NO_PROXY": "127.0.0.1,localhost",
}
backend_log = (args.work / "backend.log").open("w", encoding="utf-8")
process = subprocess.Popen(
    [str(args.backend), "--static", str(root / "apps/web/dist"), "--control-stdin"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=backend_log,
    env=env,
    text=True,
    encoding="utf-8",
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)
ports: queue.Queue[str] = queue.Queue()


def read_port() -> None:
    assert process.stdout is not None
    for line in process.stdout:
        if line.startswith("POLYMECH_PORT="):
            ports.put(line.strip().split("=", 1)[1])
    ports.put("")


threading.Thread(target=read_port, daemon=True).start()
summary: dict = {"existing_origin_pids": sorted(before)}
try:
    port = int(ports.get(timeout=90))
    base = f"http://127.0.0.1:{port}"
    print(f"Frozen backend ready on loopback port {port}", flush=True)
    with (args.work / "smoke.log").open("w", encoding="utf-8") as log:
        subprocess.run(
            [sys.executable, str(root / "scripts/desktop/smoke.py"), base],
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:

        def ok(response: httpx.Response) -> dict:
            if response.is_error:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
            return response.json()

        analyses = {
            method: ok(client.get(f"/api/analyses/{rid}"))
            for method, rid in (("uniaxial", 1), ("dma", 2))
        }
        (args.work / "numeric-results.json").write_text(
            json.dumps(analyses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        spec = ok(
            client.post(
                "/api/plots/spec",
                json={"template_id": "nominal_stress_stretch", "runs": [[1, "SYNTHETIC 实验"]]},
            )
        )
        for format_ in ("png", "svg", "pdf"):
            response = client.post("/api/plots/export", json={"spec": spec, "format": format_})
            response.raise_for_status()
            (args.work / f"matplotlib.{format_}").write_bytes(response.content)
        with Image.open(args.work / "matplotlib.png") as image:
            assert image.size == (3216, 2280), image.size
            summary["matplotlib_png_size"] = image.size
        if args.origin:
            status = ok(client.get("/api/origin/status"))
            assert status["mode"] == "local" and status["reachable"], status
            assert status["capabilities"]["originpro_importable"], status
            (args.work / "origin-status.json").write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            requests = [
                (
                    "analysis",
                    "/api/origin/jobs",
                    {
                        "run_id": 1,
                        "template_id": "nominal_stress_stretch",
                        "exports": ["png", "pdf"],
                    },
                ),
                (
                    "plot-studio",
                    "/api/origin/plot-jobs",
                    {"spec": spec, "name": "SYNTHETIC 工作室", "exports": ["png", "pdf"]},
                ),
            ]
            for label, endpoint, body in requests:
                job = ok(client.post(endpoint, json=body))
                deadline = time.monotonic() + 300
                while job["status"] in ("queued", "running") and time.monotonic() < deadline:
                    time.sleep(1)
                    response = client.get(f"/api/origin/jobs/{job['id']}")
                    if response.status_code == 503:
                        print(f"Origin poll temporarily unavailable: {response.text}", flush=True)
                        continue
                    job = ok(response)
                folder = args.work / label
                folder.mkdir()
                (folder / "job.json").write_text(
                    json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                owned.update(job.get("verification", {}).get("origin", {}).get("owned_pids", []))
                for name in job.get("files", []):
                    response = client.get(f"/api/origin/jobs/{job['id']}/files/{name}")
                    response.raise_for_status()
                    (folder / name).write_bytes(response.content)
                assert job["status"] == "done" and job["verification"]["passed"], job
                for png in folder.glob("*.png"):
                    with Image.open(png) as image:
                        assert image.size == (3216, 2280), (png.name, image.size)
                summary[label] = {"job_id": job["id"], "verification_passed": True}
                print(f"Real Origin {label} export and reopen verification passed", flush=True)
finally:
    if process.poll() is None:
        assert process.stdin is not None
        process.stdin.write("shutdown\n")
        process.stdin.flush()
        process.stdin.close()
        try:
            process.wait(timeout=100)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
            raise
    backend_log.close()
    after = origin_pids()
    summary["origin_pids_after_exit"] = sorted(after)
    summary["owned_origin_pids"] = sorted(owned)
    summary["new_origin_remaining"] = sorted(after - before)
    summary["owned_origin_gone"] = not bool(owned & after)
    summary["existing_origin_preserved"] = before <= after
    (args.work / "acceptance.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert before <= after and not (owned & after), summary
print(f"FROZEN_WINDOWS_ACCEPTANCE_PASSED {args.work}")
