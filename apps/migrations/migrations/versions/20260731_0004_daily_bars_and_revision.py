"""core.daily_bars table and core.latest_daily_bars view (PR-06)

Revision ID: 20260731_0004
Revises: 20260731_0003
Create Date: 2026-07-31

PR-06 introduces the standardized ETF daily-bars persistence layer per
ADR-0005 / ADR-0006:

- ``core.daily_bars`` — one row per ``(instrument_id, trade_date,
  adjustment, revision)`` quadruple (the composite primary key is
  enforced at the database level so two attempts cannot claim the same
  business content + revision). The table stores the full OHLCV row,
  the audit trail (``source_provider`` / ``source_batch_id`` /
  ``observed_at``), the monotonic ``revision`` and the deterministic
  business-content ``row_hash``. Per-row invariants mirror the
  domain-level validation in :class:`invest_domain.market_data.models.DailyBar`:

  - prices and ``prev_close`` are strictly positive decimals
    (``open`` / ``high`` / ``low`` / ``close`` / ``prev_close``);
  - ``high`` is at least ``max(open, close, low)``;
  - ``low`` is at most ``min(open, close, high)``;
  - ``volume`` / ``amount`` are non-negative;
  - ``trading_status IN ('normal', 'suspended')``;
  - ``adjustment = 'none'`` (per ADR-0005 §1);
  - ``revision >= 1``.

- ``core.latest_daily_bars`` — read-only PostgreSQL view that picks
  the highest-revision row for each ``(instrument_id, trade_date,
  adjustment)`` triplet using ``row_number() ... order by revision
  desc``. Per ADR-0006 §5 the view is the recommended read surface for
  new snapshot builders, but it MUST NOT be used for candidate-pool
  replay (snapshots pin an exact revision).

Both objects live in the ``core`` schema (created in
``20260731_0001``). The ``source_batch_id`` foreign key targets
``raw.provider_batches.id`` so the raw / core lineage is enforced at
the database level. There is no auto-revision trigger: revision
allocation is owned by the application layer
(:meth:`invest_storage.repositories.SqlAlchemyDailyBarRepository.
upsert_many`) so the domain's ``row_hash``-based comparison stays in
one place.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0004"
down_revision: str | None = "20260731_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NUMERIC = sa.Numeric(precision=38, scale=18)


def upgrade() -> None:
    op.create_table(
        "daily_bars",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", _NUMERIC, nullable=True),
        sa.Column("high", _NUMERIC, nullable=True),
        sa.Column("low", _NUMERIC, nullable=True),
        sa.Column("close", _NUMERIC, nullable=True),
        sa.Column("prev_close", _NUMERIC, nullable=True),
        sa.Column("volume", _NUMERIC, nullable=True),
        sa.Column("amount", _NUMERIC, nullable=True),
        sa.Column("adjustment", sa.String(length=16), nullable=False),
        sa.Column("trading_status", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint(
            "instrument_id",
            "trade_date",
            "adjustment",
            "revision",
            name="pk_daily_bars",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_daily_bars_instrument_id_core_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_daily_bars_source_batch_id_raw_provider_batches",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_daily_bars_revision_positive",
        ),
        sa.CheckConstraint(
            "adjustment = 'none'",
            name="ck_daily_bars_adjustment_none_only",
        ),
        sa.CheckConstraint(
            "trading_status IN ('normal', 'suspended')",
            name="ck_daily_bars_trading_status_valid",
        ),
        sa.CheckConstraint(
            "length(source_provider) > 0",
            name="ck_daily_bars_source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(row_hash) > 0",
            name="ck_daily_bars_row_hash_nonempty",
        ),
        sa.CheckConstraint(
            "open IS NULL OR open > 0",
            name="ck_daily_bars_open_positive",
        ),
        sa.CheckConstraint(
            "high IS NULL OR high > 0",
            name="ck_daily_bars_high_positive",
        ),
        sa.CheckConstraint(
            "low IS NULL OR low > 0",
            name="ck_daily_bars_low_positive",
        ),
        sa.CheckConstraint(
            "close IS NULL OR close > 0",
            name="ck_daily_bars_close_positive",
        ),
        sa.CheckConstraint(
            "prev_close IS NULL OR prev_close > 0",
            name="ck_daily_bars_prev_close_positive",
        ),
        sa.CheckConstraint(
            "volume IS NULL OR volume >= 0",
            name="ck_daily_bars_volume_nonneg",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_daily_bars_amount_nonneg",
        ),
        sa.CheckConstraint(
            "high IS NULL OR close IS NULL OR open IS NULL OR low IS NULL "
            "OR high >= GREATEST(open, close, low)",
            name="ck_daily_bars_high_ge_ohlc",
        ),
        sa.CheckConstraint(
            "low IS NULL OR close IS NULL OR open IS NULL OR high IS NULL "
            "OR low <= LEAST(open, close, high)",
            name="ck_daily_bars_low_le_ohlc",
        ),
        schema="core",
    )
    op.create_index(
        "ix_daily_bars_instrument_trade_date",
        "daily_bars",
        ["instrument_id", "trade_date"],
        schema="core",
    )
    op.create_index(
        "ix_daily_bars_trade_date",
        "daily_bars",
        ["trade_date"],
        schema="core",
    )
    op.create_index(
        "ix_daily_bars_source_batch_id",
        "daily_bars",
        ["source_batch_id"],
        schema="core",
    )

    op.execute(
        sa.text(
            """
            CREATE VIEW "core"."latest_daily_bars" AS
            SELECT
                id,
                instrument_id,
                trade_date,
                open,
                high,
                low,
                close,
                prev_close,
                volume,
                amount,
                adjustment,
                trading_status,
                source_provider,
                source_batch_id,
                observed_at,
                revision,
                row_hash,
                created_at
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY instrument_id, trade_date, adjustment
                        ORDER BY revision DESC
                    ) AS _rn
                FROM "core"."daily_bars"
            ) _ranked
            WHERE _rn = 1
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text('DROP VIEW IF EXISTS "core"."latest_daily_bars"'))
    op.drop_index(
        "ix_daily_bars_source_batch_id",
        table_name="daily_bars",
        schema="core",
    )
    op.drop_index(
        "ix_daily_bars_trade_date",
        table_name="daily_bars",
        schema="core",
    )
    op.drop_index(
        "ix_daily_bars_instrument_trade_date",
        table_name="daily_bars",
        schema="core",
    )
    op.drop_table("daily_bars", schema="core")
