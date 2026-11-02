import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "import"


@pytest.fixture(scope="session")
def manifest() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
