# PyInstaller spec for the desktop backend (onedir: fast start, no unpacking per launch).
# Build: scripts/desktop/build.sh
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("polymech_api")
    + collect_submodules("polymech_database")
    + ["multipart", "python_multipart"]
    # export formats are loaded by name at savefig time
    + ["matplotlib.backends.backend_agg", "matplotlib.backends.backend_svg", "matplotlib.backends.backend_pdf"]
)
datas = (
    # Alembic loads migration scripts from files at runtime → ship the .py sources
    collect_data_files("polymech_database", include_py_files=True)
    + collect_data_files("pint")
    + collect_data_files("matplotlib")
)

a = Analysis(
    ["backend_entry.py"],
    hiddenimports=hiddenimports,
    datas=datas,
    excludes=["tkinter", "IPython", "pytest", "hypothesis", "mypy", "ruff", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="polymech-backend", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="polymech-backend")
