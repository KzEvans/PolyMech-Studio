#!/usr/bin/env bash
# Run a command in the VM user's interactive session, hidden (no console window),
# then print its output. Needed for Origin (must live in the logged-in session).
# Usage: scripts/vm/run_user.sh [-t SECONDS] <exe> [args...]   (%BRIDGE%/%LOCALAPPDATA% allowed)
# Exit status = the command's exit status.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/vm_lib.sh"
timeout=600
if [[ "${1:-}" == "-t" ]]; then timeout="$2"; shift 2; fi
vm_resolve_user
quoted=""
for a in "$@"; do quoted+="\"$(vm_path "$a")\" "; done
log="$VM_BRIDGE_ROOT\\stage\\run_user_$$.log"
runner="%BRIDGE%\\stage\\hidden_run_$$.py"
"$here/push_file.sh" "$here/../../bridge/windows-origin/hidden_run.py" "$runner"
"$here/run_ps.sh" "$here/run_user.ps1" "User=$VM_USER" "Pythonw=%BRIDGE%\\venv\\Scripts\\pythonw.exe" \
  "Runner=$runner" "Log=$log" "CmdArgs=$quoted" "TimeoutS=$timeout"
vmx "type \"$log\"" | iconv -f UTF-8 -t UTF-8 -c || true
rc=$(vmx "type \"$log.rc\"" | tr -d '\r\n ' || true)
vmx "del \"$log\" \"$log.rc\" \"$(vm_path "$runner")\"" >/dev/null || true
[[ "$rc" =~ ^[0-9]+$ ]] || { echo "run_user: no exit code (timeout or launch failure)" >&2; exit 124; }
exit "$rc"
