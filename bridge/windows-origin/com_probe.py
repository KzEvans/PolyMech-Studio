"""Diagnose Origin COM activation from the bridge venv (new instance only, never attach)."""
import json, subprocess, sys, threading, time, traceback, winreg

def reg(root, path, name=""):
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError as e:
        return f"<{e.__class__.__name__}>"

def origin_pids():
    out = subprocess.run(["tasklist", "/fi", "imagename eq Origin64.exe", "/fo", "csv", "/nh"],
                         capture_output=True, text=True, errors="replace",
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return {int(p.split('","')[1]) for p in out.splitlines() if '","' in p}

r = {}
for prog in ("Origin.Application", "Origin.ApplicationSI"):
    clsid = reg(winreg.HKEY_CLASSES_ROOT, rf"{prog}\CLSID")
    r[prog] = {"clsid": clsid,
               "LocalServer32(HKCR)": reg(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32"),
               "LocalServer32(HKCU)": reg(winreg.HKEY_CURRENT_USER, rf"Software\Classes\CLSID\{clsid}\LocalServer32"),
               "LocalServer32(HKLM)": reg(winreg.HKEY_LOCAL_MACHINE, rf"Software\Classes\CLSID\{clsid}\LocalServer32"),
               "AppID": reg(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}", "AppID")}

before = origin_pids()
seen = set()
windows = {}
stop = False
def watch():
    import win32gui, win32process
    while not stop:
        new = origin_pids() - before
        seen.update(new)
        def cb(h, _):
            _, pid = win32process.GetWindowThreadProcessId(h)
            if pid in new:
                key = (pid, win32gui.GetClassName(h), win32gui.GetWindowText(h))
                entry = windows.setdefault(str(key), {"visible": bool(win32gui.IsWindowVisible(h)),
                                                      "t": round(time.perf_counter() - t0, 1)})
                if key[1] == "#32770" and "children" not in entry:
                    kids = []
                    win32gui.EnumChildWindows(
                        h, lambda c, acc: acc.append((win32gui.GetClassName(c), win32gui.GetWindowText(c))), kids)
                    entry["children"] = kids
        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            pass
        time.sleep(1)
t0 = time.perf_counter()
threading.Thread(target=watch, daemon=True).start()

import pythoncom, win32com.client
pythoncom.CoInitialize()
t0 = time.perf_counter()
app = None
try:
    app = win32com.client.DispatchEx("Origin.Application")
    r["dispatch_s"] = round(time.perf_counter() - t0, 1)
    r["version"] = app.LTVar("@V")
    r["visible_var"] = app.LTVar("@VIS")
except Exception:
    r["dispatch_error"] = traceback.format_exc(limit=3)
    r["dispatch_s"] = round(time.perf_counter() - t0, 1)
finally:
    r["spawned_pids"] = sorted(seen | (origin_pids() - before))
    if app is not None:
        try:
            app.Exit()
        except Exception:
            r["exit_error"] = traceback.format_exc(limit=2)
    app = None
    time.sleep(4); stop = True
    r["leftover_pids"] = sorted(origin_pids() - before)
    r["windows"] = windows
print(json.dumps(r, ensure_ascii=False, indent=1))
