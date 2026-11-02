from pathlib import Path
from typing import Any

import numpy as np
import pytest

from polymech_dataio.errors import FileFormatError
from polymech_dataio.reader import read_bytes, read_file, split_name_unit

from .conftest import FIXTURES


def _table(entry: dict[str, Any]):
    tables = read_file(FIXTURES / entry["file"])
    if entry["sheet"]:
        return next(t for t in tables if t.sheet == entry["sheet"])
    assert len(tables) == 1
    return tables[0]


def test_every_fixture_table_is_read_with_expected_headers(manifest: list[dict[str, Any]]) -> None:
    for entry in manifest:
        t = _table(entry)
        headers = [c.header for c in t.columns]
        assert headers == list(entry["columns"]), entry["file"]
        assert t.n_rows > 5
        for c in t.columns:
            assert np.isfinite(c.values).sum() >= t.n_rows - 1  # at most one injected gap


def test_gbk_with_preamble_and_units_row() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_gbk_chinese.csv")
    assert t.encoding == "gb18030"
    assert t.preamble_fields["样品厚度"] == "1.00 mm"
    assert [c.unit_text for c in t.columns] == ["s", "N", "mm"]
    assert "SYNTHETIC" in t.preamble[0]


def test_utf8_bom_tsv_with_missing_value() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_bom_kN.tsv")
    assert t.encoding == "utf-8-sig"
    assert t.delimiter == "\t"
    load = t.columns[1]
    assert load.unit_text == "kN"
    assert load.n_missing == 1
    assert np.isnan(load.values[10])


def test_decimal_comma_with_semicolons() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_decimal_comma.csv")
    assert t.delimiter == ";"
    assert t.decimal_comma
    assert t.columns[0].values[0] == pytest.approx(1.0)
    assert t.columns[0].values[-1] > 3.0


def test_whitespace_delimited_txt() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_strain_percent.txt")
    assert t.delimiter is None
    assert [c.unit_text for c in t.columns] == ["%", "MPa"]


def test_multisheet_excel_with_group_header() -> None:
    tables = read_file(FIXTURES / "SYNTH_uniaxial_multisheet.xlsx")
    assert [t.sheet for t in tables] == ["Specimen A", "Specimen B"]
    assert tables[0].columns[1].header == "Channel 1 / Force"
    assert tables[0].columns[1].unit_text == "N"


@pytest.mark.parametrize(
    ("text", "name", "unit"),
    [
        ("Force (N)", "Force", "N"),
        ("Stress [MPa]", "Stress", "MPa"),
        ("应力（MPa）", "应力", "MPa"),
        ("负荷/mN", "负荷", "mN"),
        ("Load, kN", "Load", "kN"),
        ("Displacement, total", "Displacement, total", None),
        ("Stretch", "Stretch", None),
        ("Temperature (°C)", "Temperature", "°C"),
    ],
)
def test_split_name_unit(text: str, name: str, unit: str | None) -> None:
    assert split_name_unit(text) == (name, unit)


def test_thousands_separator_is_never_guessed() -> None:
    data = b'Force (N),Disp (mm)\n"1,234",1\n"2,345",2\n"3,456",3\n4,4\n'
    # quoted "1,234" in a comma file is not a number; nothing is silently converted
    (t,) = read_bytes(data, "x.csv")
    assert t.columns[0].n_non_numeric == 3


def test_corrupt_binary_rejected() -> None:
    with pytest.raises(FileFormatError):
        read_file(FIXTURES / "SYNTH_corrupt.csv")


def test_empty_and_textonly_files_rejected() -> None:
    with pytest.raises(FileFormatError):
        read_bytes(b"", "empty.csv")
    with pytest.raises(FileFormatError):
        read_bytes("只有文字\n没有数据\n".encode(), "notes.txt")
    with pytest.raises(FileFormatError):
        read_bytes(b"x", "old.xls")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileFormatError):
        read_file(tmp_path / "nope.csv")


def test_legacy_xls_instrument_export(tmp_path: Path) -> None:
    """WPS/Excel 97–2003 .xls as exported by the tensile tester: numbered headers, no units."""
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("tmpMyFile")
    # the 65536-row exports add a trailing “Column1” header over blank cells
    for j, h in enumerate(["时间4", "力4", "位移4", "应力4", "应变4", "Column1"]):
        ws.write(0, j, h)
    for i in range(1, 21):
        for j, v in enumerate([0.05 * i, 0.001 * i, 0.01 * i, 0.0012 * i, 0.0005 * i, " "]):
            ws.write(i, j, v)
    wb.add_sheet("Sheet2")  # empty sheets are skipped
    wb.save(tmp_path / "PEHA.xls")

    (t,) = read_file(tmp_path / "PEHA.xls")
    assert t.sheet == "tmpMyFile"
    assert [c.header for c in t.columns] == ["时间4", "力4", "位移4", "应力4", "应变4"]
    assert t.n_rows == 20
    np.testing.assert_allclose(t.columns[3].values, 0.0012 * np.arange(1, 21))
    # recognised by content even when the extension is wrong
    (t2,) = read_bytes((tmp_path / "PEHA.xls").read_bytes(), "export.dat")
    assert t2.n_rows == 20
