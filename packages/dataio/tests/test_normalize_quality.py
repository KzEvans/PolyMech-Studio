import numpy as np
import pytest

from polymech_dataio.corrections import linear_baseline, shift_to_contact, smooth, zero_offset
from polymech_dataio.errors import DataIOError, MappingError
from polymech_dataio.mapping import MappedColumn, Quantity
from polymech_dataio.metadata import ExperimentMetadata, TestType, missing_fields, required_fields
from polymech_dataio.normalize import normalize
from polymech_dataio.quality import check_quality, summarize_issues
from polymech_dataio.reader import read_bytes, read_file

from .conftest import FIXTURES

Q = Quantity


def test_normalize_kn_mm_to_si() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_bom_kN.tsv")
    d = normalize(
        t,
        [
            MappedColumn(0, Q.TIME, "s"),
            MappedColumn(1, Q.FORCE, "kN"),
            MappedColumn(2, Q.DISPLACEMENT, "mm"),
        ],
    )
    raw = t.columns[1].values
    np.testing.assert_allclose(d.columns[Q.FORCE], raw * 1000)
    np.testing.assert_allclose(d.columns[Q.DISPLACEMENT], t.columns[2].values / 1000)
    assert {c.to_unit for c in d.conversions} == {"s", "N", "m"}


def test_percent_strain_becomes_fraction() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_strain_percent.txt")
    d = normalize(
        t, [MappedColumn(0, Q.ENGINEERING_STRAIN, "%"), MappedColumn(1, Q.NOMINAL_STRESS, "MPa")]
    )
    np.testing.assert_allclose(d.columns[Q.ENGINEERING_STRAIN], t.columns[0].values / 100)
    np.testing.assert_allclose(d.columns[Q.NOMINAL_STRESS], t.columns[1].values * 1e6)


def test_micro_and_milli_units() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_chinese_inline_units.csv")
    d = normalize(t, [MappedColumn(1, Q.FORCE, "mN"), MappedColumn(2, Q.DISPLACEMENT, "μm")])
    np.testing.assert_allclose(d.columns[Q.FORCE], t.columns[1].values * 1e-3)
    np.testing.assert_allclose(d.columns[Q.DISPLACEMENT], t.columns[2].values * 1e-6)


def test_celsius_to_kelvin() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_dma.csv")
    d = normalize(t, [MappedColumn(0, Q.TEMPERATURE, "°C")])
    assert d.columns[Q.TEMPERATURE][0] == pytest.approx(-70 + 273.15)


@pytest.mark.parametrize(
    "mapping",
    [
        [MappedColumn(1, Q.NOMINAL_STRESS, "N/m")],  # wrong dimension
        [MappedColumn(1, Q.FORCE, "")],  # no unit
        [MappedColumn(0, Q.STRETCH, "%")],  # stretch cannot be percent
        [MappedColumn(0, Q.TIME, "s"), MappedColumn(1, Q.TIME, "s")],  # duplicate
        [MappedColumn(9, Q.TIME, "s")],  # no such column
        [],
    ],
)
def test_invalid_mappings(mapping: list[MappedColumn]) -> None:
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_strain_percent.txt")
    with pytest.raises(MappingError):
        normalize(t, mapping)


def _uniaxial_data():
    (t,) = read_file(FIXTURES / "SYNTH_uniaxial_gbk_chinese.csv")
    return t, normalize(
        t,
        [
            MappedColumn(0, Q.TIME, "s"),
            MappedColumn(1, Q.FORCE, "N"),
            MappedColumn(2, Q.DISPLACEMENT, "mm"),
        ],
    )


def test_clean_synthetic_file_has_no_warnings() -> None:
    t, d = _uniaxial_data()
    issues = check_quality(d, TestType.UNIAXIAL, t)
    assert summarize_issues(issues)["warning"] == 0, issues
    assert summarize_issues(issues)["error"] == 0


def _csv(rows: list[tuple[float, ...]], header: str) -> bytes:
    return (header + "\n" + "\n".join(",".join(f"{v:g}" for v in r) for r in rows) + "\n").encode()


def _uniaxial_rows(n: int = 200):
    lam = np.linspace(1, 3, n)
    f = 10 * (lam - 1)
    return list(zip(np.linspace(0, 100, n), f, (lam - 1) * 20, strict=True)), lam


def _check(rows, test_type=TestType.UNIAXIAL):
    (t,) = read_bytes(_csv(rows, "Time (s),Force (N),Displacement (mm)"), "x.csv")
    d = normalize(
        t,
        [
            MappedColumn(0, Q.TIME, "s"),
            MappedColumn(1, Q.FORCE, "N"),
            MappedColumn(2, Q.DISPLACEMENT, "mm"),
        ],
    )
    return {i.code for i in check_quality(d, test_type, t)}


