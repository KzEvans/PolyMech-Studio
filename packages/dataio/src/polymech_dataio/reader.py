"""Read instrument exports without requiring a fixed layout (SPEC §3.1).

Handles UTF-8 (with/without BOM), UTF-16, GBK/GB18030; comma/tab/semicolon/pipe/whitespace
delimiters (and decimal commas); instrument preamble lines; one or more header rows including
a separate units row; units embedded in column names; missing-value markers; XLSX with
multiple sheets. Nothing is modified: values that are not numbers are kept as NaN and counted.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import charset_normalizer
import numpy as np
from numpy.typing import NDArray

from polymech_dataio.errors import FileFormatError

MISSING_MARKERS = {"", "nan", "na", "n/a", "null", "none", "--", "-", "—", "#n/a", "inf?"}
_NUM_RE = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")
_UNIT_IN_NAME = [
    re.compile(r"^(?P<name>.*?)\s*[\(\[（【{]\s*(?P<unit>[^)\]）】}]+?)\s*[)\]）】}]\s*$"),
    re.compile(r"^(?P<name>.*?\S)\s*/\s*(?P<unit>[^\s/]+)$"),
    re.compile(r"^(?P<name>.*?\S)\s*,\s*(?P<unit>[^\s,]+)$"),
]
_KV_RE = re.compile(r"^\s*(?P<key>[^:：=]{1,60}?)\s*[:：=]\s*(?P<value>.*?)\s*$")
TEXT_SUFFIXES = {".csv", ".tsv", ".txt", ".dat", ".asc"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm"}


@dataclass(frozen=True)
class RawColumn:
    index: int
    header: str  # header text as found (multi-row headers joined with " / ")
    name: str  # header without the unit part
    unit_text: str | None  # unit as written in the file (None if none found)
    values: NDArray[np.float64]  # NaN where missing or non-numeric
    n_missing: int
    n_non_numeric: int
    non_numeric_examples: tuple[str, ...]


@dataclass(frozen=True)
class RawTable:
    source: str  # file name (no directories) + optional "#sheet"
    sheet: str | None
    encoding: str | None
    delimiter: str | None
    decimal_comma: bool
    header_rows: tuple[int, ...]  # 0-based row indices used as headers
    data_start_row: int
    preamble: tuple[str, ...]
    preamble_fields: dict[str, str]
    columns: tuple[RawColumn, ...]
    warnings: tuple[str, ...] = field(default=())

    @property
    def n_rows(self) -> int:
        return len(self.columns[0].values) if self.columns else 0


# --------------------------------------------------------------------------- decoding
def decode_bytes(data: bytes) -> tuple[str, str]:
    """Return (text, encoding). Prefers explicit BOMs, then strict UTF-8, then detection."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    best = charset_normalizer.from_bytes(data).best()
    enc = (best.encoding if best else "gb18030").lower()
    if enc in {"gbk", "gb2312", "cp936", "hz", "big5"} or enc.startswith("gb"):
        enc = "gb18030"  # superset of GBK/GB2312; Big5 misdetections are rare for numeric files
    try:
        return data.decode(enc), enc
    except (UnicodeDecodeError, LookupError) as e:
        raise FileFormatError(f"无法识别文件编码（尝试了 UTF-8 与 {enc}）") from e


# --------------------------------------------------------------------------- cell parsing
def parse_number(cell: Any, decimal_comma: bool = False) -> float | None:
    """Float for numeric cells, None for missing/non-numeric."""
    if cell is None:
        return None
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if np.isfinite(cell) else None
    s = str(cell).strip().replace("−", "-")
    if s.lower() in MISSING_MARKERS:
        return None
    if "," in s:
        if not decimal_comma:
            return None  # could be a thousands separator: never guess
        s = s.replace(",", ".")
    if not _NUM_RE.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_numeric(cell: Any, decimal_comma: bool) -> bool:
    return parse_number(cell, decimal_comma) is not None


def _is_missing(cell: Any) -> bool:
    return cell is None or (isinstance(cell, str) and cell.strip().lower() in MISSING_MARKERS)


