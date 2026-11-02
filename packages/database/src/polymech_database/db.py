"""Engine, migrations (Alembic, run at startup) and session handling."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from polymech_database.errors import MigrationError

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
DB_FILENAME = "polymech.sqlite"


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    return cfg


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def migrate(engine: Engine, db_path: Path, backup_dir: Path) -> Path | None:
    """Upgrade to head. An existing database is copied to `backup_dir` first.

    Returns the backup path (None if nothing needed migrating or the DB was new).
    """
    current, head = current_revision(engine), head_revision()
    if current == head:
        return None
    backup: Path | None = None
    if current is not None and db_path.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = backup_dir / f"polymech-{current}-{stamp}.sqlite"
        with (
            closing(sqlite3.connect(db_path)) as source,
            closing(sqlite3.connect(backup)) as target,
        ):
            source.backup(target)
    cfg = alembic_config()
    try:
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    except Exception as e:
        hint = f"迁移前备份：{backup.name}" if backup else "这是新数据库，没有备份"
        raise MigrationError(f"数据库迁移失败（{current} → {head}）：{e}。{hint}") from e
    return backup


class Database:
    """Data directory layout:

    polymech.sqlite        metadata
    raw/ab/<sha256>.<ext>  read-only archived originals
    curves/<run>.parquet   processed curves per analysis run
    backups/               pre-migration copies
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / DB_FILENAME
        self.engine = make_engine(self.db_path)
        self.last_backup = migrate(self.engine, self.db_path, data_dir / "backups")
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transaction scope: commit on success, roll back on any exception."""
        s = self._sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()
