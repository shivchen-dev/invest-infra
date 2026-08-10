"""research_evidence_bundles storage (Stage 4B Phase 3).

Revision ID: 20260811_0016
Revises: 20260810_0015
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0016"
down_revision: str | None = "20260810_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_evidence_bundles",
        sa.Column("bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "research_case_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "evidence_pack_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "evidence_pack_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "as_of_date",
            sa.Date(),
            nullable=False,
        ),
        sa.Column(
            "market_snapshot_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "market_snapshot_hashes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "market_snapshot_dates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "schema_version", sa.String(length=32), nullable=False
        ),
        sa.Column(
            "bundle_hash", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "bundle_id", name="pk_research_evidence_bundles"
        ),
        sa.ForeignKeyConstraint(
            ["research_case_id"],
            ["analytics.research_cases.case_id"],
            name="fk_research_evidence_bundles_research_case_id_research_cases",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_pack_id"],
            ["analytics.research_evidence_packs.id"],
            name=(
                "fk_research_evidence_bundles_evidence_pack_id_"
                "research_packs"
            ),
        ),
        sa.CheckConstraint(
            "length(bundle_hash) = 64",
            name="ck_research_evidence_bundles_bundle_hash_len64",
        ),
        sa.CheckConstraint(
            "length(evidence_pack_hash) = 64",
            name="ck_research_evidence_bundles_evidence_pack_hash_len64",
        ),
        sa.CheckConstraint(
            "length(schema_version) > 0",
            name="ck_research_evidence_bundles_schema_version_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(market_snapshot_ids) = 'array'",
            name="ck_research_evidence_bundles_snapshot_ids_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(market_snapshot_hashes) = 'array'",
            name="ck_research_evidence_bundles_snapshot_hashes_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(market_snapshot_dates) = 'array'",
            name="ck_research_evidence_bundles_snapshot_dates_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(market_snapshot_ids) = "
            "jsonb_array_length(market_snapshot_hashes)",
            name="ck_research_evidence_bundles_snapshot_ids_hashes_same_length",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(market_snapshot_ids) = "
            "jsonb_array_length(market_snapshot_dates)",
            name="ck_research_evidence_bundles_snapshot_ids_dates_same_length",
        ),
        sa.UniqueConstraint(
            "bundle_hash",
            name="uq_research_evidence_bundles_bundle_hash",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_evidence_bundles_research_case_id",
        "research_evidence_bundles",
        ["research_case_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_evidence_bundles_evidence_pack_id",
        "research_evidence_bundles",
        ["evidence_pack_id"],
        schema="analytics",
    )

    op.add_column(
        "research_runs",
        sa.Column(
            "evidence_bundle_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="analytics",
    )
    op.create_foreign_key(
        "fk_research_runs_evidence_bundle_id_research_evidence_bundles",
        "research_runs",
        "research_evidence_bundles",
        ["evidence_bundle_id"],
        ["bundle_id"],
        source_schema="analytics",
        referent_schema="analytics",
    )
    op.create_index(
        "ix_research_runs_evidence_bundle_id",
        "research_runs",
        ["evidence_bundle_id"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_runs_evidence_bundle_id",
        table_name="research_runs",
        schema="analytics",
    )
    op.drop_constraint(
        "fk_research_runs_evidence_bundle_id_research_evidence_bundles",
        "research_runs",
        type_="foreignkey",
        schema="analytics",
    )
    op.drop_column("research_runs", "evidence_bundle_id", schema="analytics")

    op.drop_index(
        "ix_research_evidence_bundles_evidence_pack_id",
        table_name="research_evidence_bundles",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_evidence_bundles_research_case_id",
        table_name="research_evidence_bundles",
        schema="analytics",
    )
    op.drop_table(
        "research_evidence_bundles", schema="analytics"
    )
