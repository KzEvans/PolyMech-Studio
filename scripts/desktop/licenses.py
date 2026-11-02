"""Collect the installed Python dependency licenses into the Windows bundle."""

from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
runtime_licenses = out / "python-runtime"
runtime_licenses.mkdir(exist_ok=True)
shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", runtime_licenses / "LICENSE.txt")
packages = []
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
    name = dist.metadata["Name"]
    packages.append(
        {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", ""),
            "home": dist.metadata.get("Home-page", ""),
        }
    )
    for file in dist.files or []:
        if file.name.lower().startswith(("license", "licence", "copying", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = out / "python" / name / Path(*file.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(out / "python-dependencies.json").write_text(
    json.dumps(packages, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Frontend dependencies are materialized by pnpm before this collector is run.
root = Path(__file__).resolve().parents[2]
node_packages = {}
for modules in (root / "apps" / "web" / "node_modules", root / "apps" / "desktop" / "node_modules"):
    for package_json in modules.rglob("package.json"):
        try:
            info = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not info.get("name") or not info.get("version"):
            continue
        label = info["name"] + "@" + info["version"]
        node_packages[label] = {
            "name": info["name"],
            "version": info["version"],
            "license": info.get("license", ""),
        }
        for source in package_json.parent.iterdir():
            if source.is_file() and source.name.lower().startswith(
                ("license", "licence", "copying", "notice")
            ):
                target = out / "node" / label / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(out / "node-dependencies.json").write_text(
    json.dumps(list(node_packages.values()), ensure_ascii=False, indent=2), encoding="utf-8"
)

# Cargo metadata supplies the resolved package versions and paths, including license files.

metadata = subprocess.run(
    [
        "cargo",
        "metadata",
        "--manifest-path",
        str(root / "apps/desktop/src-tauri/Cargo.toml"),
        "--locked",
        "--format-version",
        "1",
        "--filter-platform",
        "x86_64-pc-windows-msvc",
    ],
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=True,
)
cargo = json.loads(metadata.stdout)
resolved = {node["id"] for node in cargo["resolve"]["nodes"]}
rust_packages = []
for package in cargo["packages"]:
    if package["id"] not in resolved:
        continue
    label = package["name"] + "@" + package["version"]
    rust_packages.append(
        {"name": package["name"], "version": package["version"], "license": package["license"]}
    )
    directory = Path(package["manifest_path"]).parent
    candidates = [
        file
        for file in directory.iterdir()
        if file.name.lower().startswith(("license", "licence", "copying", "notice"))
    ]
    if package.get("license_file"):
        candidates.append(directory / package["license_file"])
    for source in candidates:
        if source.is_file():
            target = out / "rust" / label / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
(out / "rust-dependencies.json").write_text(
    json.dumps(rust_packages, ensure_ascii=False, indent=2), encoding="utf-8"
)
