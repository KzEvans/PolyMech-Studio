import os
import sqlite3
import stat
from pathlib import Path

import numpy as np
import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from polymech_database.db import (
    Database,
    alembic_config,
    current_revision,
    head_revision,
    make_engine,
    migrate,
)
from polymech_database.errors import MigrationError, StorageError
from polymech_database.models import AnalysisRun, LiteratureSource, MechanicalProperty, RawDataFile
from polymech_database.repository import (
    PropertyValue,
    add_literature_value,
    add_raw_file,
    compare_runs,
    create_experiment,
    create_specimen,
    get_or_create_material,
    list_runs,
    record_analysis,
    save_profile,
    set_mappings,
)
from polymech_database.storage import read_archived, read_curves, write_curves


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "data")


def _experiment(s):
    m = get_or_create_material(s, "SYN-A", polymer_type="synthetic")
    sp = create_specimen(s, m, "S1", thickness_m=1e-3, width_m=2e-3, gauge_length_m=0.02)
    return create_experiment(s, sp, "uniaxial", instrument="SYNTH")


def test_migration_creates_schema_and_is_idempotent(tmp_path: Path) -> None:
    d = Database(tmp_path / "d")
    assert current_revision(d.engine) == head_revision()
    tables = set(inspect(d.engine).get_table_names())
    assert {
        "material",
        "analysis_run",
        "mechanical_property",
        "raw_data_file",
        "origin_job",
    } <= tables
    d.dispose()
    again = Database(tmp_path / "d")
    assert again.last_backup is None


def test_failed_migration_reports_backup(tmp_path: Path) -> None:
    d = Database(tmp_path / "d")
    cfg = alembic_config()
    with d.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.stamp(cfg, "base")  # pretend the schema is older than it is
    with d.engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('0000deadbeef')")
    d.dispose()
    with pytest.raises(MigrationError, match="备份"):
        Database(tmp_path / "d")
    backups = list((tmp_path / "d" / "backups").glob("*.sqlite"))
    assert len(backups) == 1


def test_migration_backup_includes_committed_wal_data(tmp_path: Path) -> None:
    path = tmp_path / "polymech.sqlite"
    engine = make_engine(path)
    try:
        cfg = alembic_config()
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "b7c1d2e3f4a5")
            conn.exec_driver_sql("CREATE TABLE committed_before_upgrade(value TEXT)")
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO committed_before_upgrade VALUES ('saved')")
        assert path.with_suffix(".sqlite-wal").stat().st_size > 0
        backup = migrate(engine, path, tmp_path / "backups")
        assert backup is not None
        with sqlite3.connect(backup) as copied:
            assert copied.execute("SELECT value FROM committed_before_upgrade").fetchall() == [
                ("saved",)
            ]
            assert copied.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "b7c1d2e3f4a5",
            )
        assert current_revision(engine) == head_revision()
    finally:
        engine.dispose()


def test_raw_archive_is_readonly_deduplicated_and_verified(db: Database) -> None:
    payload = "时间,力\n0,0\n1,1\n".encode("gbk")
    with db.session() as s:
        a = add_raw_file(s, db.data_dir, payload, "/Users/x/secret/raw.csv")
        b = add_raw_file(s, db.data_dir, payload, "raw-copy.csv")
        assert a.sha256 == b.sha256
        assert a.archive_path == b.archive_path
        assert a.original_name == "raw.csv"  # no directories stored
    path = db.data_dir / a.archive_path
    assert not os.access(path, os.W_OK) or not (path.stat().st_mode & stat.S_IWUSR)
    assert read_archived(db.data_dir, a.archive_path, a.sha256) == payload
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(StorageError):
        read_archived(db.data_dir, a.archive_path, a.sha256)
    with pytest.raises(StorageError), db.session() as s:
        add_raw_file(s, db.data_dir, payload, "raw.csv")


def test_curves_roundtrip_with_ragged_columns(tmp_path: Path) -> None:
    write_curves(tmp_path, "curves/x.parquet", {"a": np.arange(5.0), "b": np.arange(3.0)})
    out = read_curves(tmp_path, "curves/x.parquet")
    np.testing.assert_array_equal(out["a"], np.arange(5.0))
    np.testing.assert_array_equal(out["b"], np.arange(3.0))
    assert not list((tmp_path / "curves").glob(".tmp-*"))


