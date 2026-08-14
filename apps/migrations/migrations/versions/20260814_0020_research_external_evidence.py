"""Bind admitted external evidence to Research Cases."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0020"
down_revision: str | None = "20260814_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_external_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_content_hash", sa.String(64), nullable=True),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("source_uri", sa.String(512), nullable=False),
        sa.Column("producer", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("admission", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_research_external_evidence"),
        sa.ForeignKeyConstraint(
            ["research_case_id"], ["analytics.research_cases.case_id"],
            name="fk_research_external_evidence_case",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["integration.external_observations.observation_id"],
            name="fk_research_external_evidence_observation",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["integration.external_artifacts.artifact_id"],
            name="fk_research_external_evidence_artifact",
        ),
        sa.UniqueConstraint(
            "research_case_id", "observation_id",
            name="uq_research_external_evidence_case_observation",
        ),
        sa.UniqueConstraint("evidence_id", name="uq_research_external_evidence_evidence_id"),
        sa.CheckConstraint("length(evidence_id) > 0", name="evidence_id_nonempty"),
        sa.CheckConstraint("length(content_hash) = 64", name="content_hash_len64"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        sa.CheckConstraint("jsonb_typeof(admission) = 'object'", name="admission_object"),
        schema="analytics",
    )
    op.create_index(
        "ix_research_external_evidence_case",
        "research_external_evidence", ["research_case_id"], schema="analytics",
    )
    op.create_index(
        "ix_research_external_evidence_observation",
        "research_external_evidence", ["observation_id"], schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_external_evidence_observation",
        table_name="research_external_evidence", schema="analytics",
    )
    op.drop_index(
        "ix_research_external_evidence_case",
        table_name="research_external_evidence", schema="analytics",
    )
    op.drop_table("research_external_evidence", schema="analytics")
