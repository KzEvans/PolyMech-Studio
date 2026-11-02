"""File storage: content-addressed read-only raw archive and Parquet curve files.

All writes go to a temporary file in the target directory followed by os.replace, so a crash
never leaves a half-written file under the final name (SPEC §11.4).
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from polymech_database.errors import StorageError


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        Path(tmp).unlink(missing_ok=True)
        raise StorageError(f"写入 {path.name} 失败：{e.strerror}") from e


def archive_raw(data_dir: Path, data: bytes, original_name: str) -> tuple[str, str]:
    """Store an original file once, read-only. Returns (sha256, path relative to data_dir)."""
    digest = sha256_bytes(data)
    suffix = Path(original_name).suffix.lower()[:10]
    rel = Path("raw") / digest[:2] / f"{digest}{suffix}"
    target = data_dir / rel
    if target.exists():
        if sha256_bytes(target.read_bytes()) != digest:
            raise StorageError(f"归档文件 {rel} 已存在但内容哈希不一致，可能已被篡改")
        return digest, rel.as_posix()
    atomic_write(target, data)
    target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return digest, rel.as_posix()


def read_archived(data_dir: Path, rel: str, expected_sha256: str) -> bytes:
    data = (data_dir / rel).read_bytes()
    if sha256_bytes(data) != expected_sha256:
        raise StorageError(f"归档文件 {rel} 的哈希与数据库记录不一致")
    return data


def write_curves(data_dir: Path, rel: str, curves: Mapping[str, NDArray[np.float64]]) -> None:
    """Columns may differ in length (e.g. per-cycle tables); short ones are null-padded."""
    n = max((len(v) for v in curves.values()), default=0)
    cols = {}
    for k, v in curves.items():
        arr = np.full(n, np.nan)
        arr[: len(v)] = v
        cols[k] = pa.array(arr, mask=np.arange(n) >= len(v))
    table = pa.table(cols)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    atomic_write(data_dir / rel, sink.getvalue().to_pybytes())


def read_curves(data_dir: Path, rel: str) -> dict[str, NDArray[np.float64]]:
    table = pq.read_table(data_dir / rel)
    out: dict[str, NDArray[np.float64]] = {}
    for name in table.column_names:
        col = table.column(name)
        valid = col.drop_null().to_numpy(zero_copy_only=False)
        out[name] = np.asarray(valid, dtype=float)
    return out
