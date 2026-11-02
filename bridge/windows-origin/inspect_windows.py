"""List top-level windows (and dialog texts) of given PIDs; optionally terminate them.
Usage: inspect_windows.py PID [PID...] [--kill]   (only ever pass PIDs this project created)"""

import json
import sys

import win32api
import win32con
import win32gui
import win32process

pids = {int(a) for a in sys.argv[1:] if a.isdigit()}
out = []


def cb(h, _):
    pid = win32process.GetWindowThreadProcessId(h)[1]
    if pid in pids:
        e = {
            "pid": pid,
            "class": win32gui.GetClassName(h),
            "title": win32gui.GetWindowText(h),
            "visible": bool(win32gui.IsWindowVisible(h)),
        }
        if e["class"] == "#32770":
            kids = []
            win32gui.EnumChildWindows(h, lambda c, a: a.append(win32gui.GetWindowText(c)), kids)
            e["children"] = kids
        if e["visible"] or e["class"] == "#32770":
            out.append(e)


win32gui.EnumWindows(cb, None)
print(json.dumps(out, ensure_ascii=False, indent=1))
if "--kill" in sys.argv:
    for pid in pids:
        h = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
        win32api.TerminateProcess(h, 1)
        print("terminated", pid)
