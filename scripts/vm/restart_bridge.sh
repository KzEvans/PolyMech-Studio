#!/usr/bin/env bash
# Graceful bridge restart (after deploy_bridge.sh): ask the bridge to shut down (it closes the
# Origin instance it owns), then start the autostart task again. Token comes from the Keychain.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
url="${1:-$(curl -s http://127.0.0.1:8765/api/settings | python3 -c 'import sys,json;print(json.load(sys.stdin)["bridge_url"])' 2>/dev/null || true)}"
[[ -n "$url" ]] || { echo "usage: restart_bridge.sh <bridge-url>" >&2; exit 2; }
token="$(/usr/bin/security find-generic-password -s PolyMechStudio -a bridge_token -w)"
curl -s -m 10 -X POST -H "Authorization: Bearer $token" "$url/v1/shutdown" >/dev/null || true
for _ in $(seq 1 60); do curl -s -m 2 "$url/health" >/dev/null || break; sleep 1; done
# the old process may still be closing Origin after HTTP stops; the task ignores a new start
# while it is Running, so wait for it to finish first
cat > "${TMPDIR:-/tmp}/polymech_start_bridge.ps1" <<'PS'
$n = "PolyMech Origin Bridge"
$deadline = (Get-Date).AddSeconds(90)
while ((Get-ScheduledTask -TaskName $n).State -eq "Running" -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
Start-ScheduledTask -TaskName $n
Start-Sleep 6
(Get-ScheduledTask -TaskName $n).State
PS
"$here/run_ps.sh" "${TMPDIR:-/tmp}/polymech_start_bridge.ps1"
for _ in $(seq 1 30); do curl -s -m 2 "$url/health" && echo && exit 0; sleep 1; done
echo "bridge did not come back" >&2; exit 1
