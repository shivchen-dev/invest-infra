from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0007"
down_revision: str | None = "20260731_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_evidence_packs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("factor_set_key", sa.String(length=80), nullable=False),
        sa.Column("factor_set_version", sa.String(length=32), nullable=False),
        sa.Column("input_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "candidate_pool_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("freshness_status", sa.String(length=24), nullable=False),
        sa.Column("quality_status", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_evidence_packs"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_packs_instrument",
        ),
        sa.ForeignKeyConstraint(
            ["input_snapshot_id"],
            ["analytics.input_snapshots.id"],
            name="fk_research_packs_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_pool_run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_research_packs_candidate_run",
        ),
        sa.UniqueConstraint(
            "instrument_id",
            "as_of_date",
            "schema_version",
            "factor_set_version",
            "content_hash",
            name="uq_research_evidence_packs_natural_key",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_research_evidence_packs_content_hash_len64",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_research_evidence_packs_payload_object",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_evidence_packs_instrument_as_of_date",
        "research_evidence_packs",
        ["instrument_id", "as_of_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_evidence_packs_content_hash",
        "research_evidence_packs",
        ["content_hash"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_evidence_packs_content_hash",
        table_name="research_evidence_packs",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_evidence_packs_instrument_as_of_date",
        table_name="research_evidence_packs",
        schema="analytics",
    )
    op.drop_table("research_evidence_packs", schema="analytics")
