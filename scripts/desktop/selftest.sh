#!/usr/bin/env bash
# Desktop app self-test: launch the bundled .app with a temporary data folder, wait for the UI,
# check the backend (smoke.py), both download kinds and that quitting leaves no backend behind.
# Usage: scripts/desktop/selftest.sh ["path/to/PolyMech Studio.app"]
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
app="${1:-$root/apps/desktop/src-tauri/target/release/bundle/macos/PolyMech Studio.app}"
work="$(mktemp -d "${TMPDIR:-/tmp}/polymech-selftest.XXXXXX")"
mkdir -p "$work/data" "$work/downloads"
result="$work/result.txt"
log="$HOME/Library/Logs/cn.edu.zju.polymech.studio/backend.log"
if pgrep -f "PolyMech Studio.app/Contents/MacOS/polymech-studio" >/dev/null; then
  echo "PolyMech Studio 正在运行，请先退出再自测" >&2; exit 2
fi

mkdir -p "$(dirname "$log")"; : >"$log"   # the app truncates it too, but not before we read it
# Finder-like minimal environment: the app must find its tools on its own
env -i HOME="$HOME" USER="$USER" SHELL="${SHELL:-/bin/zsh}" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  POLYMECH_DATA_DIR="$work/data" POLYMECH_DOWNLOAD_DIR="$work/downloads" POLYMECH_DESKTOP_SELFTEST="$result" \
  "$app/Contents/MacOS/polymech-studio" >"$work/shell.log" 2>&1 &
shell_pid=$!
t0=$(date +%s)
port=""
for _ in $(seq 1 240); do
  port=$(grep -o 'on 127.0.0.1:[0-9]*' "$log" 2>/dev/null | tail -1 | cut -d: -f2 || true)
  [[ -n "$port" ]] && break
  sleep 0.5
done
[[ -n "$port" ]] || { echo "FAIL: backend did not start"; tail -20 "$log"; kill "$shell_pid"; exit 1; }
echo "backend on port $port after $(( $(date +%s) - t0 )) s"
(cd "$root" && uv run python scripts/desktop/smoke.py "http://127.0.0.1:$port")

for _ in $(seq 1 60); do
  [[ -f "$result" && $(grep -c '^download' "$result") -ge 2 ]] && break
  sleep 0.5
done
echo "downloads:"; sed 's/^/  /' "$result" 2>/dev/null || true
ok=1
grep -q "download ok .*selftest_link.json" "$result" 2>/dev/null && grep -q '"status":"ok"' "$work/downloads/selftest_link.json" || { echo "FAIL: link download"; ok=0; }
grep -q "download ok .*selftest_blob.txt" "$result" 2>/dev/null && grep -q "PolyMech" "$work/downloads/selftest_blob.txt" || { echo "FAIL: blob download"; ok=0; }

backend_pid=$(pgrep -f "PolyMech Studio.app/Contents/Resources/backend/polymech-backend" || true)
kill "$shell_pid"; wait "$shell_pid" 2>/dev/null || true
sleep 3
if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then echo "FAIL: backend $backend_pid still running after quit"; ok=0; else echo "backend exited with the app"; fi
[[ $ok == 1 ]] && echo "SELFTEST PASSED ($work)" || { echo "SELFTEST FAILED ($work)"; exit 1; }