def test_flags_no_break_slip_offset_saturation_jump_time() -> None:
    rows, _ = _uniaxial_rows()
    codes = _check(rows)
    assert "break_not_found" in codes  # no fracture drop in this record
    r = [list(x) for x in rows]
    r[100][1] *= 0.8  # 20 % drop during loading → slip
    assert "possible_slip" in _check([tuple(x) for x in r])
    r = [(a, b + 3.0, c) for a, b, c in rows]  # preload
    assert "baseline_offset" in _check(r)
    r = [list(x) for x in rows]
    for k in range(150, 200):
        r[k][1] = r[150][1]  # clipped
    assert "saturation" in _check([tuple(x) for x in r])
    r = [list(x) for x in rows]
    r[60][0] = r[59][0] - 1  # time goes backwards
    assert "time_not_monotonic" in _check([tuple(x) for x in r])
    r = [list(x) for x in rows]
    r[80][2] += 15  # displacement spike
    assert "signal_jump" in _check([tuple(x) for x in r])
    r = list(rows)
    r.insert(50, r[49])
    assert "duplicate_rows" in _check(r)


def test_unit_suspect_and_too_few_points() -> None:
    rows, _ = _uniaxial_rows(10)
    big = [(a, b * 1e6, c) for a, b, c in rows]
    codes = _check(big)
    assert "unit_suspect" in codes
    assert "too_few_points" in codes


def test_non_numeric_and_missing_reported() -> None:
    data = b"Time (s),Force (N),Displacement (mm)\n" + b"\n".join(
        f"{i},{'ERR' if i == 5 else ('' if i == 7 else i)},{i}".encode() for i in range(40)
    )
    (t,) = read_bytes(data, "x.csv")
    d = normalize(
        t,
        [
            MappedColumn(0, Q.TIME, "s"),
            MappedColumn(1, Q.FORCE, "N"),
            MappedColumn(2, Q.DISPLACEMENT, "mm"),
        ],
    )
    codes = {i.code for i in check_quality(d, TestType.UNIAXIAL, t)}
    assert {"non_numeric", "missing_values"} <= codes


def test_cyclic_segmentation_checks() -> None:
    (t,) = read_file(FIXTURES / "SYNTH_cyclic_steps.csv")
    d = normalize(
        t, [MappedColumn(1, Q.STRETCH, "dimensionless"), MappedColumn(2, Q.NOMINAL_STRESS, "MPa")]
    )
    assert not [i for i in check_quality(d, TestType.CYCLIC, t) if i.severity == "error"]
    d2 = normalize(t, [MappedColumn(2, Q.NOMINAL_STRESS, "MPa")])
    assert "cycle_no_strain" in {i.code for i in check_quality(d2, TestType.CYCLIC, t)}


def test_quality_never_modifies_data() -> None:
    t, d = _uniaxial_data()
    before = {q: v.copy() for q, v in d.columns.items()}
    check_quality(d, TestType.UNIAXIAL, t)
    for q, v in d.columns.items():
        np.testing.assert_array_equal(v, before[q])


def test_corrections_keep_original_and_record() -> None:
    x = np.linspace(0, 10, 101)
    y = 2.0 + 0.5 * x + np.sin(x)
    y0 = y.copy()
    _, rec = zero_offset(y, 5, "tester")
    np.testing.assert_array_equal(y, y0)
    assert rec.algorithm == "zero_offset"
    assert rec.operator == "tester"
    assert rec.params["offset"] == pytest.approx(np.mean(y[:5]))
    b, rec = linear_baseline(x, 2.0 + 0.5 * x, 0, 101, "tester")
    np.testing.assert_allclose(b, 0, atol=1e-9)
    _, rec = smooth(y, "savgol", 11, "tester")
    assert rec.params == {"window": 11, "polyorder": 3}
    m, _ = smooth(np.ones(20), "moving_average", 5, "tester")
    np.testing.assert_allclose(m, 1.0)
    d, rec = shift_to_contact(
        np.arange(10.0), np.array([0, 0, 0.1, 1, 2, 3, 4, 5, 6, 7.0]), 0.5, "tester"
    )
    assert d[3] == 0
    assert rec.params["contact_index"] == 3
    with pytest.raises(DataIOError):
        smooth(y, "savgol", 4, "tester")
    with pytest.raises(DataIOError):
        smooth(y, "fft", 5, "tester")
    with pytest.raises(DataIOError):
        shift_to_contact(np.arange(3.0), np.zeros(3), 1.0, "tester")


def test_metadata_requirements() -> None:
    meta = ExperimentMetadata(material_name="SYN", test_type=TestType.UNIAXIAL)
    assert set(missing_fields(meta, {Q.FORCE, Q.DISPLACEMENT})) == {
        "width_m",
        "thickness_m",
        "gauge_length_m",
    }
    assert missing_fields(meta, {Q.NOMINAL_STRESS, Q.STRETCH}) == []
    ps = ExperimentMetadata(material_name="SYN", test_type=TestType.PURE_SHEAR_NOTCHED)
    assert "height_m" in missing_fields(ps, {Q.NOMINAL_STRESS, Q.STRETCH})
    assert "notch_length_m" in required_fields(TestType.PURE_SHEAR_NOTCHED, set())
    assert required_fields(TestType.PEEL_TROUSER, set())[-1] == "thickness_m"
    assert required_fields(TestType.PEEL_T, set())[-1] == "width_m"
    zero = ExperimentMetadata(
        material_name="SYN", width_m=0.0, thickness_m=1e-3, gauge_length_m=0.02
    )
    assert missing_fields(zero, {Q.FORCE, Q.DISPLACEMENT}) == ["width_m"]
