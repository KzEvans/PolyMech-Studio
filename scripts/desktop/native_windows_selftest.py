"""Exercise Windows credentials and process handles with disposable SYNTHETIC values."""

from __future__ import annotations

import json
import secrets
import struct
import subprocess
import sys
import sysconfig
import uuid

from polymech_api import native_windows

if sys.platform != "win32":
    raise SystemExit("Run this check inside Windows.")

name = "SYNTHETIC-" + uuid.uuid4().hex
value = "临时凭据-" + secrets.token_urlsafe(24)
try:
    native_windows.set_credential(name, value)
    assert native_windows.get_credential(name) == value
finally:
    native_windows.delete_credential(name)
assert native_windows.get_credential(name) is None
with subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(0.25)"],
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
) as child:
    native_windows.wait_for_process_exit(child.pid)
    assert child.wait(timeout=5) == 0
print(
    json.dumps(
        {
            "credential_roundtrip": True,
            "credential_deleted": True,
            "process_handle_wait": True,
            "python_bits": struct.calcsize("P") * 8,
            "python_platform": sysconfig.get_platform(),
        }
    )
)
