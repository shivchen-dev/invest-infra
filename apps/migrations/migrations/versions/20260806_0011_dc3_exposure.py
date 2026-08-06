"""DC-3 exposure schema.

Revision ID: 20260806_0011
Revises: 20260805_0010
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0011"
down_revision: str | None = "20260805_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.String(length=64), nullable=False),
        sa.Column("index_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_indexes"),
        sa.UniqueConstraint("index_code", name="uq_indexes_index_code"),
        sa.CheckConstraint("length(index_code) > 0", name="ck_indexes_index_code_nonempty"),
        sa.CheckConstraint("length(index_name) > 0", name="ck_indexes_index_name_nonempty"),
        schema="core",
    )
    op.create_index("ix_indexes_index_code", "indexes", ["index_code"], schema="core")
    op.create_index("ix_indexes_category", "indexes", ["category"], schema="core")

    op.create_table(
        "index_profiles",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_batch_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_profiles"),
        sa.ForeignKeyConstraint(
            ["index_id"], ["core.indexes.id"], name="fk_index_profiles_index_id_core_indexes"
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_index_profiles_source_batch_id_raw_provider_batches",
        ),
        sa.UniqueConstraint("index_id", "revision", name="uq_index_profiles_index_id_revision"),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_index_profiles_content_hash_len64"
        ),
        sa.CheckConstraint("length(index_name) > 0", name="ck_index_profiles_index_name_nonempty"),
        sa.CheckConstraint(
            "length(source_provider) > 0", name="ck_index_profiles_source_provider_nonempty"
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0", name="ck_index_profiles_source_dataset_nonempty"
        ),
        sa.CheckConstraint(
            "source_revision >= 1", name="ck_index_profiles_source_revision_positive"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_index_profiles_revision_positive"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_index_profiles_confidence_range"
        ),
        schema="core",
    )
    for name, columns in (
        ("uq_index_profiles_content_hash", ["content_hash"]),
        ("ix_index_profiles_index_id", ["index_id"]),
        ("ix_index_profiles_source_provider", ["source_provider"]),
        ("ix_index_profiles_category", ["category"]),
    ):
        op.create_index(
            name, "index_profiles", columns, unique=name.startswith("uq_"), schema="core"
        )

    op.create_table(
        "index_constituent_snapshots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_batch_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_constituent_snapshots"),
        sa.ForeignKeyConstraint(
            ["index_id"],
            ["core.indexes.id"],
            name="fk_index_constituent_snapshots_index_id_core_indexes",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_index_snapshots_source_batch_raw_provider_batches",
        ),
        sa.UniqueConstraint(
            "index_id", "as_of_date", "revision", name="uq_index_constituent_snapshots_natural_key"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_index_constituent_snapshots_content_hash_len64"
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0",
            name="ck_index_constituent_snapshots_source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_index_constituent_snapshots_source_dataset_nonempty",
        ),
        sa.CheckConstraint(
            "source_revision >= 1", name="ck_index_constituent_snapshots_source_revision_positive"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_index_constituent_snapshots_revision_positive"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_index_constituent_snapshots_confidence_range",
        ),
        schema="core",
    )
    for name, columns in (
        ("uq_index_constituent_snapshots_content_hash", ["content_hash"]),
        ("ix_index_constituent_snapshots_index_id_as_of_date", ["index_id", "as_of_date"]),
        ("ix_index_constituent_snapshots_index_id_observed_at", ["index_id", "observed_at"]),
    ):
        op.create_index(
            name,
            "index_constituent_snapshots",
            columns,
            unique=name.startswith("uq_"),
            schema="core",
        )

    op.create_table(
        "index_constituents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stock_code", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_constituents"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["core.index_constituent_snapshots.id"],
            name="fk_index_constituents_snapshot_core_index_snapshots",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "stock_code", name="uq_index_constituents_snapshot_stock_code"
        ),
        sa.CheckConstraint(
            "length(stock_code) > 0", name="ck_index_constituents_stock_code_nonempty"
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1", name="ck_index_constituents_weight_range"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_index_constituents_revision_positive"),
        schema="core",
    )
    op.create_index(
        "ix_index_constituents_snapshot_id", "index_constituents", ["snapshot_id"], schema="core"
    )
    op.create_index(
        "ix_index_constituents_stock_code", "index_constituents", ["stock_code"], schema="core"
    )

    op.create_table(
        "etf_index_mappings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("etf_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_batch_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_etf_index_mappings"),
        sa.ForeignKeyConstraint(
            ["etf_id"],
            ["core.instruments.id"],
            name="fk_etf_index_mappings_etf_id_core_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["index_id"], ["core.indexes.id"], name="fk_etf_index_mappings_index_id_core_indexes"
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_etf_index_mappings_source_batch_id_raw_provider_batches",
        ),
        sa.UniqueConstraint(
            "etf_id",
            "index_id",
            "effective_from",
            "revision",
            name="uq_etf_index_mappings_natural_key",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_etf_index_mappings_content_hash_len64"
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0", name="ck_etf_index_mappings_source_provider_nonempty"
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0", name="ck_etf_index_mappings_source_dataset_nonempty"
        ),
        sa.CheckConstraint(
            "source_revision >= 1", name="ck_etf_index_mappings_source_revision_positive"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_etf_index_mappings_revision_positive"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_etf_index_mappings_confidence_range"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_etf_index_mappings_effective_to_after_from",
        ),
        schema="core",
    )
    for name, columns in (
        ("uq_etf_index_mappings_content_hash", ["content_hash"]),
        ("ix_etf_index_mappings_etf_id", ["etf_id"]),
        ("ix_etf_index_mappings_index_id", ["index_id"]),
        ("ix_etf_index_mappings_etf_id_effective_from", ["etf_id", "effective_from"]),
        ("ix_etf_index_mappings_source_provider", ["source_provider"]),
    ):
        op.create_index(
            name, "etf_index_mappings", columns, unique=name.startswith("uq_"), schema="core"
        )

    op.create_table(
        "etf_holding_snapshots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("etf_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_dataset", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_batch_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_etf_holding_snapshots"),
        sa.ForeignKeyConstraint(
            ["etf_id"],
            ["core.instruments.id"],
            name="fk_etf_holding_snapshots_etf_id_core_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_etf_holding_snapshots_source_batch_id_raw_provider_batches",
        ),
        sa.UniqueConstraint(
            "etf_id", "as_of_date", "revision", name="uq_etf_holding_snapshots_natural_key"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64", name="ck_etf_holding_snapshots_content_hash_len64"
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0",
            name="ck_etf_holding_snapshots_source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_etf_holding_snapshots_source_dataset_nonempty",
        ),
        sa.CheckConstraint(
            "source_revision >= 1", name="ck_etf_holding_snapshots_source_revision_positive"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_etf_holding_snapshots_revision_positive"
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_etf_holding_snapshots_confidence_range",
        ),
        schema="core",
    )
    for name, columns in (
        ("uq_etf_holding_snapshots_content_hash", ["content_hash"]),
        ("ix_etf_holding_snapshots_etf_id_as_of_date", ["etf_id", "as_of_date"]),
        ("ix_etf_holding_snapshots_etf_id_observed_at", ["etf_id", "observed_at"]),
    ):
        op.create_index(
            name,
            "etf_holding_snapshots",
            columns,
            unique=name.startswith("uq_"),
            schema="core",
        )

    op.create_table(
        "etf_holdings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stock_code", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Numeric(38, 18), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_etf_holdings"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["core.etf_holding_snapshots.id"],
            name="fk_etf_holdings_snapshot_id_core_etf_holding_snapshots",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "stock_code", name="uq_etf_holdings_snapshot_stock_code"
        ),
        sa.CheckConstraint(
            "length(stock_code) > 0", name="ck_etf_holdings_stock_code_nonempty"
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1", name="ck_etf_holdings_weight_range"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_etf_holdings_revision_positive"
        ),
        schema="core",
    )
    for name, columns in (
        ("ix_etf_holdings_snapshot_id", ["snapshot_id"]),
        ("ix_etf_holdings_stock_code", ["stock_code"]),
    ):
        op.create_index(
            name, "etf_holdings", columns, unique=name.startswith("uq_"), schema="core"
        )


def downgrade() -> None:
    for name in ("ix_etf_holdings_stock_code", "ix_etf_holdings_snapshot_id"):
        op.drop_index(name, table_name="etf_holdings", schema="core")
    op.drop_table("etf_holdings", schema="core")
    for name in (
        "ix_etf_holding_snapshots_etf_id_observed_at",
        "ix_etf_holding_snapshots_etf_id_as_of_date",
        "uq_etf_holding_snapshots_content_hash",
    ):
        op.drop_index(name, table_name="etf_holding_snapshots", schema="core")
    op.drop_table("etf_holding_snapshots", schema="core")
    for name in (
        "ix_etf_index_mappings_source_provider",
        "ix_etf_index_mappings_etf_id_effective_from",
        "ix_etf_index_mappings_index_id",
        "ix_etf_index_mappings_etf_id",
        "uq_etf_index_mappings_content_hash",
    ):
        op.drop_index(name, table_name="etf_index_mappings", schema="core")
    op.drop_table("etf_index_mappings", schema="core")
    for name in ("ix_index_constituents_stock_code", "ix_index_constituents_snapshot_id"):
        op.drop_index(name, table_name="index_constituents", schema="core")
    op.drop_table("index_constituents", schema="core")
    for name in (
        "ix_index_constituent_snapshots_index_id_observed_at",
        "ix_index_constituent_snapshots_index_id_as_of_date",
        "uq_index_constituent_snapshots_content_hash",
    ):
        op.drop_index(name, table_name="index_constituent_snapshots", schema="core")
    op.drop_table("index_constituent_snapshots", schema="core")
    for name in (
        "ix_index_profiles_category",
        "ix_index_profiles_source_provider",
        "ix_index_profiles_index_id",
        "uq_index_profiles_content_hash",
    ):
        op.drop_index(name, table_name="index_profiles", schema="core")
    op.drop_table("index_profiles", schema="core")
    for name in ("ix_indexes_category", "ix_indexes_index_code"):
        op.drop_index(name, table_name="indexes", schema="core")
    op.drop_table("indexes", schema="core")
