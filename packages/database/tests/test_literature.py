"""Literature import (SPEC §7.3): validation, SI conversion, idempotency, and the curated file."""

import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from polymech_database.db import Database
from polymech_database.literature import LiteratureImportError, import_literature, validate
from polymech_database.models import LiteratureMeasurement, Material, MechanicalProperty
from polymech_database.repository import get_or_create_material

MINI = {
    "format": "polymech-literature/1",
    "sources": {"s": {"title": "SYNTHETIC source", "authors": "A", "year": 2024, "kind": "thesis"}},
    "materials": {"LIT-SYN": {"polymer_type": "synthetic"}},
    "records": [
        {
            "source": "s",
            "material": "LIT-SYN",
            "quantity": "fracture_toughness",
            "value": 91,
            "unit": "kJ/m^2",
            "reported_text": "91 kJ m−2",
            "extraction_method": "reported",
            "page": "88",
            "figure": "图 1",
            "test_type": "pure_shear",
        },
        {
            "source": "s",
            "material": "LIT-SYN",
            "quantity": "glass_transition_temperature",
            "value": -39,
            "unit": "°C",
            "reported_text": "−39 °C",
            "extraction_method": "reported",
            "page": "70",
            "table": "表 1",
            "test_type": "dma",
            "conditions": {"tg_definition": "tan_delta_peak", "frequency_hz": 1.0},
        },
        {
            "source": "s",
            "material": "LIT-SYN",
            "quantity": "elongation_at_break",
            "value": 320,
            "unit": "%",
            "reported_text": "320",
            "extraction_method": "reported",
            "page": "70",
        },
        {
            "source": "s",
            "material": "LIT-SYN",
            "quantity": "fatigue_threshold",
            "lower_bound": 2718,
            "unit": "J/m^2",
            "reported_text": "2718",
            "extraction_method": "reported",
            "page": "91",
        },
    ],
}


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "data")


def _mut(**changes):  # type: ignore[no-untyped-def]
    p = copy.deepcopy(MINI)
    p["records"][0].update(changes)
    return p


def test_import_converts_to_si_and_keeps_reported_form(db: Database) -> None:
    with db.session() as s:
        out = import_literature(s, MINI)
        assert (out.records_added, out.materials_created) == (4, 1)
        props = {p.quantity: p for p in s.scalars(select(MechanicalProperty))}
        assert props["fracture_toughness"].value == pytest.approx(91e3)
        assert props["fracture_toughness"].unit == "J/m^2"
        assert props["glass_transition_temperature"].value == pytest.approx(234.15)
        assert props["elongation_at_break"].value == pytest.approx(3.2)
        assert props["fatigue_threshold"].value is None
        assert props["fatigue_threshold"].lower_bound == pytest.approx(2718)
        c = props["fracture_toughness"].conditions
        assert c["reported_text"] == "91 kJ m−2" and c["reported_unit"] == "kJ/m^2"
        lm = props["glass_transition_temperature"].literature_measurement
        assert (lm.page, lm.table, lm.extraction_method) == ("70", "表 1", "reported")
        assert s.scalar(select(Material).where(Material.name == "LIT-SYN")).origin == "literature"


def test_reimport_is_idempotent(db: Database) -> None:
    with db.session() as s:
        import_literature(s, MINI)
    with db.session() as s:
        out = import_literature(s, MINI)
        assert (out.records_added, out.records_skipped, out.materials_created) == (0, 4, 0)
        assert len(s.scalars(select(LiteratureMeasurement)).all()) == 4


def test_corrected_record_updates_in_place(db: Database) -> None:
    with db.session() as s:
        import_literature(s, MINI)
    fixed = copy.deepcopy(MINI)
    fixed["records"][0]["conditions"] = {"method": "pure_shear", "height_m": 0.01}
    fixed["records"][0]["notes"] = "corrected"
    with db.session() as s:
        out = import_literature(s, fixed)
        assert (out.records_added, out.records_updated, out.records_skipped) == (0, 1, 3)
        p = s.scalars(
            select(MechanicalProperty).where(MechanicalProperty.quantity == "fracture_toughness")
        ).one()
        assert p.conditions["method"] == "pure_shear"
        assert p.literature_measurement.notes == "corrected"


def test_duplicate_citation_in_file_rejected() -> None:
    dup = copy.deepcopy(MINI)
    dup["records"].append(copy.deepcopy(dup["records"][0]))
    with pytest.raises(LiteratureImportError, match="重复登记"):
        validate(dup)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"extraction_method": "guessed"}, "extraction_method"),
        ({"page": ""}, "页码"),
        ({"reported_text": ""}, "reported_text"),
        ({"extraction_method": "digitized", "figure": ""}, "图号"),
        ({"quantity": "made_up"}, "未知物理量"),
        ({"unit": "N"}, "单位"),
        ({"value": None}, "至少给出一个"),
        ({"value": "91"}, "数字"),
        ({"source": "nope"}, "未定义的文献"),
        ({"test_type": "bogus"}, "测试类型"),
    ],
)
def test_invalid_records_rejected_before_any_write(db: Database, changes, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(LiteratureImportError, match=message), db.session() as s:
        import_literature(s, _mut(**changes))
    with db.session() as s:
        assert s.scalars(select(MechanicalProperty)).all() == []


def test_literature_material_never_merges_into_experiment_material(db: Database) -> None:
    with db.session() as s:
        get_or_create_material(s, "LIT-SYN")  # origin defaults to experiment
    with pytest.raises(LiteratureImportError, match="实验材料"), db.session() as s:
        import_literature(s, MINI)


def test_wrong_format_rejected() -> None:
    with pytest.raises(LiteratureImportError, match="格式"):
        validate({"format": "x"})
