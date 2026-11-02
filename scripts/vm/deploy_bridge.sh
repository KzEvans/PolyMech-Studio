#!/usr/bin/env bash
# Copy the bridge package into the VM (%LOCALAPPDATA%\PolyMechBridge\app) and install its
# dependencies into the bridge venv. Idempotent. Does not start the bridge.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../../bridge/windows-origin"
"$here/push_file.sh" "$src/requirements.txt" '%BRIDGE%\app\requirements.txt'
for f in "$src"/polymech_bridge/*.py; do
  "$here/push_file.sh" "$f" "%BRIDGE%\\app\\polymech_bridge\\$(basename "$f")"
done
for f in "$here/../../templates/origin"/*; do
  "$here/push_file.sh" "$f" "%BRIDGE%\\app\\templates\\$(basename "$f")"
done
for f in bridge_selftest.py make_templates.py; do
  "$here/push_file.sh" "$src/$f" "%BRIDGE%\\app\\$f"
done
"$here/run_ps.sh" "$src/setup_env.ps1" 'Root=%BRIDGE%'
