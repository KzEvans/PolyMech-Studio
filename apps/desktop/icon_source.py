"""Draws the 1024×1024 app icon source (icon-source.png); `pnpm tauri icon` derives the rest.
Motif: a loading/unloading (hysteresis) loop on stress–stretch axes."""

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig = plt.figure(figsize=(10.24, 10.24), dpi=100)
ax = fig.add_axes((0, 0, 1, 1))
ax.set_xlim(0, 1024)
ax.set_ylim(0, 1024)
ax.axis("off")
# macOS icon grid: 824 px rounded square centred, corner radius ≈ 185 px
ax.add_patch(
    FancyBboxPatch(
        (100 + 185, 100 + 185),
        824 - 370,
        824 - 370,
        boxstyle="round,pad=185",
        fc="#0A64D6",
        ec="none",
    )
)
ox, oy, w, h = 250, 250, 540, 520
ax.plot(
    [ox, ox, ox + w], [oy + h, oy, oy], color="white", lw=14, solid_capstyle="round", alpha=0.55
)
t = np.linspace(0, 1, 200)
load = oy + h * 0.92 * (0.55 * t + 0.45 * t**3)
unload = oy + h * 0.92 * (0.15 * t + 0.85 * t**4)
x = ox + 30 + (w - 60) * t
ax.fill_between(x, unload, load, color="white", alpha=0.25, lw=0)
ax.plot(x, load, color="white", lw=22, solid_capstyle="round")
ax.plot(x, unload, color="#9CC8FF", lw=22, solid_capstyle="round")
fig.savefig("icon-source.png", transparent=True)
