"""analytics.etf_profile_fields table (Stage DC-2 PR-ETF-PROFILE-04 存储切片)

Revision ID: 20260805_0009
Revises: 20260804_0008
Create Date: 2026-08-05

``PR-ETF-PROFILE-04`` introduces the persistence layer for the per-field
evidence contract added by ``PR-ETF-PROFILE-01``. The migration is the
schema-only foundation for the ``analytics.etf_profile_fields`` table;
the storage adapter (``SqlAlchemyEtfProfileFieldRepository`` in
``packages/storage/src/invest_storage/repositories.py``) and the storage
DTOs (``NewEtfProfileField`` / ``StoredEtfProfileField``) land together
with this migration. Subsequent increments will build the Provider
collection path and the application service that translates Provider
responses into ``FieldEvidence`` rows.

Design notes (mirrors :class:`invest_domain.etf_profile.models.FieldEvidence`):

- One row per ``FieldEvidence`` observation. The natural idempotency
  key is ``content_hash`` (the 64-character lowercase hex digest
  computed by the domain layer over the business content). The unique
  index on ``content_hash`` enforces idempotency at the database
  boundary so a re-collect of the same observation from the same
  provider / revision is a no-op while a different provider / revision
  (different ``content_hash``) is stored as a coexisting row,
  preserving the full evidence history per the PR-ETF-PROFILE-01
  conflict rules.

- The runtime value is stored in three discriminated columns
  (``field_value_text`` / ``field_value_numeric`` /
  ``field_value_date``) so the SQLAlchemy layer can preserve the exact
  ``Decimal`` precision and the exact ``date`` calendar semantics
  without forcing a single JSONB-typed envelope. ``value_type`` tells
  the repository which column carries the canonical value; the CHECK
  constraints guard against any mismatch between ``value_type`` and
  the populated column. ``None`` is the carrier for ``unknown`` /
  ``not disclosed`` and is allowed for every ``value_type`` (the
  ``MISSING`` ``quality_status`` keeps the value ``NULL`` by contract).

- ``source_provider`` / ``source_dataset`` / ``source_revision`` plus
  ``content_hash`` is the unique provider-provenance fingerprint per
  business observation. Two observations with the same ``content_hash``
  but different source provenance are rejected by the database.

- ``instrument_id`` is the foreign key to ``core.instruments.id`` so
  the storage layer rejects writes that reference an unknown
  instrument. The combination ``(instrument_id, field_key)`` is
  indexed so the resolver's read path can fetch every observation of
  one field for one instrument in O(log n).

- ``confidence_score`` is a finite ``Decimal`` in ``[0, 1]``; the
  ``CHECK (confidence_score >= 0 AND confidence_score <= 1)``
  constraint enforces the same bounds as the domain dataclass.
  ``source_revision`` is a positive ``int`` so a buggy application
  cannot persist a ``0`` revision.

- Indexes target the natural read paths:
  ``(instrument_id, field_key)`` for the resolver's per-field lookup,
  ``(instrument_id)`` for the per-instrument history replay, and
  ``(source_provider)`` for the provider-provenance audit. The
  ``content_hash`` unique index is the idempotency guard.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0009"
down_revision: str | None = "20260804_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etf_profile_fields",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "instrument_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("field_key", sa.String(length=64), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("field_value_text", sa.Text(), nullable=True),
        sa.Column("field_value_numeric", sa.Numeric(38, 18), nullable=True),
        sa.Column("field_value_date", sa.Date(), nullable=True),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("confidence_score", sa.Numeric(38, 18), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_etf_profile_fields"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_etf_profile_fields_instrument_id_core_instruments",
        ),
        sa.CheckConstraint(
            "value_type IN ('text', 'decimal', 'date')",
            name="ck_etf_profile_fields_value_type_valid",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_etf_profile_fields_content_hash_len64",
        ),
        sa.CheckConstraint(
            "length(field_key) > 0",
            name="ck_etf_profile_fields_field_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0",
            name="ck_etf_profile_fields_source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_etf_profile_fields_source_dataset_nonempty",
        ),
        sa.CheckConstraint(
            "source_revision >= 1",
            name="ck_etf_profile_fields_source_revision_positive",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_etf_profile_fields_confidence_score_range",
        ),
        sa.CheckConstraint(
            "((value_type = 'text' AND field_value_numeric IS NULL "
            "AND field_value_date IS NULL) OR "
            "(value_type = 'decimal' AND field_value_text IS NULL "
            "AND field_value_date IS NULL) OR "
            "(value_type = 'date' AND field_value_text IS NULL "
            "AND field_value_numeric IS NULL))",
            name="ck_etf_profile_fields_value_columns_match",
        ),
        sa.UniqueConstraint(
            "content_hash",
            name="uq_etf_profile_fields_content_hash",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_etf_profile_fields_instrument_id",
        "etf_profile_fields",
        ["instrument_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_etf_profile_fields_instrument_field_key",
        "etf_profile_fields",
        ["instrument_id", "field_key"],
        schema="analytics",
    )
    op.create_index(
        "ix_etf_profile_fields_field_key",
        "etf_profile_fields",
        ["field_key"],
        schema="analytics",
    )
    op.create_index(
        "ix_etf_profile_fields_source_provider",
        "etf_profile_fields",
        ["source_provider"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_etf_profile_fields_source_provider",
        table_name="etf_profile_fields",
        schema="analytics",
    )
    op.drop_index(
        "ix_etf_profile_fields_field_key",
        table_name="etf_profile_fields",
        schema="analytics",
    )
    op.drop_index(
        "ix_etf_profile_fields_instrument_field_key",
        table_name="etf_profile_fields",
        schema="analytics",
    )
    op.drop_index(
        "ix_etf_profile_fields_instrument_id",
        table_name="etf_profile_fields",
        schema="analytics",
    )
    op.drop_table("etf_profile_fields", schema="analytics")
