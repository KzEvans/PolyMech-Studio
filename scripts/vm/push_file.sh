#!/usr/bin/env bash
# Copy a local file into the VM (no shared folders needed). prlctl exec rejects
# command lines over ~3-4k chars, so the file goes over as base64 chunks.
# Usage: scripts/vm/push_file.sh <local-file> <windows-dest>   (%BRIDGE%/%LOCALAPPDATA% allowed)
set -euo pipefail
source "$(dirname "$0")/vm_lib.sh"
src="$1"; dest="$(vm_path "$2")"; tmp="$dest.b64"
# `set /p` always leaves errorlevel 1, so per-chunk exit codes are ignored;
# the final size comparison is the success criterion.
vmx "for %I in (\"$dest\") do (if not exist \"%~dpI\" mkdir \"%~dpI\") & type nul > \"$tmp\"" >/dev/null || true
base64 < "$src" | tr -d '\n' | fold -w 2500 | while IFS= read -r chunk || [[ -n "$chunk" ]]; do
  vmx "<nul set /p=$chunk>>\"$tmp\"" >/dev/null || true
done
vmx "certutil -f -decode \"$tmp\" \"$dest\" & del \"$tmp\"" >/dev/null || true
want=$(wc -c < "$src" | tr -d ' ')
got=$(vmx "for %I in (\"$dest\") do @echo %~zI" | tr -d '\r\n ')
[[ "$got" == "$want" ]] || { echo "push_file: size mismatch for $dest (local $want, remote '$got')" >&2; exit 1; }
