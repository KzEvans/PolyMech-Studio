"""List visible top-level windows in this session with owning process (diagnostic, read-only)."""

import json

import win32api
import win32con
import win32gui
import win32process


def exe_of(pid):
    try:
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        return win32process.GetModuleFileNameEx(h, 0)
    except Exception as e:
        return f"<{e.__class__.__name__}>"


rows = []


def cb(h, _):
    if win32gui.IsWindowVisible(h) and not win32gui.GetParent(h):
        _tid, pid = win32process.GetWindowThreadProcessId(h)
        rows.append(
            {
                "hwnd": h,
                "pid": pid,
                "exe": exe_of(pid).split("\\")[-1],
                "class": win32gui.GetClassName(h),
                "title": win32gui.GetWindowText(h)[:80],
            }
        )


win32gui.EnumWindows(cb, None)
for r in rows:
    if r["title"] or r["class"] not in ("Shell_TrayWnd",):
        print(json.dumps(r, ensure_ascii=False))
