"""SPEC §6.7 ten-step end-to-end acceptance against the REAL Origin in the Parallels VM.

Prerequisites: API running (POLYMECH_DATA_DIR=<dir> uvicorn polymech_api.main:app --port 8765),
bridge paired (POST /api/origin/pair). Writes reports/data/origin/e2e_<date>[_runN]/report.json and
copies of the Origin output.

Run:  uv run python scripts/acceptance_origin_e2e.py <data_dir>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8765"
FIX = ROOT / "fixtures" / "import"
NAME = "SYNTH_uniaxial_gbk_chinese.csv"


def ok(r: httpx.Response) -> dict:
    r.raise_for_status()
    return r.json()


def main(data_dir: Path) -> int:
    c = httpx.Client(base_url=API, timeout=120)
    steps: list[dict] = []
    t_all = time.perf_counter()

    def step(n: int, title: str, **info: object) -> None:
        steps.append({"step": n, "title": title, **info})
        print(f"[{n:2d}] {title}: {json.dumps(info, ensure_ascii=False)[:200]}", flush=True)

    manifest = {
        e["file"]: e for e in json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
    }
    t0 = time.perf_counter()
    up = ok(c.post("/api/imports", files=[("files", (NAME, (FIX / NAME).read_bytes()))]))["files"][
        0
    ]
    table = up["tables"][0]
    step(
        1,
        "macOS 上传单轴拉伸数据文件",
        file=NAME,
        sha256=up["sha256"],
        rows=table["n_rows"],
        suggested=[s["quantity"] for s in table["suggestions"]],
        elapsed_s=round(time.perf_counter() - t0, 2),
    )

    truth = manifest[NAME]
    mappings = [
        {"column_index": col["index"], **truth["columns"][col["header"]]}
        for col in table["columns"]
    ]
    exp = ok(
        c.post(
            "/api/experiments",
            json={
                "raw_file_id": up["raw_file_id"],
                "mappings": mappings,
                "material_name": "SYN-E2E",
                "specimen_label": "E2E-U1",
                "test_type": "uniaxial",
                **truth["metadata"],
            },
        )
    )
    t0 = time.perf_counter()
    run = ok(
        c.post(f"/api/experiments/{exp['id']}/analyses/uniaxial", json={"operator": "acceptance"})
    )
    step(
        2,
        "Python 计算引擎生成标准化曲线",
        run_id=run["id"],
        version=run["version"],
        status=run["status"],
        modulus_mpa=round(run["result"]["modulus_fit"]["slope"] / 1e6, 4),
        break_stretch=round(run["result"]["break_stretch"], 4),
        elapsed_s=round(time.perf_counter() - t0, 2),
    )

    template = "nominal_stress_stretch"
    step(3, "选择 Origin 绘图模板", template=template)

    t0 = time.perf_counter()
    job = ok(
        c.post(
            "/api/origin/jobs",
            json={"run_id": run["id"], "template_id": template, "exports": ["png", "pdf", "svg"]},
        )
    )
    step(
        4, "macOS 向 Windows Bridge 发送任务", origin_job_id=job["id"], bridge_status=job["status"]
    )

    while job["status"] in ("queued", "running"):
        time.sleep(2)
        job = ok(c.get(f"/api/origin/jobs/{job['id']}"))
    elapsed = round(time.perf_counter() - t0, 1)
    ver = job["verification"]
    step(
        5,
        "Windows Bridge 调用真实 Origin",
        status=job["status"],
        origin=ver.get("origin"),
        error=job["error"],
    )
    books = [ch for ch in ver.get("checks", []) if "book" in ch]
    graphs = [ch for ch in ver.get("checks", []) if "graph" in ch]
    step(
        6,
        "Origin 生成工作簿及图页",
        books=[b["book"] for b in books],
        graphs=[g["graph"] for g in graphs],
    )
    step(7, "保存 OPJU", opju=job["opju_file"])
    step(
        8,
        "导出预览图片",
        files=[f for f in job["files"] if f.endswith((".png", ".pdf", ".svg"))],
        export_errors=ver.get("export_errors"),
        job_elapsed_s=elapsed,
    )

    folder = data_dir / "origin" / f"job{job['id']}"
    opju = folder / job["opju_file"]
    sha_mac = hashlib.sha256(opju.read_bytes()).hexdigest()
    step(
        9,
        "macOS 接收真实 Origin 输出",
        folder=str(folder.relative_to(data_dir)),
        opju_bytes=opju.stat().st_size,
        opju_magic=opju.read_bytes()[:5].decode("latin1"),
        sha256=sha_mac,
    )

    # Step 10: push the Mac copy back and open it in a FRESH Origin instance
    vm = ROOT / "scripts" / "vm"
    remote = "%BRIDGE%\\verify\\" + opju.name
    subprocess.run([str(vm / "push_file.sh"), str(opju), remote], check=True)
    subprocess.run(
        [
            str(vm / "push_file.sh"),
            str(ROOT / "bridge/windows-origin/verify_opju.py"),
            "%BRIDGE%\\app\\verify_opju.py",
        ],
        check=True,
    )
    out = subprocess.run(
        [
            str(vm / "run_user.sh"),
            "-t",
            "300",
            "%BRIDGE%\\venv\\Scripts\\python.exe",
            "%BRIDGE%\\app\\verify_opju.py",
            remote,
        ],
        capture_output=True,
        text=True,
    )
    line = next((ln for ln in out.stdout.splitlines() if ln.startswith("{")), "{}")
    fresh = json.loads(line)
    expected_rows = table["n_rows"]
    raw = next((b for b in fresh.get("books", []) if b["name"] == "RawData"), None)
    fresh_ok = bool(
        fresh.get("opened")
        and raw
        and raw["sheets"][0]["rows"] == expected_rows
        and any(g["plots"] >= 1 for g in fresh.get("graphs", []))
        and not fresh.get("leftover_pids")
    )
    step(
        10,
        "再次在 Origin 中打开 OPJU 并检查数据和图页",
        bridge_reopen_passed=ver.get("passed"),
        fresh_instance=fresh,
        fresh_instance_passed=fresh_ok,
    )

    passed = job["status"] == "done" and ver.get("passed") and fresh_ok
    base = ROOT / "reports" / "data" / "origin" / f"e2e_{datetime.now().strftime('%Y%m%d')}"
    out_dir, k = base, 1
    while out_dir.exists():  # never overwrite an earlier acceptance record
        k += 1
        out_dir = base.with_name(f"{base.name}_run{k}")
    out_dir.mkdir(parents=True)
    for f in folder.iterdir():
        shutil.copy2(f, out_dir / f.name)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": passed,
        "total_elapsed_s": round(time.perf_counter() - t_all, 1),
        "data": "SYNTHETIC fixture " + NAME,
        "steps": steps,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("PASSED" if passed else "FAILED", out_dir.relative_to(ROOT))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
