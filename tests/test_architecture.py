"""Enforce module boundaries (SPEC §2.2): the calculation engine must not depend on
frontend, Origin, AI, database or IO layers."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_THIRD_PARTY = {
    "polymech_mechanics": {"numpy", "scipy", "pint"},
    "polymech_dataio": {
        "numpy",
        "scipy",
        "pandas",
        "openpyxl",
        "xlrd",
        "pyarrow",
        "charset_normalizer",
        "pint",
    },
    "polymech_plotting": {"numpy", "pydantic", "matplotlib"},
    "polymech_ai": {"pydantic", "httpx", "anthropic"},
}
ALLOWED_INTERNAL = {
    "polymech_mechanics": set(),
    "polymech_dataio": {"polymech_mechanics"},
    "polymech_plotting": set(),
    "polymech_ai": set(),
    "polymech_database": {"polymech_mechanics"},
}


def _imports(pkg_dir: Path) -> set[str]:
    names: set[str] = set()
    for f in pkg_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("pkg", sorted(ALLOWED_INTERNAL))
def test_package_dependencies(pkg: str) -> None:
    src = next(ROOT.glob(f"packages/*/src/{pkg}"))
    imported = _imports(src) - {pkg} - set(sys.stdlib_module_names) - {"__future__"}
    internal = {m for m in imported if m.startswith("polymech")}
    assert internal <= ALLOWED_INTERNAL[pkg], f"{pkg} imports {internal - ALLOWED_INTERNAL[pkg]}"
    if pkg in ALLOWED_THIRD_PARTY:
        third = imported - internal
        assert third <= ALLOWED_THIRD_PARTY[pkg], (
            f"{pkg} imports {third - ALLOWED_THIRD_PARTY[pkg]}"
        )
