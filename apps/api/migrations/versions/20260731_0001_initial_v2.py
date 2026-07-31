"""initial v2 schemas and tables

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31

Greenfield baseline migration for invest-infra V2.
Creates the four frozen schemas (raw/core/analytics/ops) and the
minimum tables required for the first vertical slice:

- core.instruments
- raw.provider_batches
- ops.pipeline_runs

No legacy compatibility, no shadow renames, no data backfill.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    # core.instruments
    op.create_table(
        "instruments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("instrument_type", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="unknown"),
        sa.Column("underlying_index", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("provider_symbol_map", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        schema="core",
    )
    op.create_index(
        "uq_instruments_symbol_exchange_active",
        "instruments",
        ["symbol", "exchange"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("delist_date IS NULL"),
    )
    op.create_index("ix_instruments_exchange", "instruments", ["exchange"], schema="core")

    # raw.provider_batches
    op.create_table(
        "provider_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("request_params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("raw_payload_uri", sa.Text(), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_provider_batches"),
        schema="raw",
    )
    op.create_index(
        "uq_provider_batches_provider_dataset_request",
        "provider_batches",
        ["provider_key", "dataset_key", "request_key"],
        unique=True,
        schema="raw",
    )
    op.create_index("ix_provider_batches_provider_dataset", "provider_batches", ["provider_key", "dataset_key"], schema="raw")
    op.create_index("ix_provider_batches_requested_at", "provider_batches", ["requested_at"], schema="raw")
    op.create_index("ix_provider_batches_status", "provider_batches", ["status"], schema="raw")

    # ops.pipeline_runs
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dagster_run_id", sa.Text(), nullable=True),
        sa.Column("job_key", sa.String(length=120), nullable=False),
        sa.Column("partition_key", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_runs"),
        schema="ops",
    )
    op.create_index("ix_pipeline_runs_job_key", "pipeline_runs", ["job_key"], schema="ops")
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"], schema="ops")
    op.create_index("ix_pipeline_runs_dagster_run_id", "pipeline_runs", ["dagster_run_id"], schema="ops")

    # Status vocabulary constraint
    op.execute(
        sa.text(
            'ALTER TABLE "ops"."pipeline_runs" '
            "ADD CONSTRAINT ck_pipeline_runs_status_valid "
            "CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'partial', 'cancelled'))"
        )
    )

    # Trigger for updated_at
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION "ops".set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at := now();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_pipeline_runs_set_updated_at
            BEFORE UPDATE ON "ops"."pipeline_runs"
            FOR EACH ROW
            EXECUTE FUNCTION "ops".set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP TRIGGER IF EXISTS trg_pipeline_runs_set_updated_at ON "ops"."pipeline_runs"'))
    op.execute(sa.text('DROP FUNCTION IF EXISTS "ops".set_updated_at()'))
    op.execute(sa.text('ALTER TABLE "ops"."pipeline_runs" DROP CONSTRAINT IF EXISTS ck_pipeline_runs_status_valid'))

    op.drop_index("ix_pipeline_runs_dagster_run_id", table_name="pipeline_runs", schema="ops")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs", schema="ops")
    op.drop_index("ix_pipeline_runs_job_key", table_name="pipeline_runs", schema="ops")
    op.drop_table("pipeline_runs", schema="ops")

    op.drop_index("ix_provider_batches_status", table_name="provider_batches", schema="raw")
    op.drop_index("ix_provider_batches_requested_at", table_name="provider_batches", schema="raw")
    op.drop_index("ix_provider_batches_provider_dataset", table_name="provider_batches", schema="raw")
    op.drop_index("uq_provider_batches_provider_dataset_request", table_name="provider_batches", schema="raw")
    op.drop_table("provider_batches", schema="raw")

    op.drop_index("ix_instruments_exchange", table_name="instruments", schema="core")
    op.drop_index("uq_instruments_symbol_exchange_active", table_name="instruments", schema="core")
    op.drop_table("instruments", schema="core")

    op.execute("DROP SCHEMA IF EXISTS ops")
    op.execute("DROP SCHEMA IF EXISTS analytics")
    op.execute("DROP SCHEMA IF EXISTS core")
    op.execute("DROP SCHEMA IF EXISTS raw")
