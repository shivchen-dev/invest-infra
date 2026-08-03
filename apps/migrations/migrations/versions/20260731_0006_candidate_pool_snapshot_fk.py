"""Add the candidate-pool input snapshot foreign key.

Revision ID: 20260731_0006
Revises: 20260731_0005
Create Date: 2026-07-31
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260731_0006"
down_revision: str | None = "20260731_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_cpool_runs_snapshot_id"


def upgrade() -> None:
    op.create_foreign_key(
        _FK_NAME,
        "candidate_pool_runs",
        "input_snapshots",
        ["input_snapshot_id"],
        ["id"],
        source_schema="analytics",
        referent_schema="analytics",
    )


def downgrade() -> None:
    op.drop_constraint(
        _FK_NAME,
        "candidate_pool_runs",
        schema="analytics",
        type_="foreignkey",
    )
