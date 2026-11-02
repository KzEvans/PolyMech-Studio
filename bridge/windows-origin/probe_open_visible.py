"""Open an OPJU in a NEW, visible Origin instance (as a user would) and report each window's
state: page.win (0 hidden … 3 normal, 4 maximized) and is_open(). In a hidden instance every
page reads as hidden, so only a visible instance tells what the user will see. Waits a few
seconds so the desktop can be captured (prlctl capture), then closes only its own instance.

Run:  scripts/vm/run_user.sh -t 300 '%BRIDGE%\\venv\\Scripts\\python.exe' '%BRIDGE%\\app\\probe_open_visible.py' <opju> [hold_s]
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from polymech_bridge.worker import kill_pid, origin_pids


def main() -> int:
    opju = Path(sys.argv[1])
    hold = float(sys.argv[2]) if len(sys.argv) > 2 else 8
    rep: dict[str, object] = {"opju": str(opju)}
    before = origin_pids()
    import originpro as op

    op.set_show(True)
    owned = origin_pids() - before
    try:
        rep["opened"] = bool(op.open(file=str(opju), readonly=True))
        pages = {}
        for kind in ("w", "g"):
            for p in op.pages(kind):
                st: dict[str, object] = {"kind": kind}
                with contextlib.suppress(Exception):
                    st["is_open"] = p.is_open()
                with contextlib.suppress(Exception):
                    st["page.win"] = float(op.lt_float(f"{p.name}!page.win"))
                pages[p.name] = st
        rep["pages"] = pages
        print("READY_FOR_CAPTURE", flush=True)
        time.sleep(hold)
    finally:
        with contextlib.suppress(Exception):
            op.exit()
        time.sleep(3)
        for pid in owned & origin_pids():
            kill_pid(pid)
        rep["owned_left"] = sorted(owned & origin_pids())
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
