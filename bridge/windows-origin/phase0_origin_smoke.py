"""Phase 0 Origin minimal-chain smoke test (SPEC §6.7, §16 step 3).

Runs with the bridge venv's x64 CPython inside the logged-in Windows session.
Uses a SYNTHETIC, explicitly labelled neo-Hookean uniaxial dataset (no paper data).

Chain verified:
  1. launch a NEW Origin instance owned by this script (never attach to the user's)
  2. write Raw/Processed/Metadata worksheets
  3. create a graph page and plot nominal stress vs stretch
  4. export PNG, save OPJU
  5. exit Origin, launch a fresh instance, reopen the OPJU, check data + graph
  6. exit; confirm no Origin process created by this script is left behind

Prints one JSON report on stdout (last line).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

MU_MPA = 0.5  # synthetic shear modulus
WORK = Path(os.environ["LOCALAPPDATA"]) / "PolyMechBridge" / "work" / "phase0"
OPJU = WORK / "SYNTH-NH_uniaxial_20261025_v0.opju"
PNG = WORK / "SYNTH-NH_uniaxial_20261025_v0.png"


def origin_pids() -> set[int]:
    out = subprocess.run(
        ["tasklist", "/fi", "imagename eq Origin64.exe", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def synthetic_curve() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    stretch = np.linspace(1.0, 5.0, 401)
    nominal = MU_MPA * (stretch - stretch**-2)  # incompressible neo-Hookean, MPa
    true = stretch * nominal
    return stretch, nominal, true


def build_and_save(op, report: dict) -> None:
    stretch, nominal, true = synthetic_curve()

    raw = op.new_book("w", lname="Raw Data")
    wks = raw[0]
    wks.name = "Raw"
    wks.from_list(0, stretch.tolist(), lname="Stretch", units="1")
    wks.from_list(1, nominal.tolist(), lname="Nominal stress", units="MPa")

    proc = op.new_book("w", lname="Processed Data")
    pw = proc[0]
    pw.from_list(0, stretch.tolist(), lname="Stretch", units="1")
    pw.from_list(1, true.tolist(), lname="True stress", units="MPa")

    meta = op.new_book("w", lname="Metadata")
    mw = meta[0]
    mw.from_list(0, ["data_origin", "model", "mu_MPa"], lname="Key")
    mw.from_list(1, ["SYNTHETIC (Phase 0 smoke test)", "neo-Hookean", str(MU_MPA)], lname="Value")

    gp = op.new_graph(template="line", lname="Nominal stress vs stretch")
    gl = gp[0]
    gl.add_plot(wks, coly=1, colx=0, type="l")
    gl.rescale()
    gl.axis("x").title = "Stretch \\g(l)"
    gl.axis("y").title = "Nominal stress (MPa)"
    report["graph_name"] = gp.name

    png = gp.save_fig(str(PNG), type="png", width=1200)
    report["png_saved_path"] = png
    report["png_bytes"] = PNG.stat().st_size if PNG.exists() else None

    report["save_ok"] = bool(op.save(str(OPJU)))
    report["opju_bytes"] = OPJU.stat().st_size if OPJU.exists() else None


def reopen_and_verify(op, report: dict) -> None:
    report["open_ok"] = bool(op.open(file=str(OPJU), readonly=True))
    books = {p.lname: p for p in op.pages("w")}
    graphs = list(op.pages("g"))
    report["reopen_books"] = sorted([p.name, p.lname] for p in op.pages("w"))
    report["reopen_graphs"] = [[g.name, g.lname] for g in graphs]
    raw = books.get("Raw Data")
    if raw is None:
        report["reopen_data_ok"] = False
        return
    wks = raw[0]
    x = np.asarray(wks.to_list(0), dtype=float)
    y = np.asarray(wks.to_list(1), dtype=float)
    stretch, nominal, _ = synthetic_curve()
    report["reopen_rows"] = len(x)
    report["reopen_max_abs_err"] = (
        float(max(np.max(np.abs(x - stretch)), np.max(np.abs(y - nominal))))
        if len(x) == len(stretch)
        else None
    )
    report["reopen_data_ok"] = (
        len(x) == len(stretch)
        and report["reopen_max_abs_err"] is not None
        and report["reopen_max_abs_err"] < 1e-9
    )
    report["reopen_graph_plots"] = [len(g[0].plot_list()) for g in graphs]


def safe_exit(op, report: dict, key: str, owned: set[int]) -> None:
    """Mark the project saved, ask Origin to exit, then wait; force-kill only our own PIDs."""
    t = time.perf_counter()
    try:
        op.lt_exec("doc -s;")
        op.exit()
    except Exception:
        report[key + "_error"] = traceback.format_exc(limit=2)
    while time.perf_counter() - t < 30 and origin_pids() & owned:
        time.sleep(1)
    alive = origin_pids() & owned
    report[key] = {"graceful": not alive, "wait_s": round(time.perf_counter() - t, 1)}
    for pid in alive:
        subprocess.run(
            ["taskkill", "/pid", str(pid), "/f"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        report[key].setdefault("force_killed", []).append(pid)


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    for f in (OPJU, PNG):
        if f.exists():
            f.unlink()
    report: dict = {
        "python": sys.version,
        "machine": platform.machine(),
        "session_id": None,
        "steps": {},
    }
    try:
        import ctypes

        sid = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
        report["session_id"] = sid.value
    except Exception as e:  # diagnostic only
        report["session_id"] = f"error: {e}"

    before = origin_pids()
    report["origin_pids_before"] = sorted(before)
    import originpro as op

    t0 = time.perf_counter()
    try:
        op.set_show(False)
        report["origin_version"] = op.lt_float("@V")
        report["origin_build"] = op.get_lt_str("@B") if hasattr(op, "get_lt_str") else None
        report["steps"]["launch_s"] = round(time.perf_counter() - t0, 2)
        report["owned_pids"] = sorted(origin_pids() - before)
        t1 = time.perf_counter()
        build_and_save(op, report)
        report["steps"]["build_save_s"] = round(time.perf_counter() - t1, 2)
    except Exception:
        report["build_error"] = traceback.format_exc()
    finally:
        safe_exit(op, report, "exit1", origin_pids() - before)
    time.sleep(3)
    report["leftover_after_first_exit"] = sorted(origin_pids() - before)

    if OPJU.exists():
        t2 = time.perf_counter()
        try:
            op.set_show(False)
            reopen_and_verify(op, report)
            report["steps"]["reopen_s"] = round(time.perf_counter() - t2, 2)
        except Exception:
            report["reopen_error"] = traceback.format_exc()
        finally:
            safe_exit(op, report, "exit2", origin_pids() - before)
        time.sleep(3)
    report["leftover_after_second_exit"] = sorted(origin_pids() - before)

    report["passed"] = bool(
        report.get("save_ok")
        and report.get("png_bytes")
        and report.get("open_ok")
        and report.get("reopen_data_ok")
        and report.get("reopen_graphs")
        and not report["leftover_after_second_exit"]
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
