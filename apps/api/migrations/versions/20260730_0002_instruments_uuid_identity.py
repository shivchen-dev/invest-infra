"""instruments: switch to UUID identity (shadow-rename legacy, new core.instruments)

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30

This migration reshapes ``core.instruments`` so that the storage-layer
primary key is a UUID identity rather than the legacy ``symbol`` business
key (M0-DECISIONS §6 / M1 increment 2). The legacy table is preserved as
``core._instruments_legacy`` for the duration of this revision so a
rollback can re-attach it without losing data.

Upgrade steps:

1. Rename the existing ``core.instruments`` to ``core._instruments_legacy``
   (no rows are dropped; the legacy PK on ``symbol`` is preserved on the
   shadow table so a downgrade can restore the original shape).
2. Create the new ``core.instruments`` table with a UUID primary key and
   the full domain column set.
3. Add CHECK constraints enforcing non-empty text columns and
   date-range invariants (``valid_to >= valid_from`` and
   ``delist_date >= list_date``).
4. Backfill one row per legacy row, generating the ``id`` in Python via
   :func:`uuid.uuid4` (PostgreSQL ``pgcrypto`` is intentionally not used;
   see M1 increment 2 constraints). Default ``currency='CNY'``,
   ``status='unknown'`` and ``provider_symbol_map='{}'`` for every
   backfilled row. No ``valid_from`` value is invented; the column stays
   NULL.
5. Create the partial unique index on ``(symbol, exchange) WHERE
   delist_date IS NULL``. ``valid_from`` remains nullable because the legacy
   table has no trustworthy effective date; no date is fabricated during
   backfill.

Downgrade safety: before any DDL, the new and legacy tables are audited in
both directions, common fields are compared, and fields that cannot be
represented by the legacy shape are rejected. A mismatch raises
``RuntimeError`` before indexes or tables are dropped.

The whole migration runs in a single Alembic transaction.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TABLE = "_instruments_legacy"
NEW_TABLE = "instruments"
SCHEMA = "core"

_INSTRUMENT_STATUS_VALUES = ("active", "suspended", "delisted", "unknown")


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(sa.text(f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" RENAME TO "{LEGACY_TABLE}"'))

    op.create_table(
        NEW_TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("instrument_type", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="CNY"),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("delist_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("underlying_index", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column(
            "provider_symbol_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_instruments"),
        schema=SCHEMA,
    )

    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_symbol_nonempty "
            "CHECK (length(btrim(symbol)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_exchange_nonempty "
            "CHECK (length(btrim(exchange)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_name_nonempty "
            "CHECK (length(btrim(name)) > 0)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_status_valid "
            f"CHECK (status IN {_sql_tuple(_INSTRUMENT_STATUS_VALUES)})"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_valid_range "
            "CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_listing_range "
            "CHECK (delist_date IS NULL OR list_date IS NULL OR delist_date >= list_date)"
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{NEW_TABLE}" '
            "ADD CONSTRAINT ck_instruments_status_delist_invariant "
            "CHECK (status <> 'delisted' OR delist_date IS NOT NULL)"
        )
    )

    op.create_index(
        "uq_instruments_symbol_exchange_active",
        NEW_TABLE,
        ["symbol", "exchange"],
        schema=SCHEMA,
        unique=True,
        postgresql_where=sa.text("delist_date IS NULL"),
    )
    op.create_index("ix_instruments_exchange", NEW_TABLE, ["exchange"], schema=SCHEMA)

    legacy_rows = bind.execute(
        sa.text(
            f'SELECT symbol, name, exchange, instrument_type, is_active, '
            f'created_at, updated_at FROM "{SCHEMA}"."{LEGACY_TABLE}"'
        )
    ).mappings().all()

    for legacy in legacy_rows:
        bind.execute(
            sa.text(
                f'INSERT INTO "{SCHEMA}"."{NEW_TABLE}" ('
                f"id, symbol, exchange, name, instrument_type, currency, "
                f"status, provider_symbol_map, is_active, created_at, updated_at"
                f") VALUES ("
                f":id, :symbol, :exchange, :name, :instrument_type, "
                f"'CNY', 'unknown', '{{}}'::jsonb, "
                f":is_active, :created_at, :updated_at"
                f")"
            ),
            {
                "id": uuid.uuid4(),
                "symbol": legacy["symbol"],
                "exchange": legacy["exchange"],
                "name": legacy["name"],
                "instrument_type": legacy["instrument_type"],
                "is_active": legacy["is_active"],
                "created_at": legacy["created_at"],
                "updated_at": legacy["updated_at"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()

    checks = {
        "new rows absent from legacy": f'''
            SELECT COUNT(*) FROM "{SCHEMA}"."{NEW_TABLE}" n
            LEFT JOIN "{SCHEMA}"."{LEGACY_TABLE}" l
              ON l.symbol = n.symbol AND l.exchange = n.exchange
            WHERE l.symbol IS NULL
        ''',
        "legacy rows absent from new": f'''
            SELECT COUNT(*) FROM "{SCHEMA}"."{LEGACY_TABLE}" l
            LEFT JOIN "{SCHEMA}"."{NEW_TABLE}" n
              ON n.symbol = l.symbol AND n.exchange = l.exchange
            WHERE n.symbol IS NULL
        ''',
        "shared fields changed": f'''
            SELECT COUNT(*) FROM "{SCHEMA}"."{NEW_TABLE}" n
            JOIN "{SCHEMA}"."{LEGACY_TABLE}" l
              ON l.symbol = n.symbol AND l.exchange = n.exchange
            WHERE n.name IS DISTINCT FROM l.name
               OR n.exchange IS DISTINCT FROM l.exchange
               OR n.instrument_type IS DISTINCT FROM l.instrument_type
               OR n.is_active IS DISTINCT FROM l.is_active
               OR n.created_at IS DISTINCT FROM l.created_at
               OR n.updated_at IS DISTINCT FROM l.updated_at
        ''',
        "new fields cannot be represented by legacy": f'''
            SELECT COUNT(*) FROM "{SCHEMA}"."{NEW_TABLE}"
            WHERE list_date IS NOT NULL OR delist_date IS NOT NULL
               OR valid_from IS NOT NULL OR valid_to IS NOT NULL
               OR status = 'delisted' OR currency IS DISTINCT FROM 'CNY'
               OR provider_symbol_map IS DISTINCT FROM '{{}}'::jsonb
               OR underlying_index IS NOT NULL OR category IS NOT NULL
        ''',
    }
    for description, query in checks.items():
        count = int(bind.execute(sa.text(query)).scalar_one())
        if count:
            raise RuntimeError(
                f"refusing to downgrade: {description} ({count} row(s)); "
                "rollback would lose data"
            )

    op.drop_index("ix_instruments_exchange", table_name=NEW_TABLE, schema=SCHEMA)
    op.drop_index(
        "uq_instruments_symbol_exchange_active", table_name=NEW_TABLE, schema=SCHEMA
    )

    op.drop_table(NEW_TABLE, schema=SCHEMA)
    op.execute(sa.text(f'ALTER TABLE "{SCHEMA}"."{LEGACY_TABLE}" RENAME TO "{NEW_TABLE}"'))


def _sql_tuple(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"({quoted})"
