#!/usr/bin/env bash
# Build the macOS desktop app: web UI → frozen Python backend → Tauri bundle (.app + .dmg).
# Output: apps/desktop/src-tauri/target/release/bundle/{macos,dmg}/
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"   # rustup installs here (shell profile left untouched)
command -v cargo >/dev/null || { echo "需要 Rust（rustup）：见 docs/DESKTOP.md" >&2; exit 1; }

echo "== 1/3 web UI"
pnpm -C "$root/apps/web" build

echo "== 2/3 Python backend (PyInstaller, onedir)"
(cd "$root/apps/desktop" && uv run pyinstaller --noconfirm --log-level WARN \
  --distpath "$root/build/desktop/backend" --workpath "$root/build/desktop/work" backend.spec)

echo "== 3/3 Tauri shell + bundle"
(cd "$root/apps/desktop" && pnpm install --frozen-lockfile >/dev/null && pnpm tauri build)
ls -d "$root"/apps/desktop/src-tauri/target/release/bundle/macos/*.app "$root"/apps/desktop/src-tauri/target/release/bundle/dmg/*.dmg
