#!/usr/bin/env bash
# Copy a file out of the VM via base64 over prlctl stdout.
# Usage: scripts/vm/pull_file.sh <windows-src> <local-dest>   (%BRIDGE%/%LOCALAPPDATA% allowed)
set -euo pipefail
source "$(dirname "$0")/vm_lib.sh"
src="$(vm_path "$1")"; dest="$2"
vmx "certutil -f -encode \"$src\" \"$src.b64\" >nul && type \"$src.b64\" && del \"$src.b64\"" \
  | tr -d '\r' | sed '/^-----/d' | base64 -d > "$dest"