def split_name_unit(header: str) -> tuple[str, str | None]:
    """'Force (N)' → ('Force', 'N'); '应力/MPa' → ('应力', 'MPa'); 'Stress' → ('Stress', None)."""
    from polymech_dataio.units_text import looks_like_unit

    h = header.strip()
    for rx in _UNIT_IN_NAME:
        m = rx.match(h)
        if m and looks_like_unit(m.group("unit")):
            return m.group("name").strip(), m.group("unit").strip()
    return h, None


# --------------------------------------------------------------------------- delimiter
def _split(line: str, delim: str | None) -> list[str]:
    if delim is None:
        return line.split()
    return next(csv.reader([line], delimiter=delim, quotechar='"'))


def sniff_delimiter(lines: Sequence[str]) -> str | None:
    """Pick the delimiter giving the most consistent multi-field split of the tail rows."""
    body = [ln for ln in lines if ln.strip()]
    sample = body[len(body) // 2 :][:200] or body
    best: tuple[float, str | None] = (0.0, None)
    for delim in ["\t", ",", ";", "|", None]:
        split = [_split(ln, delim) for ln in sample]
        counts = [len(r) for r in split]
        mode, freq = Counter(counts).most_common(1)[0]
        if mode < 2:
            continue
        cells = [c for r in split for c in r if c.strip()]
        numeric = sum(
            parse_number(c) is not None or parse_number(c, decimal_comma=True) is not None
            for c in cells
        ) / max(len(cells), 1)
        # consistent field count AND fields that parse as numbers (rejects ',' in "1,5;2,5")
        score = freq / len(counts) + numeric + 0.01 * mode
        if score > best[0]:
            best = (score, delim)
    return best[1]


# --------------------------------------------------------------------------- layout
def _locate(rows: list[list[Any]], decimal_comma: bool) -> tuple[int, int]:
    """Return (data_start, n_cols): first row starting ≥3 consecutive mostly-numeric rows."""
    n = len(rows)
    for i in range(n):
        width = len(rows[i])
        if width == 0:
            continue
        block = rows[i : i + 3]
        if len(block) < min(3, n - i):
            continue

        def numeric_row(r: list[Any], w: int = width) -> bool:
            cells = r[:w]
            num = sum(_is_numeric(c, decimal_comma) for c in cells)
            filled = sum(not _is_missing(c) for c in cells)
            return num >= 1 and num >= 0.5 * max(filled, 1) and len(r) >= max(1, w - 1)

        if all(numeric_row(r) for r in block):
            counts = Counter(len(r) for r in rows[i : i + 50])
            return i, counts.most_common(1)[0][0]
    raise FileFormatError("没有找到连续的数值数据行，可能不是数据表或格式无法识别")


def _is_units_row(r: list[Any]) -> bool:
    from polymech_dataio.units_text import looks_like_unit

    filled = [str(c).strip() for c in r if not _is_missing(c)]
    return bool(filled) and all(looks_like_unit(c.strip("()[]（）")) for c in filled)


def _header_rows(
    rows: list[list[Any]], start: int, ncol: int, decimal_comma: bool, allow_narrow_group: bool
) -> list[int]:
    """Up to 3 textual rows directly above the data. Header rows span the full table width;
    a narrower row is accepted only as a merged-cell group header above a full header row
    (Excel), and an Excel header row may be wider than the data. Comment lines ('#', '//')
    are never headers."""
    hdr: list[int] = []
    i = start - 1
    while i >= 0 and len(hdr) < 3:
        r = rows[i]
        filled = [c for c in r if not _is_missing(c)]
        if not filled or str(filled[0]).lstrip().startswith(("#", "//")):
            break
        textual = sum(not _is_numeric(c, decimal_comma) for c in filled)
        if textual < 0.5 * len(filled):
            break
        if len(r) != ncol and not (allow_narrow_group and (len(r) > ncol or hdr)):
            break  # Excel: a header may also name trailing columns that hold no data
        if hdr and not allow_narrow_group and not _is_units_row(rows[hdr[0]]):
            break  # text files: only "names row + units row"; above that is preamble
        hdr.insert(0, i)
        i -= 1
    return hdr


def _build_table(
    rows: list[list[Any]],
    source: str,
    sheet: str | None,
    encoding: str | None,
    delimiter: str | None,
    raw_lines: Sequence[str] | None,
) -> RawTable:
    from polymech_dataio.units_text import looks_like_unit

    decimal_comma = False
    if delimiter in {";", "\t", None}:
        tail = [c for r in rows[len(rows) // 2 :] for c in r if isinstance(c, str)]
        dc = sum(bool(re.fullmatch(r"[+-]?\d+,\d+", c.strip())) for c in tail)
        dp = sum(bool(re.fullmatch(r"[+-]?\d+\.\d+", c.strip())) for c in tail)
        decimal_comma = dc > dp
    start, ncol = _locate(rows, decimal_comma)
    hdr_idx = _header_rows(rows, start, ncol, decimal_comma, allow_narrow_group=raw_lines is None)

    # a header row whose filled cells all look like units is the units row
    units_row: list[str | None] = [None] * ncol
    name_rows: list[list[str]] = []
    for i in hdr_idx:
        cells = [("" if _is_missing(c) else str(c).strip()) for c in rows[i]] + [""] * ncol
        cells = cells[:ncol]
        filled = [c for c in cells if c]
        if name_rows and filled and all(looks_like_unit(c.strip("()[]（）")) for c in filled):
            units_row = [c.strip("()[]（）") or None for c in cells]
        else:
            name_rows.append(cells)
    if not name_rows:
        name_rows = [[f"列{j + 1}" for j in range(ncol)]]
    # forward-fill grouped (merged-cell) upper header rows
    for r in name_rows[:-1]:
        last = ""
        for j in range(ncol):
            r[j] = r[j] or last
            last = r[j]

    data_rows = rows[start:]
    warnings: list[str] = []
    ragged = sum(1 for r in data_rows if r and len(r) != ncol)
    if ragged:
        warnings.append(
            f"{ragged} 行的列数与表头不一致，已按位置对齐（多余列忽略，缺少列记为缺失）"
        )

    columns: list[RawColumn] = []
    for j in range(ncol):
        parts = [r[j] for r in name_rows if r[j]]
        header = " / ".join(dict.fromkeys(parts)) or f"列{j + 1}"
        name, unit = split_name_unit(parts[-1] if parts else header)
        if len(parts) > 1:
            name = " / ".join([*dict.fromkeys(parts[:-1]), name])
        unit = units_row[j] or unit
        vals = np.full(len(data_rows), np.nan)
        n_missing = n_bad = 0
        bad_examples: list[str] = []
        for k, r in enumerate(data_rows):
            cell = r[j] if j < len(r) else None
            v = parse_number(cell, decimal_comma)
            if v is not None:
                vals[k] = v
            elif _is_missing(cell):
                n_missing += 1
            else:
                n_bad += 1
                if len(bad_examples) < 3:
                    bad_examples.append(str(cell))
        columns.append(
            RawColumn(j, header, name, unit, vals, n_missing, n_bad, tuple(bad_examples))
        )

    # drop trailing rows that are entirely empty (e.g. Excel formatting leftovers)
    mask = np.zeros(len(data_rows), dtype=bool)
    for c in columns:
        mask |= ~np.isnan(c.values)
    keep = int(np.nonzero(mask)[0][-1]) + 1 if mask.any() else 0
    if keep < len(data_rows):
        columns = [
            RawColumn(
                c.index,
                c.header,
                c.name,
                c.unit_text,
                c.values[:keep],
                max(0, c.n_missing - (len(data_rows) - keep)),
                c.n_non_numeric,
                c.non_numeric_examples,
            )
            for c in columns
        ]

    first_header = hdr_idx[0] if hdr_idx else start
    if raw_lines is not None:
        preamble = tuple(ln.strip() for ln in raw_lines[:first_header] if ln.strip())
    else:
        preamble = tuple(
            " ".join(str(c) for c in r if not _is_missing(c)).strip()
            for r in rows[:first_header]
            if any(not _is_missing(c) for c in r)
        )
    fields: dict[str, str] = {}
    for i in range(first_header):
        r = [str(c).strip() for c in rows[i] if not _is_missing(c)]
        if r:
            r[0] = r[0].lstrip("#/ ").strip()  # comment markers are not part of keys
            r = [c for c in r if c]
        if len(r) == 2 and not r[0].endswith((":", "：")):
            fields.setdefault(r[0], r[1])
            continue
        m = _KV_RE.match(" ".join(r))
        if m and m.group("value"):
            fields.setdefault(m.group("key").strip(), m.group("value"))
        elif len(r) >= 2:
            fields.setdefault(r[0].rstrip(":："), " ".join(r[1:]))

    return RawTable(
        source=source,
        sheet=sheet,
        encoding=encoding,
        delimiter=delimiter,
        decimal_comma=decimal_comma,
        header_rows=tuple(hdr_idx),
        data_start_row=start,
        preamble=preamble,
        preamble_fields=fields,
        columns=tuple(columns),
        warnings=tuple(warnings),
    )


# --------------------------------------------------------------------------- public API
def read_text_table(data: bytes, source: str) -> RawTable:
    text, enc = decode_bytes(data)
    lines = text.splitlines()
    delim = sniff_delimiter(lines)
    rows = [_split(ln, delim) if ln.strip() else [] for ln in lines]
    return _build_table(rows, source, None, enc, delim, lines)


def _sheet_tables(sheets: list[tuple[str, list[list[Any]]]], source: str) -> list[RawTable]:
    tables: list[RawTable] = []
    errors: list[str] = []
    for title, rows in sheets:
        while rows and all(_is_missing(c) for c in rows[-1]):
            rows.pop()
        rows = [r if any(not _is_missing(c) for c in r) else [] for r in rows]
        # trim trailing empty cells so row widths reflect content
        rows = [
            r[: max((k + 1 for k, c in enumerate(r) if not _is_missing(c)), default=0)]
            for r in rows
        ]
        if not rows:
            continue
        try:
            tables.append(_build_table(rows, f"{source}#{title}", title, None, None, None))
        except FileFormatError as e:
            errors.append(f"{title}: {e}")
    if not tables:
        raise FileFormatError(
            "Excel 中没有可识别的数据工作表" + (f"（{'; '.join(errors)}）" if errors else "")
        )
    return tables


def read_excel_tables(data: bytes, source: str) -> list[RawTable]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # openpyxl raises many types for corrupt files
        raise FileFormatError(f"无法打开 Excel 文件：{e}") from e
    sheets = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    wb.close()
    return _sheet_tables(sheets, source)


def read_xls_tables(data: bytes, source: str) -> list[RawTable]:
    """Legacy BIFF .xls (Excel 97–2003, WPS exports); one table per data sheet."""
    import xlrd

    try:
        wb = xlrd.open_workbook(file_contents=data)
    except Exception as e:  # xlrd raises many types for corrupt files
        raise FileFormatError(f"无法打开 .xls 文件：{e}") from e
    sheets = [
        (
            sh.name,
            [
                [
                    None
                    if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR)
                    else c.value
                    for c in sh.row(r)
                ]
                for r in range(sh.nrows)
            ],
        )
        for sh in wb.sheets()
    ]
    return _sheet_tables(sheets, source)


def read_file(path: str | Path) -> list[RawTable]:
    """Read one file; Excel workbooks yield one table per data sheet."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as e:
        raise FileFormatError(f"无法读取文件 {p.name}：{e.strerror}") from e
    return read_bytes(data, p.name)


def read_bytes(data: bytes, filename: str) -> list[RawTable]:
    suffix = Path(filename).suffix.lower()
    if not data:
        raise FileFormatError(f"{filename} 是空文件")
    if suffix in EXCEL_SUFFIXES or data[:4] == b"PK\x03\x04":
        return read_excel_tables(data, filename)
    if suffix == ".xls" or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return read_xls_tables(data, filename)
    if (
        suffix not in TEXT_SUFFIXES
        and b"\x00" in data[:1024]
        and not data.startswith((b"\xff\xfe", b"\xfe\xff"))
    ):
        raise FileFormatError(f"{filename} 看起来是二进制文件，无法作为文本表格读取")
    return [read_text_table(data, filename)]


def read_files(paths: Sequence[str | Path]) -> list[RawTable]:
    """Batch import. Errors are per file: a FileFormatError names the failing file."""
    out: list[RawTable] = []
    for p in paths:
        out.extend(read_file(p))
    return out
