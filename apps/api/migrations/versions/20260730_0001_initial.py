"""initial schemas and tables

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    op.create_table(
        "instruments",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("instrument_type", sa.String(length=24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("symbol", name="pk_instruments"),
        schema="core",
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_runs"),
        schema="app",
    )
    op.create_index("ix_pipeline_runs_job_name", "pipeline_runs", ["job_name"], schema="app")
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"], schema="app")


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs", schema="app")
    op.drop_index("ix_pipeline_runs_job_name", table_name="pipeline_runs", schema="app")
    op.drop_table("pipeline_runs", schema="app")
    op.drop_table("instruments", schema="core")
    op.execute("DROP SCHEMA IF EXISTS app")
    op.execute("DROP SCHEMA IF EXISTS core")
