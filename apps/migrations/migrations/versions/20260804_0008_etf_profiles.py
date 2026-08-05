"""core.etf_profiles table (Stage DC-2 ETF Profile 第一切片)

Revision ID: 20260804_0008
Revises: 20260803_0007
Create Date: 2026-08-04

Stage DC-2 introduces the persistence layer for the ``EtfProfile`` domain
contract. The migration is the schema-only foundation: it adds the
``core.etf_profiles`` table and the supporting indexes/constraints but
does NOT introduce a Provider adapter, a real-network collection path or
an API route. Subsequent DC-2 increments will build on top of this
schema.

Design notes (mirrors :class:`invest_domain.etf_profile.models.EtfProfile`):

- ``core.etf_profiles`` carries one static ETF metadata record per
  underlying instrument. ``instrument_id`` is BOTH the table primary key
  (the natural business key for the 1-1 mapping) and the foreign key to
  ``core.instruments.id``; the database enforces uniqueness on
  ``instrument_id`` so re-collects overwrite an existing row rather
  than producing duplicates.

- Columns mirror the Stage DC-2 plan §"ETF Profile" field list:
  ``instrument_id``, ``manager``, ``benchmark_index``, ``category``,
  ``inception_date``, ``fund_type``, ``management_fee``, ``custody_fee``,
  ``aum``, ``shares``. Every non-key column is nullable: Provider
  responses do not always disclose every field and the domain
  contract forbids fabricating defaults.

- ``management_fee`` / ``custody_fee`` use ``NUMERIC(38, 18)`` to
  preserve fractional precision and carry a defensive range check
  ``[0, 1)`` (``0.0015`` = 0.15% contractual management fee). ``aum`` and
  ``shares`` are also ``NUMERIC(38, 18)`` with strict ``> 0`` checks.
  The textual fields carry ``length(...) > 0`` so an empty Provider
  string never lands in storage.

- ``created_at`` / ``updated_at`` mirror every other ``core.*`` table;
  ``updated_at`` uses ``onupdate=now()`` so a re-write moves the
  timestamp without any application-side bookkeeping.

- Indexes target the three dashboard filter columns (``manager``,
  ``category``, ``fund_type``) at the request of the Stage DC-2 plan.
  ``benchmark_index`` is intentionally not indexed here because the
  benchmark-related slices live in DC-3; adding the index prematurely
  would burn write throughput on a column the dashboard does not yet
  filter on.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0008"
down_revision: str | None = "20260803_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etf_profiles",
        sa.Column("instrument_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manager", sa.String(length=120), nullable=True),
        sa.Column("benchmark_index", sa.String(length=120), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("inception_date", sa.Date(), nullable=True),
        sa.Column("fund_type", sa.String(length=32), nullable=True),
        sa.Column("management_fee", sa.Numeric(38, 18), nullable=True),
        sa.Column("custody_fee", sa.Numeric(38, 18), nullable=True),
        sa.Column("aum", sa.Numeric(38, 18), nullable=True),
        sa.Column("shares", sa.Numeric(38, 18), nullable=True),
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
        sa.PrimaryKeyConstraint("instrument_id", name="pk_etf_profiles"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_etf_profiles_instrument_id_core_instruments",
        ),
        sa.CheckConstraint(
            "manager IS NULL OR length(manager) > 0",
            name="ck_etf_profiles_manager_nonempty",
        ),
        sa.CheckConstraint(
            "benchmark_index IS NULL OR length(benchmark_index) > 0",
            name="ck_etf_profiles_benchmark_index_nonempty",
        ),
        sa.CheckConstraint(
            "category IS NULL OR length(category) > 0",
            name="ck_etf_profiles_category_nonempty",
        ),
        sa.CheckConstraint(
            "fund_type IS NULL OR length(fund_type) > 0",
            name="ck_etf_profiles_fund_type_nonempty",
        ),
        sa.CheckConstraint(
            "management_fee IS NULL OR (management_fee >= 0 AND management_fee < 1)",
            name="ck_etf_profiles_management_fee_range",
        ),
        sa.CheckConstraint(
            "custody_fee IS NULL OR (custody_fee >= 0 AND custody_fee < 1)",
            name="ck_etf_profiles_custody_fee_range",
        ),
        sa.CheckConstraint(
            "aum IS NULL OR aum > 0",
            name="ck_etf_profiles_aum_positive",
        ),
        sa.CheckConstraint(
            "shares IS NULL OR shares > 0",
            name="ck_etf_profiles_shares_positive",
        ),
        schema="core",
    )
    op.create_index(
        "ix_etf_profiles_manager",
        "etf_profiles",
        ["manager"],
        schema="core",
    )
    op.create_index(
        "ix_etf_profiles_category",
        "etf_profiles",
        ["category"],
        schema="core",
    )
    op.create_index(
        "ix_etf_profiles_fund_type",
        "etf_profiles",
        ["fund_type"],
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_etf_profiles_fund_type",
        table_name="etf_profiles",
        schema="core",
    )
    op.drop_index(
        "ix_etf_profiles_category",
        table_name="etf_profiles",
        schema="core",
    )
    op.drop_index(
        "ix_etf_profiles_manager",
        table_name="etf_profiles",
        schema="core",
    )
    op.drop_table("etf_profiles", schema="core")
