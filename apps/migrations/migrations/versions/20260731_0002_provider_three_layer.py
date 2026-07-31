"""Provider three-layer evidence model (PR-02)

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31

PR-02 replaces the single-layer ``raw.provider_batches`` table with the
three-layer evidence model required by ADR-0003 §6:

- ``raw.provider_requests`` — one row per logical request
  ``(provider_key, dataset_key, request_key)``; multiple attempts may
  share the same request.
- ``raw.provider_attempts`` — one row per network / SDK attempt;
  carries lifecycle status, HTTP status, error_stage / error_code /
  error_message, response_payload_sha256 / json / uri.
- ``raw.provider_batches`` — slimmed down: only successful / partial
  attempts produce a batch row. ``provider_request_id`` and
  ``provider_attempt_id`` replace the old self-contained
  ``provider_key`` / ``dataset_key`` / ``request_key`` columns
  (``provider_key`` / ``dataset_key`` are kept on the batch row for
  query convenience, ``request_key`` is dropped from the batch).

The greenfield v2 baseline (``20260731_0001``) introduced the original
``raw.provider_batches`` shape with no rows; this migration drops that
table and recreates the three tables in the new shape. Foreign keys
are enforced at the database level so a batch row cannot exist without
its parent attempt row, and an attempt row cannot exist without its
parent request row.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0002"
down_revision: str | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the legacy single-layer provider_batches table; it is being
    # replaced by the three-layer evidence model. The v2 baseline had
    # no production rows.
    op.drop_index(
        "ix_provider_batches_status",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_requested_at",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_provider_dataset",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "uq_provider_batches_provider_dataset_request",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_table("provider_batches", schema="raw")

    # raw.provider_requests
    op.create_table(
        "provider_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("request_params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("requested_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_requests"),
        sa.UniqueConstraint(
            "provider_key", "dataset_key", "request_key",
            name="uq_provider_requests_logical_key",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_provider_requests_status_valid",
        ),
        sa.CheckConstraint(
            "length(provider_key) > 0",
            name="ck_provider_requests_provider_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(dataset_key) > 0",
            name="ck_provider_requests_dataset_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(request_key) > 0",
            name="ck_provider_requests_request_key_nonempty",
        ),
        schema="raw",
    )
    op.create_index(
        "ix_provider_requests_status",
        "provider_requests",
        ["status"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_requests_created_at",
        "provider_requests",
        ["created_at"],
        schema="raw",
    )

    # raw.provider_attempts
    op.create_table(
        "provider_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("provider_request_id_text", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_stage", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("response_payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("response_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("response_payload_uri", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_provider_attempts"),
        sa.UniqueConstraint(
            "provider_request_id", "attempt_no",
            name="uq_provider_attempts_request_attempt_no",
        ),
        sa.ForeignKeyConstraint(
            ["provider_request_id"],
            ["raw.provider_requests.id"],
            name="fk_provider_attempts_provider_request_id_raw_provider_requests",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_provider_attempts_status_valid",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_provider_attempts_attempt_no_positive",
        ),
        sa.CheckConstraint(
            "status = 'succeeded' AND response_payload_sha256 IS NOT NULL "
            "OR status <> 'succeeded'",
            name="ck_provider_attempts_succeeded_has_hash",
        ),
        sa.CheckConstraint(
            "status = 'failed' AND error_stage IS NOT NULL AND error_code IS NOT NULL "
            "OR status <> 'failed'",
            name="ck_provider_attempts_failed_has_error",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_provider_attempts_finished_after_started",
        ),
        schema="raw",
    )
    op.create_index(
        "ix_provider_attempts_provider_request_id",
        "provider_attempts",
        ["provider_request_id"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_attempts_status",
        "provider_attempts",
        ["status"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_attempts_started_at",
        "provider_attempts",
        ["started_at"],
        schema="raw",
    )

    # raw.provider_batches (recreated with three-layer FK wiring)
    op.create_table(
        "provider_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_provider_batches"),
        sa.ForeignKeyConstraint(
            ["provider_request_id"],
            ["raw.provider_requests.id"],
            name="fk_provider_batches_provider_request_id_raw_provider_requests",
        ),
        sa.ForeignKeyConstraint(
            ["provider_attempt_id"],
            ["raw.provider_attempts.id"],
            name="fk_provider_batches_provider_attempt_id_raw_provider_attempts",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'partial')",
            name="ck_provider_batches_status_valid",
        ),
        sa.CheckConstraint(
            "record_count >= 0",
            name="ck_provider_batches_record_count_nonneg",
        ),
        sa.CheckConstraint(
            "length(provider_key) > 0",
            name="ck_provider_batches_provider_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(dataset_key) > 0",
            name="ck_provider_batches_dataset_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) > 0",
            name="ck_provider_batches_payload_sha256_nonempty",
        ),
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_provider_attempt_id",
        "provider_batches",
        ["provider_attempt_id"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_provider_request_id",
        "provider_batches",
        ["provider_request_id"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_provider_dataset",
        "provider_batches",
        ["provider_key", "dataset_key"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_status",
        "provider_batches",
        ["status"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_created_at",
        "provider_batches",
        ["created_at"],
        schema="raw",
    )


def downgrade() -> None:
    # Drop provider_batches (recreated in the original baseline shape)
    op.drop_index(
        "ix_provider_batches_created_at",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_status",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_provider_dataset",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_provider_request_id",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_batches_provider_attempt_id",
        table_name="provider_batches",
        schema="raw",
    )
    op.drop_table("provider_batches", schema="raw")

    # Drop provider_attempts
    op.drop_index(
        "ix_provider_attempts_started_at",
        table_name="provider_attempts",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_attempts_status",
        table_name="provider_attempts",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_attempts_provider_request_id",
        table_name="provider_attempts",
        schema="raw",
    )
    op.drop_table("provider_attempts", schema="raw")

    # Drop provider_requests
    op.drop_index(
        "ix_provider_requests_created_at",
        table_name="provider_requests",
        schema="raw",
    )
    op.drop_index(
        "ix_provider_requests_status",
        table_name="provider_requests",
        schema="raw",
    )
    op.drop_table("provider_requests", schema="raw")

    # Recreate the original baseline provider_batches shape
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
    op.create_index(
        "ix_provider_batches_provider_dataset",
        "provider_batches",
        ["provider_key", "dataset_key"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_requested_at",
        "provider_batches",
        ["requested_at"],
        schema="raw",
    )
    op.create_index(
        "ix_provider_batches_status",
        "provider_batches",
        ["status"],
        schema="raw",
    )