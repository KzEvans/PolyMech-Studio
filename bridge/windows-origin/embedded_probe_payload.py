# Runs INSIDE Origin's embedded Python (launched via Origin64.exe -rs run -pyf ...).
import json, os, sys, traceback
out = os.path.join(os.environ["LOCALAPPDATA"], "PolyMechBridge", "stage", "embedded_probe.json")
r = {"executable": sys.executable, "version": sys.version, "pid": os.getpid()}
try:
    import originpro as op
    r["originpro_file"] = op.__file__
    r["origin_version"] = op.lt_float("@V")
    r["uff"] = op.get_lt_str("%Y") if hasattr(op, "get_lt_str") else None
    for mod in ("numpy", "pandas"):
        try:
            r[mod] = __import__(mod).__version__
        except Exception as e:
            r[mod] = f"unavailable: {e}"
except Exception:
    r["error"] = traceback.format_exc()
with open(out, "w", encoding="utf-8") as f:
    json.dump(r, f, ensure_ascii=False, indent=1)
