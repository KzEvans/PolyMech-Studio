"""Deterministic hashes of analysis inputs and results (SPEC §9.3 C, §10 item 12)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def hash_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def hash_arrays(arrays: Mapping[str, NDArray[np.float64]], extra: Any = None) -> str:
    h = hashlib.sha256()
    for k in sorted(arrays):
        h.update(k.encode())
        h.update(np.ascontiguousarray(arrays[k], dtype="<f8").tobytes())
    if extra is not None:
        h.update(canonical_json(extra).encode())
    return h.hexdigest()
