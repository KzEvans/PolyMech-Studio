"""PyInstaller entry for the desktop backend (see apps/desktop/backend.spec)."""

import os
import sys

from polymech_api.paths import cache_dir

# PyInstaller's matplotlib hook points MPLCONFIGDIR at a fresh temp dir on every launch, which
# rebuilds the font cache each time (~30 s). This onedir bundle has stable paths, so keep the
# cache in the user's Caches folder; must happen before matplotlib is imported.
cache = cache_dir() / "matplotlib"
cache.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(cache)

from polymech_api.desktop import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
