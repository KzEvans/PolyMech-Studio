"""Real-Origin self-test of the bridge inside the VM (no network exposure):
start the bridge on 127.0.0.1, submit a SYNTHETIC uniaxial job over HTTP, wait, print result.

Run (hidden, in the user's session):  scripts/vm/run_user.sh -t 600 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\bridge_selftest.py'
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import uvicorn
from polymech_bridge.server import create_app

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "selftest-" + str(int(time.time()))
PORT = 18766


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main() -> int:
    app = create_app(TOKEN, ROOT / "selftest-jobs")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_config=None))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            call("GET", "/v1/templates")
            break
        except Exception:
            time.sleep(0.2)
    lam = np.linspace(1, 4, 300)
    sig = 0.4 * (lam - lam**-2)  # MPa, synthetic neo-Hookean
    job = {
        "file_stem": "SYNTH-SELFTEST_uniaxial_v1",
        "books": [
            {
                "name": "RawData",
                "long_name": "Raw Data (SYNTHETIC)",
                "sheets": [
                    {
                        "name": "Raw",
                        "columns": [
                            {
                                "long_name": "Stretch",
                                "units": "",
                                "designation": "X",
                                "values": lam.tolist(),
                            },
                            {"long_name": "Nominal stress", "units": "MPa", "values": sig.tolist()},
                        ],
                    }
                ],
            },
            {
                "name": "Processed",
                "long_name": "Processed Data",
                "sheets": [
                    {
                        "name": "Curves",
                        "columns": [
                            {"long_name": "Stretch", "designation": "X", "values": lam.tolist()},
                            {
                                "long_name": "True stress",
                                "units": "MPa",
                                "values": (lam * sig).tolist(),
                            },
                        ],
                    }
                ],
            },
            {
                "name": "Summary",
                "long_name": "Summary",
                "sheets": [
                    {
                        "name": "Results",
                        "columns": [
                            {"long_name": "Quantity", "designation": "L", "values": ["E", "σ_max"]},
                            {"long_name": "Value", "values": [1.2, float(sig.max())]},
                            {"long_name": "Unit", "designation": "L", "values": ["MPa", "MPa"]},
                        ],
                    }
                ],
            },
            {
                "name": "Metadata",
                "long_name": "Metadata",
                "sheets": [
                    {
                        "name": "Meta",
                        "columns": [
                            {
                                "long_name": "Key",
                                "designation": "L",
                                "values": ["data_origin", "software"],
                            },
                            {
                                "long_name": "Value",
                                "designation": "L",
                                "values": ["SYNTHETIC selftest", "PolyMech Studio"],
                            },
                        ],
                    }
                ],
            },
        ],
        "graphs": [
            {
                "name": "GStress",
                "long_name": "Nominal stress vs stretch",
                "template": "pm_line",
                "x": {"title": "Stretch λ"},
                "y": {"title": "Nominal stress (MPa)"},
                "plots": [
                    {"book": "RawData", "x": 0, "y": 1, "color": "#0072B2", "line_width_pt": 1.5},
                    {
                        "book": "Processed",
                        "x": 0,
                        "y": 1,
                        "kind": "linesymbol",
                        "color": "#D55E00",
                        "symbol": "circle",
                        "symbol_size": 4,
                    },
                ],
            },
            {  # registered double-Y .otpu (mode A)
                "name": "GDouble",
                "long_name": "Stress and true stress (double Y)",
                "template": "pm_doubley",
                "x": {"title": "Stretch λ"},
                "y": {"title": "Nominal stress (MPa)"},
                "y2": {"title": "True stress (MPa)"},
                "plots": [
                    {"book": "RawData", "x": 0, "y": 1, "color": "#0072B2"},
                    {"book": "Processed", "x": 0, "y": 1, "axis": "y2", "color": "#D55E00"},
                ],
            },
            {  # unregistered id → built-in base + programmatic journal style (mode B)
                "name": "GFallback",
                "long_name": "Fallback template check",
                "template": "pm_not_installed",
                "x": {"title": "Stretch λ"},
                "y": {"title": "Nominal stress (MPa)"},
                "plots": [{"book": "RawData", "x": 0, "y": 1, "color": "#009E73"}],
            },
        ],
        "exports": ["png", "pdf", "svg"],
        "image_width_px": 1600,
    }
    t0 = time.time()
    st = call("POST", "/v1/plot-jobs", job)
    while st["status"] in ("queued", "running"):
        time.sleep(1)
        st = call("GET", f"/v1/plot-jobs/{st['id']}")
    st["elapsed_s"] = round(time.time() - t0, 1)
    st["capabilities"] = call("GET", "/v1/capabilities")
    server.should_exit = True
    time.sleep(1)
    app.state.worker.stop()
    app.state.worker.join(timeout=60)
    st["owned_after_shutdown"] = sorted(app.state.worker.owned)
    print(json.dumps(st, ensure_ascii=False))
    return 0 if st["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
