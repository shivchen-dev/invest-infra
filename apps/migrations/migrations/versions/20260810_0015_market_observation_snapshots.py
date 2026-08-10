"""analytics market observation snapshot storage (Stage 4B Phase 2).

Revision ID: 20260810_0015
Revises: 20260807_0014
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0015"
down_revision: str | None = "20260807_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_observation_snapshots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.String(length=48), nullable=False),
        sa.Column(
            "input_snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("freshness_status", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_market_observation_snapshots"),
        sa.ForeignKeyConstraint(
            ["input_snapshot_id"],
            ["analytics.input_snapshots.id"],
            name="fk_market_observation_snapshots_input_snapshot_id",
        ),
        sa.UniqueConstraint(
            "snapshot_id", name="uq_market_observation_snapshots_snapshot_id"
        ),
        sa.UniqueConstraint(
            "content_hash", name="uq_market_observation_snapshots_content_hash"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_market_observation_snapshots_content_hash_len64",
        ),
        sa.CheckConstraint(
            "length(snapshot_id) > 0",
            name="ck_market_observation_snapshots_snapshot_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_market_observation_snapshots_algorithm_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(scope_type) > 0",
            name="ck_market_observation_snapshots_scope_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(scope_key) > 0",
            name="ck_market_observation_snapshots_scope_key_nonempty",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_market_observation_snapshots_as_of_date",
        "market_observation_snapshots",
        ["as_of_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_market_observation_snapshots_content_hash",
        "market_observation_snapshots",
        ["content_hash"],
        schema="analytics",
    )
    op.create_table(
        "market_observations",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_key", sa.String(length=128), nullable=False),
        sa.Column("value_numeric", sa.Numeric(38, 18), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("item_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_market_observations"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["analytics.market_observation_snapshots.id"],
            name="fk_market_observations_snapshot_id_market_observation_snapshots",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "observation_key", name="uq_market_observations_snapshot_key"
        ),
        sa.CheckConstraint(
            "length(item_hash) = 64", name="ck_market_observations_item_hash_len64"
        ),
        sa.CheckConstraint(
            "length(observation_key) > 0",
            name="ck_market_observations_observation_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(unit) > 0", name="ck_market_observations_unit_nonempty"
        ),
        sa.CheckConstraint(
            "length(source_kind) > 0",
            name="ck_market_observations_source_kind_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_ref) > 0",
            name="ck_market_observations_source_ref_nonempty",
        ),
        sa.CheckConstraint(
            "NOT (value_numeric IS NOT NULL AND value_text IS NOT NULL)",
            name="ck_market_observations_single_value_column",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_market_observations_snapshot_id",
        "market_observations",
        ["snapshot_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_market_observations_observed_date",
        "market_observations",
        ["observed_date"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_observations_observed_date",
        table_name="market_observations",
        schema="analytics",
    )
    op.drop_index(
        "ix_market_observations_snapshot_id",
        table_name="market_observations",
        schema="analytics",
    )
    op.drop_table("market_observations", schema="analytics")
    op.drop_index(
        "ix_market_observation_snapshots_content_hash",
        table_name="market_observation_snapshots",
        schema="analytics",
    )
    op.drop_index(
        "ix_market_observation_snapshots_as_of_date",
        table_name="market_observation_snapshots",
        schema="analytics",
    )
    op.drop_table("market_observation_snapshots", schema="analytics")