def _record(s, db, exp, params, value, status="ok"):
    return record_analysis(
        s,
        db.data_dir,
        experiment=exp,
        method="uniaxial",
        params=params,
        inputs={"raw_file_sha256": "abc"},
        input_arrays={"stretch": np.linspace(1, 2, 5)},
        result={"initial_modulus_pa": value, "nan_value": float("nan")},
        flags=[],
        curves={"stretch": np.linspace(1, 2, 5)},
        software_version="0.1.0",
        status=status,
        properties=[
            PropertyValue("elastic_modulus", value, conditions={"fit_range": params["range"]})
        ],
    )


def test_analysis_runs_are_append_only_versions(db: Database) -> None:
    with db.session() as s:
        exp = _experiment(s)
        r1 = _record(s, db, exp, {"range": [1.0, 1.05]}, 1.0e6)
        r2 = _record(s, db, exp, {"range": [1.0, 1.02]}, 1.1e6)
        assert (r1.version, r2.version) == (1, 2)
        assert r1.input_sha256 != r2.input_sha256  # params are part of the input hash
        assert r1.result["nan_value"] is None
        diff = compare_runs(r1, r2)
        assert diff["same_input_data"]
        assert diff["params"]["range"] == ([1.0, 1.05], [1.0, 1.02])
        assert diff["result"]["initial_modulus_pa"] == (1.0e6, 1.1e6)
        exp_id = exp.id
    with db.session() as s:
        runs = list_runs(s, exp_id, "uniaxial")
        assert [r.result["initial_modulus_pa"] for r in runs] == [1.0e6, 1.1e6]
        props = s.scalars(select(MechanicalProperty)).all()
        assert len(props) == 2
        assert all(p.unit == "Pa" for p in props)
        assert read_curves(db.data_dir, runs[0].curves_path)["stretch"][-1] == 2.0


def test_same_input_gives_same_hashes(db: Database) -> None:
    with db.session() as s:
        exp = _experiment(s)
        a = _record(s, db, exp, {"range": [1.0, 1.05]}, 1.0e6)
        b = _record(s, db, exp, {"range": [1.0, 1.05]}, 1.0e6)
        assert (a.input_sha256, a.result_sha256) == (b.input_sha256, b.result_sha256)


def test_transaction_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(RuntimeError), db.session() as s:
        _experiment(s)
        raise RuntimeError("boom")
    with db.session() as s:
        assert s.scalars(select(AnalysisRun)).all() == []
        assert get_or_create_material(s, "SYN-A").id is not None  # created fresh now


def test_property_needs_exactly_one_source(db: Database) -> None:
    with pytest.raises(IntegrityError), db.session() as s:
        m = get_or_create_material(s, "X")
        s.add(
            MechanicalProperty(material_id=m.id, quantity="elastic_modulus", value=1.0, unit="Pa")
        )
        s.flush()


def test_literature_values_and_extraction_method(db: Database) -> None:
    with db.session() as s:
        src = LiteratureSource(title="T", authors="A", year=2024, kind="thesis")
        s.add(src)
        m = get_or_create_material(s, "LIT-1", origin="literature")
        s.flush()
        lm = add_literature_value(
            s,
            source=src,
            material=m,
            extraction_method="reported",
            page="78",
            values=[
                PropertyValue(
                    "fatigue_threshold",
                    None,
                    lower_bound=100.0,
                    conditions={"G_definition": "G_max"},
                )
            ],
        )
        assert lm.properties[0].lower_bound == 100.0
        assert lm.properties[0].value is None
    with pytest.raises(IntegrityError), db.session() as s:
        src = s.scalars(select(LiteratureSource)).one()
        m = get_or_create_material(s, "LIT-1")
        add_literature_value(
            s, source=src, material=m, extraction_method="guessed", page="1", values=[]
        )


def test_mappings_and_profiles(db: Database) -> None:
    with db.session() as s:
        rf = add_raw_file(s, db.data_dir, b"a,b\n1,2\n", "x.csv")
        set_mappings(s, rf, [{"column_index": 0, "header": "a", "quantity": "time", "unit": "s"}])
        set_mappings(s, rf, [{"column_index": 1, "header": "b", "quantity": "force", "unit": "N"}])
        assert [m.quantity for m in rf.mappings] == ["force"]
        p = save_profile(s, "UTM", "SYNTH", [{"header": "b", "quantity": "force", "unit": "N"}])
        p2 = save_profile(s, "UTM", "SYNTH2", [])
        assert p.id == p2.id
        assert s.get(RawDataFile, rf.id) is not None
