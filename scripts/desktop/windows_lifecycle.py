"""Verify cancellation, failed jobs, and shell-crash cleanup with real Windows Origin.

Run in the logged-in Windows session against the installed SYNTHETIC test build.
Only the shell and Bridge processes launched here are stopped by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--exe", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "bridge/windows-origin"))
from polymech_bridge.worker import automation_instances, kill_pid, origin_pids  # noqa: E402

args.work.mkdir(parents=True, exist_ok=False)
summary: dict[str, Any] = {}
flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
bridge = args.exe.parent / "bridge/polymech-bridge.exe"
before = origin_pids()


def wait_until(check: Any, timeout: float = 120) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.5)
    raise TimeoutError("Windows lifecycle condition did not complete")


def process_rows() -> list[dict[str, Any]]:
    command = (
        "@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in "
        "@('polymech-studio.exe','polymech-backend.exe','polymech-bridge.exe')} | "
        "Select-Object Name,ProcessId,ParentProcessId) | ConvertTo-Json -Compress"
    )
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
        creationflags=flags,
    ).stdout.strip()
    rows = json.loads(out) if out else []
    return [rows] if isinstance(rows, dict) else rows


if process_rows():
    raise SystemExit("Close other PolyMech desktop test processes first.")

# Interrupt only the verified automation instance created for this synthetic job.
job = {
    "file_stem": "SYNTHETIC_lifecycle",
    "books": [
        {
            "name": "Data",
            "long_name": "SYNTHETIC",
            "sheets": [
                {
                    "name": "Data",
                    "columns": [
                        {"long_name": "x", "designation": "X", "values": [1, 2, 3]},
                        {"long_name": "y", "values": [0, 1, 2]},
                    ],
                }
            ],
        }
    ],
    "graphs": [
        {
            "name": "Graph",
            "long_name": "SYNTHETIC",
            "template": "line",
            "x": {"title": "x"},
            "y": {"title": "y"},
            "plots": [{"book": "Data", "x": 0, "y": 1}],
        }
    ],
    "exports": [],
}
token = secrets.token_urlsafe(32)
with (args.work / "bridge.log").open("w", encoding="utf-8") as log:
    process = subprocess.Popen(
        [str(bridge), "--work-root", str(args.work / "jobs"), "--parent-pid", str(os.getpid())],
        env=os.environ | {"POLYMECH_LOCAL_TOKEN": token},
        stdout=subprocess.PIPE,
        stderr=log,
        text=True,
        encoding="utf-8",
        creationflags=flags,
    )
    ports: queue.Queue[str] = queue.Queue()

    def read_port() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            if line.startswith("POLYMECH_BRIDGE_PORT="):
                ports.put(line.strip().split("=", 1)[1])
        ports.put("")

    threading.Thread(target=read_port, daemon=True).start()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{int(ports.get(timeout=60))}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
        trust_env=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    )
    try:
        starting_instances = automation_instances()
        response = client.post("/v1/plot-jobs", json=job)
        response.raise_for_status()
        jid = response.json()["id"]
        failed_instances = wait_until(
            lambda: {
                pid: created
                for pid, created in automation_instances().items()
                if pid not in starting_instances
            },
            180,
        )
        time.sleep(1)
        for pid, created in failed_instances.items():
            kill_pid(pid, created)

        def terminal() -> dict[str, Any] | None:
            response = client.get(f"/v1/plot-jobs/{jid}")
            response.raise_for_status()
            state = response.json()
            return state if state["status"] in ("done", "failed", "cancelled") else None

        failed = wait_until(terminal, 240)
        assert failed["status"] == "failed" and failed["error"], failed
        wait_until(lambda: origin_pids() == before)
        summary["failed_job"] = failed
        summary["failure_origin_pids"] = sorted(failed_instances)
        print("REAL_ORIGIN_FAILURE_CLEANUP_PASSED", flush=True)

        for column in job["books"][0]["sheets"][0]["columns"]:
            column["values"] = list(range(100_000))
        start = automation_instances()
        response = client.post("/v1/plot-jobs", json=job)
        response.raise_for_status()
        jid = response.json()["id"]
        started = wait_until(lambda: automation_instances().keys() - start.keys(), 180)
        # The worker observer records PID + creation time before it can terminate the instance.
        time.sleep(1)
        response = client.post(f"/v1/plot-jobs/{jid}/cancel")
        response.raise_for_status()
        cancelled = wait_until(terminal, 180)
        assert cancelled["status"] == "cancelled", cancelled
        wait_until(lambda: origin_pids() == before)
        summary["cancelled_job"] = cancelled
        summary["cancelled_origin_pids"] = sorted(started)
        print("REAL_ORIGIN_CANCEL_CLEANUP_PASSED", flush=True)
    finally:
        if process.poll() is None:
            client.post("/v1/shutdown")
            process.wait(timeout=100)
        client.close()

# Kill the owned desktop shell while its own real Origin job is starting.
log_path = Path(os.environ["LOCALAPPDATA"]) / "PolyMechStudio/logs/backend.log"
log_path.write_text("", encoding="utf-8")
env = os.environ | {
    "POLYMECH_DATA_DIR": str(args.work / "desktop-data"),
    "POLYMECH_DOWNLOAD_DIR": str(args.work / "downloads"),
    "POLYMECH_NO_KEYCHAIN": "1",
    "HTTP_PROXY": "http://127.0.0.1:9",
    "HTTPS_PROXY": "http://127.0.0.1:9",
}
process = subprocess.Popen([str(args.exe)], env=env, creationflags=flags)
try:

    def backend_port() -> str | None:
        matches = re.findall(
            r"on 127\.0\.0\.1:(\d+)", log_path.read_text("utf-8", errors="replace")
        )
        return matches[-1] if matches else None

    port = wait_until(backend_port)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False) as client:
        name = "SYNTH_uniaxial_gbk_chinese.csv"
        response = client.post(
            "/api/imports", files={"files": (name, (root / "fixtures/import" / name).read_bytes())}
        )
        response.raise_for_status()
        raw_id = response.json()["files"][0]["raw_file_id"]
        response = client.post(
            "/api/experiments",
            json={
                "raw_file_id": raw_id,
                "material_name": "SYNTHETIC 生命周期",
                "specimen_label": "TEST",
                "test_type": "uniaxial",
                "thickness_m": 0.001,
                "width_m": 0.002,
                "gauge_length_m": 0.02,
                "mappings": [
                    {"column_index": i, "quantity": q, "unit": u}
                    for i, (q, u) in enumerate(
                        [("time", "s"), ("force", "N"), ("displacement", "mm")]
                    )
                ],
            },
        )
        response.raise_for_status()
        experiment = response.json()["id"]
        response = client.post(f"/api/experiments/{experiment}/analyses/uniaxial", json={})
        response.raise_for_status()
        run_id = response.json()["id"]
        response = client.post(
            "/api/origin/jobs",
            json={
                "run_id": run_id,
                "template_id": "nominal_stress_stretch",
                "exports": ["png"],
            },
        )
        response.raise_for_status()
        summary["interrupted_job_id"] = response.json()["id"]
        started = wait_until(lambda: origin_pids() - before, 180)
        time.sleep(1)
        owned = process_rows()
        process.kill()
        process.wait(timeout=10)
        wait_until(lambda: not process_rows(), 150)
        wait_until(lambda: origin_pids() == before, 150)
        summary["crash_owned_processes"] = owned
        summary["crash_origin_pids"] = sorted(started)
        summary["shell_crash_cleanup"] = True
        print("SHELL_CRASH_WITH_ACTIVE_ORIGIN_CLEANUP_PASSED", flush=True)
    log_path.write_text("", encoding="utf-8")
    process = subprocess.Popen([str(args.exe)], env=env, creationflags=flags)
    port = wait_until(backend_port)
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120, trust_env=False) as client:
        response = client.get(f"/api/origin/jobs/{summary['interrupted_job_id']}")
        response.raise_for_status()
        interrupted = response.json()
        assert interrupted["status"] == "failed" and "重新导出" in interrupted["error"], interrupted
        summary["restart_job_recovery"] = interrupted
    process.kill()
    process.wait(timeout=10)
    wait_until(lambda: not process_rows())
    wait_until(lambda: origin_pids() == before)
    print("INTERRUPTED_ORIGIN_JOB_RECOVERY_PASSED", flush=True)
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    summary["origin_before"] = sorted(before)
    summary["origin_after"] = sorted(origin_pids())
    (args.work / "lifecycle.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if log_path.exists():
        (args.work / "desktop-backend.log").write_bytes(log_path.read_bytes())
print("WINDOWS_LIFECYCLE_PASSED")
