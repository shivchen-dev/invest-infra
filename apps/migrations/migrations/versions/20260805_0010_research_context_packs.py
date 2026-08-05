"""analytics research context pack storage.

Revision ID: 20260805_0010
Revises: 20260805_0009
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0010"
down_revision: str | None = "20260805_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_context_packs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("missing_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_context_packs"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_context_packs_instrument_id_core_instruments",
        ),
        sa.UniqueConstraint("content_hash", name="uq_research_context_packs_content_hash"),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_research_context_packs_content_hash_len64"
        ),
        sa.CheckConstraint(
            "context_version >= 1", name="ck_research_context_packs_context_version_positive"
        ),
        sa.CheckConstraint(
            "length(schema_version) > 0", name="ck_research_context_packs_schema_version_nonempty"
        ),
        sa.CheckConstraint(
            "missing_reason IS NULL OR length(missing_reason) > 0",
            name="ck_research_context_packs_missing_reason_nonempty",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_context_packs_instrument_version",
        "research_context_packs",
        ["instrument_id", "context_version"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_context_packs_instrument_created_at",
        "research_context_packs",
        ["instrument_id", "created_at"],
        schema="analytics",
    )
    op.create_table(
        "research_context_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_type", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("confidence_score", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "evidence_refs",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("item_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_context_items"),
        sa.ForeignKeyConstraint(
            ["pack_id"],
            ["analytics.research_context_packs.id"],
            name="fk_research_context_items_pack_id_analytics_research_context_packs",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pack_id", "item_hash", name="uq_research_context_items_pack_item_hash"
        ),
        sa.CheckConstraint(
            "value_type IN ('text', 'decimal', 'date', 'json')",
            name="ck_research_context_items_value_type_valid",
        ),
        sa.CheckConstraint(
            "length(item_hash) = 64", name="ck_research_context_items_item_hash_len64"
        ),
        sa.CheckConstraint(
            "length(context_type) > 0", name="ck_research_context_items_context_type_nonempty"
        ),
        sa.CheckConstraint("length(key) > 0", name="ck_research_context_items_key_nonempty"),
        sa.CheckConstraint(
            "length(source_provider) > 0", name="ck_research_context_items_source_provider_nonempty"
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0", name="ck_research_context_items_source_dataset_nonempty"
        ),
        sa.CheckConstraint(
            "source_revision >= 1", name="ck_research_context_items_source_revision_positive"
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_research_context_items_confidence_score_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_refs) = 'array'",
            name="ck_research_context_items_evidence_refs_array",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_context_items_pack_id",
        "research_context_items",
        ["pack_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_context_items_context_type_key",
        "research_context_items",
        ["context_type", "key"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_context_items_context_type_key",
        table_name="research_context_items",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_context_items_pack_id", table_name="research_context_items", schema="analytics"
    )
    op.drop_table("research_context_items", schema="analytics")
    op.drop_index(
        "ix_research_context_packs_instrument_created_at",
        table_name="research_context_packs",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_context_packs_instrument_version",
        table_name="research_context_packs",
        schema="analytics",
    )
    op.drop_table("research_context_packs", schema="analytics")
