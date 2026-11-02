#!/usr/bin/env bash
# Run a local PowerShell script inside the VM as SYSTEM (session 0, no window on
# the user's desktop). For work that needs the user's session use run_user.sh.
# Usage: scripts/vm/run_ps.sh <script.ps1> [VAR=VALUE ...]  -> `$VAR = 'VALUE'` prelude
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/vm_lib.sh"
script="$1"; shift
staged="$(mktemp -t polymech_ps)"
trap 'rm -f "$staged"' EXIT
{
  printf '\xEF\xBB\xBF$ProgressPreference="SilentlyContinue"; [Console]::OutputEncoding=[Text.Encoding]::UTF8\n'
  for kv in "$@"; do printf "\$%s = '%s'\n" "${kv%%=*}" "$(vm_path "${kv#*=}")"; done
  cat "$script"
} > "$staged"
remote="$(vm_path "%BRIDGE%\\stage\\$(basename "$script" .ps1)_$$.ps1")"
"$here/push_file.sh" "$staged" "$remote"
rc=0
vmx "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"$remote\"" || rc=$?
vmx "del \"$remote\"" >/dev/null || true
exit "$rc"
