"""SQLAlchemy models (SPEC §7.1). Every numeric property carries unit, conditions and source.

Physical values are stored in SI (unit column records which); analysis runs are append-only
versions — re-analysis never overwrites an earlier run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite drops time zones; store UTC and always hand back aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class Material(Base):
    __tablename__ = "material"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    polymer_type: Mapped[str] = mapped_column(String(100), default="")  # e.g. block copolymer
    structure_type: Mapped[str] = mapped_column(
        String(100), default=""
    )  # e.g. pentablock, nanocomposite
    phase_structure: Mapped[str] = mapped_column(
        String(100), default=""
    )  # e.g. spheres, co-continuous
    block_count: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(20), default="experiment")  # experiment | literature
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    components: Mapped[list[MaterialComponent]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )
    batches: Mapped[list[SampleBatch]] = relationship(back_populates="material")


class MaterialComponent(Base):
    """A constituent or polymer block (SPEC: MaterialComposition / PolymerBlock)."""

    __tablename__ = "material_component"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    name: Mapped[str] = mapped_column(String(100))  # e.g. polystyrene, PEHA
    role: Mapped[str] = mapped_column(
        String(30), default=""
    )  # glassy | rubbery | filler | crosslinker
    block_label: Mapped[str] = mapped_column(String(30), default="")  # e.g. S, EHA
    position: Mapped[int | None] = mapped_column(Integer)  # order along the chain for blocks
    molar_mass_kg_mol: Mapped[float | None] = mapped_column(Float)
    fraction: Mapped[float | None] = mapped_column(Float)
    fraction_basis: Mapped[str] = mapped_column(String(20), default="")  # mass | volume | mole
    material: Mapped[Material] = relationship(back_populates="components")


class SampleBatch(Base):
    __tablename__ = "sample_batch"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    label: Mapped[str] = mapped_column(String(100))
    prepared_on: Mapped[str] = mapped_column(String(20), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    material: Mapped[Material] = relationship(back_populates="batches")
    __table_args__ = (UniqueConstraint("material_id", "label"),)


class Specimen(Base):
    __tablename__ = "specimen"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("sample_batch.id"))
    label: Mapped[str] = mapped_column(String(100))
    thickness_m: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float | None] = mapped_column(Float)
    gauge_length_m: Mapped[float | None] = mapped_column(Float)
    height_m: Mapped[float | None] = mapped_column(Float)  # pure-shear H0
    notch_length_m: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")


class ExperimentProtocol(Base):
    """Reusable test conditions (rate, frequency, geometry type, standard)."""

    __tablename__ = "experiment_protocol"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    test_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Experiment(Base):
    __tablename__ = "experiment"
    id: Mapped[int] = mapped_column(primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimen.id"))
    protocol_id: Mapped[int | None] = mapped_column(ForeignKey("experiment_protocol.id"))
    test_type: Mapped[str] = mapped_column(String(40))
    instrument: Mapped[str] = mapped_column(String(200), default="")
    test_date: Mapped[str] = mapped_column(String(20), default="")
    temperature_k: Mapped[float | None] = mapped_column(Float)
    stretch_rate_per_s: Mapped[float | None] = mapped_column(Float)
    cycle_frequency_hz: Mapped[float | None] = mapped_column(Float)
    precycles: Mapped[int | None] = mapped_column(Integer)
    fixture: Mapped[str] = mapped_column(String(200), default="")
    operator: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    specimen: Mapped[Specimen] = relationship()
    raw_files: Mapped[list[RawDataFile]] = relationship(back_populates="experiment")
    runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="experiment", order_by="AnalysisRun.id"
    )


class RawDataFile(Base):
    """An archived, read-only original file (content-addressed by SHA-256)."""

    __tablename__ = "raw_data_file"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiment.id"))
    original_name: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    archive_path: Mapped[str] = mapped_column(String(300))  # relative to the data directory
    sheet: Mapped[str | None] = mapped_column(String(100))
    encoding: Mapped[str | None] = mapped_column(String(30))
    delimiter: Mapped[str | None] = mapped_column(String(5))
    preamble_fields: Mapped[dict[str, Any]] = mapped_column(default=dict)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    experiment: Mapped[Experiment | None] = relationship(back_populates="raw_files")
    mappings: Mapped[list[DataColumnMapping]] = relationship(
        back_populates="raw_file", cascade="all, delete-orphan"
    )
    corrections: Mapped[list[DataCorrection]] = relationship(order_by="DataCorrection.id")


class DataColumnMapping(Base):
    __tablename__ = "data_column_mapping"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_file_id: Mapped[int] = mapped_column(ForeignKey("raw_data_file.id"))
    column_index: Mapped[int] = mapped_column(Integer)
    header: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(
        String(60), default="user"
    )  # rules | ai:* | profile:* | user
    confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_by: Mapped[str] = mapped_column(String(100), default="")
    raw_file: Mapped[RawDataFile] = relationship(back_populates="mappings")
    __table_args__ = (UniqueConstraint("raw_file_id", "column_index"),)


class ImportProfileRecord(Base):
    __tablename__ = "import_profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    instrument: Mapped[str] = mapped_column(String(200), default="")
    rules: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DataCorrection(Base):
    __tablename__ = "data_correction"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_file_id: Mapped[int] = mapped_column(ForeignKey("raw_data_file.id"))
    quantity: Mapped[str] = mapped_column(String(40))
    algorithm: Mapped[str] = mapped_column(String(60))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    operator: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(default=True, server_default=true())
    """Deactivated corrections stay as history; only active ones are applied to new runs."""


class AnalysisRun(Base):
    """One immutable analysis version. Re-running creates a new row with version + 1."""

    __tablename__ = "analysis_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiment.id"))
    method: Mapped[str] = mapped_column(String(40))  # uniaxial | cyclic | pure_shear | fatigue ...
    version: Mapped[int] = mapped_column(Integer)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_run.id"))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict)  # raw file ids, mappings, geometry
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)  # scalar results (no arrays)
    flags: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | provisional | failed
    input_sha256: Mapped[str] = mapped_column(String(64))
    result_sha256: Mapped[str] = mapped_column(String(64))
    curves_path: Mapped[str | None] = mapped_column(String(300))  # parquet, relative path
    software_version: Mapped[str] = mapped_column(String(40))
    operator: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="runs")
    properties: Mapped[list[MechanicalProperty]] = relationship(back_populates="analysis_run")
    __table_args__ = (UniqueConstraint("experiment_id", "method", "version"),)


class LiteratureSource(Base):
    __tablename__ = "literature_source"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), default="article")  # article | thesis | book
    institution: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class LiteratureMeasurement(Base):
    """Where in a source a value comes from, and how it was extracted."""

    __tablename__ = "literature_measurement"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("literature_source.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"))
    page: Mapped[str] = mapped_column(String(30), default="")
    figure: Mapped[str] = mapped_column(String(30), default="")
    table: Mapped[str] = mapped_column(String(30), default="")
    extraction_method: Mapped[str] = mapped_column(String(20))  # reported | digitized
    test_type: Mapped[str] = mapped_column(String(40), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[LiteratureSource] = relationship()
    material: Mapped[Material] = relationship()
    properties: Mapped[list[MechanicalProperty]] = relationship(
        back_populates="literature_measurement"
    )
    __table_args__ = (CheckConstraint("extraction_method IN ('reported', 'digitized')"),)


class MechanicalProperty(Base):
    """A value with unit, conditions and exactly one source (analysis run or literature)."""

    __tablename__ = "mechanical_property"
    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("material.id"), index=True)
    quantity: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[float | None] = mapped_column(Float)  # None for bounds-only results
    unit: Mapped[str] = mapped_column(String(20))  # SI unit of `value`
    lower_bound: Mapped[float | None] = mapped_column(Float)
    upper_bound: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    uncertainty_kind: Mapped[str] = mapped_column(String(30), default="")  # sd | se | ci95 ...
    n_replicates: Mapped[int | None] = mapped_column(Integer)
    conditions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_run.id"))
    literature_measurement_id: Mapped[int | None] = mapped_column(
        ForeignKey("literature_measurement.id")
    )
    analysis_run: Mapped[AnalysisRun | None] = relationship(back_populates="properties")
    literature_measurement: Mapped[LiteratureMeasurement | None] = relationship(
        back_populates="properties"
    )
    __table_args__ = (
        CheckConstraint(
            "(analysis_run_id IS NULL) != (literature_measurement_id IS NULL)",
            name="exactly_one_source",
        ),
    )


class ReferenceCitation(Base):
    """Links a material (or report) to a literature source without a numeric value."""

    __tablename__ = "reference_citation"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("literature_source.id"))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("material.id"))
    context: Mapped[str] = mapped_column(Text, default="")


class PlotConfiguration(Base):
    __tablename__ = "plot_configuration"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="config", server_default="config")
    """config: a figure with its data bindings; template: user style template (data ignored)."""
    template_id: Mapped[str] = mapped_column(String(60))
    template_version: Mapped[str] = mapped_column(String(20))
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_run.id"))
    spec: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OriginJob(Base):
    __tablename__ = "origin_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_run_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_run.id"))
    plot_configuration_id: Mapped[int | None] = mapped_column(ForeignKey("plot_configuration.id"))
    bridge_job_id: Mapped[str | None] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    opju_path: Mapped[str | None] = mapped_column(String(300))
    png_path: Mapped[str | None] = mapped_column(String(300))
    error: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[dict[str, Any]] = mapped_column(default=dict)
