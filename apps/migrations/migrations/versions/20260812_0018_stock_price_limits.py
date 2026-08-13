"""core.stock_price_limits table for per-day upper/lower price-limit storage.

Revision ID: 20260812_0018
Revises: 20260812_0017
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0018"
down_revision: str | None = "20260812_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NUMERIC = sa.Numeric(precision=38, scale=18)


def upgrade() -> None:
    op.create_table(
        "stock_price_limits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("regime_id", sa.String(length=80), nullable=False),
        sa.Column("limit_up_price", _NUMERIC, nullable=True),
        sa.Column("limit_down_price", _NUMERIC, nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reference_price", _NUMERIC, nullable=True),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_price_limits"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_stock_price_limits_instrument_id_core_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_stock_price_limits_source_batch_id_raw_provider_batches",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "trade_date",
            "revision",
            "row_hash",
            name="uq_stock_price_limits_instrument_trade_date_revision_row_hash",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="revision_positive",
        ),
        sa.CheckConstraint(
            "length(regime_id) > 0",
            name="regime_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(status) > 0",
            name="status_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0",
            name="source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(row_hash) = 64",
            name="row_hash_len64",
        ),
        schema="core",
    )
    op.create_index(
        "ix_stock_price_limits_instrument_trade_date",
        "stock_price_limits",
        ["instrument_id", "trade_date"],
        schema="core",
    )
    op.create_index(
        "ix_stock_price_limits_trade_date",
        "stock_price_limits",
        ["trade_date"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_price_limits_trade_date",
        table_name="stock_price_limits",
        schema="core",
    )
    op.drop_index(
        "ix_stock_price_limits_instrument_trade_date",
        table_name="stock_price_limits",
        schema="core",
    )
    op.drop_table("stock_price_limits", schema="core")
