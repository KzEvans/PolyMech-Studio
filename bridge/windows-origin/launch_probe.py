"""Start a dedicated Origin64.exe (CreateProcess, not DCOM) that runs a payload script
in Origin's embedded Python; watch its windows; terminate ONLY the process we started."""
import json, os, subprocess, sys, time, win32con, win32gui, win32process
UFF_MSG = "The User Files Folder "
UFF_TAIL = "is not available currently. The path may be offline."
ORIGIN = r"C:\Program Files\OriginLab\Origin2025b\Origin64.exe"
stage = os.path.join(os.environ["LOCALAPPDATA"], "PolyMechBridge", "stage")
payload = os.path.join(stage, "embedded_probe_payload.py").replace("\\", "/")
result = os.path.join(stage, "embedded_probe.json")
if os.path.exists(result):
    os.remove(result)
args = [ORIGIN, "-h", "-rs", f'run -pyf "{payload}"; exit;']
t0 = time.perf_counter()
proc = subprocess.Popen(args)
r = {"args": args, "pid": proc.pid, "windows": {}}
while time.perf_counter() - t0 < float(sys.argv[1]):
    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == proc.pid:
            key = f"{win32gui.GetClassName(h)} | {win32gui.GetWindowText(h)}"
            e = r["windows"].setdefault(key, {"t": round(time.perf_counter() - t0, 1),
                                               "visible": bool(win32gui.IsWindowVisible(h))})
            if win32gui.GetClassName(h) == "#32770" and "children" not in e:
                kids = []
                win32gui.EnumChildWindows(h, lambda c, a: a.append(win32gui.GetWindowText(c)), kids)
                e["children"] = kids
            if (win32gui.GetClassName(h) == "#32770" and "--dismiss-uff" in sys.argv
                    and not e.get("dismissed")):
                texts, buttons = [], []
                def kid(c, _):
                    t = win32gui.GetWindowText(c)
                    (buttons if win32gui.GetClassName(c) == "Button" else texts).append((c, t))
                win32gui.EnumChildWindows(h, kid, None)
                if (len(buttons) == 1 and any(t.startswith(UFF_MSG) and t.endswith(UFF_TAIL) for _, t in texts)):
                    win32gui.SendMessage(buttons[0][0], win32con.BM_CLICK, 0, 0)
                    e["dismissed"] = round(time.perf_counter() - t0, 1)
    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    if os.path.exists(result) and proc.poll() is not None:
        break
    time.sleep(1)
r["elapsed_s"] = round(time.perf_counter() - t0, 1)
r["exit_code"] = proc.poll()
if r["exit_code"] is None:
    proc.terminate()  # our own process only
    r["terminated_by_launcher"] = True
r["payload_result"] = json.load(open(result, encoding="utf-8")) if os.path.exists(result) else None
print(json.dumps(r, ensure_ascii=False, indent=1))
