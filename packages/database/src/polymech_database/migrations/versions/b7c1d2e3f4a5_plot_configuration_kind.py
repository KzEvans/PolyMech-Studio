"""plot configuration kind (saved figure vs user style template)

Revision ID: b7c1d2e3f4a5
Revises: aed95c8c3043
Create Date: 2026-10-26 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1d2e3f4a5"
down_revision: str | None = "aed95c8c3043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plot_configuration") as b:
        b.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="config")
        )


def downgrade() -> None:
    with op.batch_alter_table("plot_configuration") as b:
        b.drop_column("kind")
