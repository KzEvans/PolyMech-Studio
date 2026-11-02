# Windows-only companion. This entry point never touches the existing remote Bridge config.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

source = Path(SPECPATH).parents[1] / "bridge" / "windows-origin"
a = Analysis(
    ["bridge_entry.py"],
    pathex=[str(source)],
    hiddenimports=collect_submodules("uvicorn") + [
        "originpro", "OriginExt", "pythoncom", "pywintypes", "win32api", "win32process",
        "polymech_api.native_windows",
    ],
    datas=[(str(Path(SPECPATH).parents[1] / "templates" / "origin"), "templates")],
    excludes=["tkinter", "IPython", "pytest", "hypothesis", "mypy", "ruff", "matplotlib", "scipy", "pandas", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="polymech-bridge", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="polymech-bridge")
