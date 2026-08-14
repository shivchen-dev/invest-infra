"""Stage 4D external workflow integration persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0019"
down_revision: str | None = "20260812_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS integration"))
    op.create_table(
        "external_workflow_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("producer", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("producer_status", sa.String(24), nullable=False),
        sa.Column("intake_status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_external_workflow_runs"),
        sa.CheckConstraint("length(producer) > 0", name="producer_nonempty"),
        sa.CheckConstraint("length(schema_version) > 0", name="schema_version_nonempty"),
        sa.CheckConstraint("length(producer_status) > 0", name="producer_status_nonempty"),
        sa.CheckConstraint("length(intake_status) > 0", name="intake_status_nonempty"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        schema="integration",
    )
    op.create_index(
        "ix_external_workflow_runs_producer_status",
        "external_workflow_runs",
        ["producer_status"],
        schema="integration",
    )
    op.create_index(
        "ix_external_workflow_runs_intake_status",
        "external_workflow_runs",
        ["intake_status"],
        schema="integration",
    )
    op.create_index(
        "ix_external_workflow_runs_started_at",
        "external_workflow_runs",
        ["started_at"],
        schema="integration",
    )
    op.create_table(
        "external_artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("logical_uri", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.PrimaryKeyConstraint("artifact_id", name="pk_external_artifacts"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["integration.external_workflow_runs.run_id"],
            name="fk_external_artifacts_run_id_external_workflow_runs",
        ),
        sa.UniqueConstraint("run_id", "logical_uri", name="uq_external_artifacts_run_uri"),
        sa.CheckConstraint("length(logical_uri) > 0", name="logical_uri_nonempty"),
        sa.CheckConstraint("length(content_hash) = 64", name="content_hash_len64"),
        sa.CheckConstraint("length(media_type) > 0", name="media_type_nonempty"),
        sa.CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        schema="integration",
    )
    op.create_index(
        "ix_external_artifacts_run_id", "external_artifacts", ["run_id"], schema="integration"
    )
    op.create_index(
        "ix_external_artifacts_content_hash",
        "external_artifacts",
        ["content_hash"],
        schema="integration",
    )
    op.create_table(
        "external_observations",
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source_uri", sa.String(512), nullable=False),
        sa.Column("producer", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("admission_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column(
            "metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.PrimaryKeyConstraint("observation_id", name="pk_external_observations"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["integration.external_workflow_runs.run_id"],
            name="fk_external_observations_run_id_external_workflow_runs",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["integration.external_artifacts.artifact_id"],
            name="fk_external_observations_artifact_id_external_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_external_observations_instrument_id_core_instruments",
        ),
        sa.CheckConstraint("length(source_uri) > 0", name="source_uri_nonempty"),
        sa.CheckConstraint("length(producer) > 0", name="producer_nonempty"),
        sa.CheckConstraint("length(admission_status) > 0", name="admission_status_nonempty"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        schema="integration",
    )
    op.create_index(
        "ix_external_observations_run_id", "external_observations", ["run_id"], schema="integration"
    )
    op.create_index(
        "ix_external_observations_admission_status",
        "external_observations",
        ["admission_status"],
        schema="integration",
    )
    op.create_index(
        "ix_external_observations_as_of", "external_observations", ["as_of"], schema="integration"
    )


def downgrade() -> None:
    for name, table in (
        ("ix_external_observations_as_of", "external_observations"),
        ("ix_external_observations_admission_status", "external_observations"),
        ("ix_external_observations_run_id", "external_observations"),
    ):
        op.drop_index(name, table_name=table, schema="integration")
    op.drop_table("external_observations", schema="integration")
    for name, table in (
        ("ix_external_artifacts_content_hash", "external_artifacts"),
        ("ix_external_artifacts_run_id", "external_artifacts"),
    ):
        op.drop_index(name, table_name=table, schema="integration")
    op.drop_table("external_artifacts", schema="integration")
    for name in (
        "ix_external_workflow_runs_started_at",
        "ix_external_workflow_runs_intake_status",
        "ix_external_workflow_runs_producer_status",
    ):
        op.drop_index(name, table_name="external_workflow_runs", schema="integration")
    op.drop_table("external_workflow_runs", schema="integration")
    op.execute(sa.text("DROP SCHEMA IF EXISTS integration"))
