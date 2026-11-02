"""Alembic environment: uses the connection passed by polymech_database.db.migrate, or
sqlalchemy.url from the config for CLI autogenerate."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from polymech_database.models import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "sqlite://")
    with engine.connect() as c:
        context.configure(connection=c, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()
