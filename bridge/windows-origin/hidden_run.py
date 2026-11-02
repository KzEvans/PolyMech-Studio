"""pythonw entry point: run argv[2:] with no console window, log output to argv[1].

Exit code is written to "<log>.rc" last, which the caller polls for completion.
"""

import os
import subprocess
import sys

log, cmd = sys.argv[1], sys.argv[2:]
with open(log, "wb") as f:
    try:
        rc = subprocess.run(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            # Windows defaults redirected stdout to the ANSI code page (GBK); force UTF-8
            env=os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        ).returncode
    except OSError as e:
        f.write(f"hidden_run: {e}\n".encode())
        rc = 127
with open(log + ".rc", "w") as f:
    f.write(str(rc))
