"""raw.provider_batches: provider batch raw-evidence table

Revision ID: 20260730_0003
Revises: 20260730_0002
Create Date: 2026-07-30

Introduces the ``raw`` schema and a single ``raw.provider_batches`` table
that records the evidence of every Provider request, both in-flight
(``status='requested'``) and completed (``succeeded`` / ``partial`` /
``failed``). The table intentionally has no foreign keys in this
increment; downstream daily-bars / candidate-pool rows will reference it
in later increments.

Design notes (see M1 increment 2 spec):

- Storage primary key is a UUID generated in Python (``uuid.uuid4``);
  the migration is not allowed to depend on ``pgcrypto``.
- Identifier columns (``provider_key``, ``dataset_key``, ``request_key``)
  are bounded non-empty strings; the unique key is the triplet.
- ``request_params`` and ``warnings`` are JSONB with explicit
  ``NOT NULL`` defaults (``{}`` and ``[]`` respectively). ``warnings`` is
  the per-batch audit trail for non-fatal Provider diagnostics.
- ``status`` is restricted to the four ADR-0003 values; a dedicated
  CHECK constraint encodes the rule that ``status='requested'`` rows
  must carry no payload and no SHA-256, while non-requested rows must
  carry a 64-character lowercase-hex ``payload_sha256``.
- ``updated_at`` is a storage implementation field used for operational
  mutation tracking; ``raw_payload_uri`` remains nullable until object
  storage is introduced.
- Indexes target the common access patterns: lookup by
  ``(provider_key, dataset_key)``, time-range scans by ``requested_at``,
  and operational dashboards by ``status``.

The downgrade drops the indexes, the table, and the ``raw`` schema in
reverse order; nothing is recreated on rollback.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0003"
down_revision: str | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "raw"
TABLE = "provider_batches"

_BATCH_STATUS_VALUES = ("requested", "succeeded", "partial", "failed")


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("dataset_key", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column(
            "request_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
        ),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("raw_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload_uri", sa.Text(), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_batches"),
        sa.UniqueConstraint(
            "provider_key",
            "dataset_key",
            "request_key",
            name="uq_provider_batches_provider_dataset_request",
        ),
        schema=SCHEMA,
        # ``id`` has no database-side default in this increment: M1
        # increment 2 forbids ``gen_random_uuid`` / ``pgcrypto``; the
        # application layer always supplies a Python ``uuid.uuid4()``.
    )

    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_provider_key_nonempty "
            "CHECK (length(btrim(provider_key)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_dataset_key_nonempty "
            "CHECK (length(btrim(dataset_key)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_request_key_nonempty "
            "CHECK (length(btrim(request_key)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_status_valid "
            f"CHECK (status IN {_sql_tuple(_BATCH_STATUS_VALUES)})"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_record_count_nonneg "
            "CHECK (record_count IS NULL OR record_count >= 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_requested_has_no_payload "
            "CHECK (status <> 'requested' OR (raw_payload_json IS NULL AND payload_sha256 IS NULL))"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_payload_sha256_format "
            "CHECK ("
            "payload_sha256 IS NULL "
            "OR (length(payload_sha256) = 64 AND payload_sha256 ~ '^[0-9a-f]{64}$')"
            ")"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_provider_batches_non_requested_has_hash "
            "CHECK ("
            "status = 'requested' "
            "OR (payload_sha256 IS NOT NULL "
            "    AND length(payload_sha256) = 64 "
            "    AND payload_sha256 ~ '^[0-9a-f]{64}$')"
            ")"
        )
    )

    op.create_index(
        "ix_provider_batches_provider_dataset",
        TABLE,
        ["provider_key", "dataset_key"],
        schema=SCHEMA,
    )
    op.create_index("ix_provider_batches_requested_at", TABLE, ["requested_at"], schema=SCHEMA)
    op.create_index("ix_provider_batches_status", TABLE, ["status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_provider_batches_status", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_provider_batches_requested_at", table_name=TABLE, schema=SCHEMA)
    op.drop_index("ix_provider_batches_provider_dataset", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
    op.execute(sa.text(f'DROP SCHEMA IF EXISTS "{SCHEMA}"'))


def _sql_tuple(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"({quoted})"
