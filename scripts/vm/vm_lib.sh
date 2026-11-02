# Shared helpers for talking to the Parallels VM. Source, don't execute.
# All prlctl calls here run as SYSTEM in session 0 (no --current-user), so nothing
# pops up on the user's desktop. Work that must run in the user's interactive
# session goes through run_user.sh (hidden scheduled task + pythonw).
VM="${POLYMECH_VM:-Windows 11}"
export LC_ALL=C  # VM output is GBK; byte-oriented text tools must not assume UTF-8

# prlctl exec, stdin detached (prlctl would otherwise swallow the caller's stdin),
# retrying prlctl's own transient failures (exit 255, "PrlJob_GetResult ...").
vmx() {
  local i rc out
  for i in 1 2 3 4 5; do
    rc=0; out=$(prlctl exec "$VM" cmd /c "$1" </dev/null 2>&1) || rc=$?
    if (( rc != 255 )) || [[ "$out" != *PrlJob_* && "$out" != *PrlVmGuest_* ]]; then
      printf '%s' "$out"; return $rc
    fi
    sleep 1
  done
  printf '%s' "$out" >&2; return 255
}

# Console (interactive) user and their LOCALAPPDATA, resolved once per shell.
vm_resolve_user() {
  [[ -n "${VM_USER:-}" ]] && return 0
  VM_USER=$({ vmx "query user" || true; } | awk '/console/ {sub(/^>/, "", $1); print $1; exit}')
  [[ -n "$VM_USER" ]] || { echo "vm_lib: no console user logged in to '$VM'" >&2; return 1; }
  VM_HOME=$(vmx "reg query \"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\" /s /v ProfileImagePath" \
    | tr -d '\r' | awk -v u="$VM_USER" 'tolower($NF) ~ "\\\\" tolower(u) "$" {print $NF; exit}')
  [[ -n "$VM_HOME" ]] || { echo "vm_lib: cannot resolve profile of $VM_USER" >&2; return 1; }
  VM_LOCALAPPDATA="$VM_HOME\\AppData\\Local"
  VM_BRIDGE_ROOT="$VM_LOCALAPPDATA\\PolyMechBridge"
  export VM_USER VM_HOME VM_LOCALAPPDATA VM_BRIDGE_ROOT
}

# Expand %LOCALAPPDATA% / %BRIDGE% placeholders to the console user's paths.
vm_path() {
  vm_resolve_user
  local p="$1"
  p="${p//%LOCALAPPDATA%/$VM_LOCALAPPDATA}"
  p="${p//%BRIDGE%/$VM_BRIDGE_ROOT}"
  printf '%s' "$p"
}
