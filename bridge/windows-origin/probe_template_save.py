"""Probe: which LabTalk command saves the active graph as a .otpu in this Origin version?

Starts its own hidden Origin (never attaches to the user's), plots SYNTHETIC data, tries
candidate commands, checks for the file, reloads it with op.new_graph(template=path),
then closes only the instance it started. Prints a JSON report.

Run:  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\probe_template_save.py'
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.worker import kill_pid, origin_pids

OUT = Path(__file__).resolve().parents[1] / "stage" / "tplprobe"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*"):
        f.unlink()
    report: dict[str, object] = {"out_dir": str(OUT), "candidates": []}
    before = origin_pids()
    import originpro as op

    op.set_show(False)
    owned = origin_pids() - before
    report["origin_version"] = op.lt_float("@V")
    report["owned_pids"] = sorted(owned)
    try:
        op.new()
        wks = op.new_sheet()
        wks.from_list(0, [1.0, 1.5, 2.0, 2.5, 3.0], lname="Stretch", axis="X")
        wks.from_list(1, [0.0, 0.3, 0.55, 0.8, 1.0], lname="Stress", units="MPa")
        gp = op.new_graph(template="line")
        gp.name = "TplProbe"
        gp[0].add_plot(wks, coly=1, colx=0, type="l")
        gp[0].rescale()
        gp.activate()
        report["uff"] = op.path("u")
        target = str(OUT)
        cands = [
            ("xf_page_name_filepath", f'template_saveas pg:=[TplProbe] template:="PM_probe1" filepath:="{target}";'),
            ("xf_page_name_filepath_slash", f'template_saveas pg:=[TplProbe] template:="PM_probe2" filepath:="{target}\\";'),
            ("xf_category", f'template_saveas pg:=[TplProbe] category:="PolyMech" template:="PM_probe3" filepath:="{target}";'),
        ]
        for label, cmd in cands:
            gp.activate()
            t0 = time.time()
            try:
                ok = op.lt_exec(cmd)
                err = ""
            except Exception as e:  # noqa: BLE001 - probe records everything
                ok, err = False, repr(e)
            files = sorted(p.name for p in OUT.iterdir())
            report["candidates"].append(  # type: ignore[union-attr]
                {"label": label, "cmd": cmd, "lt_ok": ok, "error": err, "files_after": files, "s": round(time.time() - t0, 2)}
            )
        uff = Path(op.path("u"))
        report["uff_probe_files"] = sorted(p.name for p in uff.glob("PM_probe*"))
        reload = {}
        for f in sorted(OUT.glob("*.otp*")):
            try:
                g = op.new_graph(template=str(f))
                reload[f.name] = {"ok": g is not None, "layers": len(g) if g is not None else 0}
            except Exception as e:  # noqa: BLE001
                reload[f.name] = {"ok": False, "error": repr(e)}
        report["reload"] = reload
    finally:
        with contextlib.suppress(Exception):
            op.exit()
        time.sleep(3)
        for pid in owned & origin_pids():
            kill_pid(pid)
        report["owned_left"] = sorted(owned & origin_pids())
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
