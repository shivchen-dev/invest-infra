"""Candidate strategies MVP Slice 1: immutable RAA audit reports.

Revision ID: 20260826_0022
Revises: 20260826_0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0022"
down_revision: str | None = "20260826_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_audits",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("agentoa_task_id", sa.String(length=160), nullable=False),
        sa.Column("auditor_agent_id", sa.String(length=160), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("findings", postgresql.JSONB, nullable=False),
        sa.Column("limitations", postgresql.JSONB, nullable=False),
        sa.Column("report_ref", sa.String(length=512), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id", name="pk_strategy_audits"),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["analytics.strategy_drafts.draft_id"],
            name="fk_strategy_audits_draft_id_strategy_drafts",
        ),
        sa.UniqueConstraint(
            "draft_id", "artifact_hash", "agentoa_task_id",
            name="uq_strategy_audits_draft_artifact_task",
        ),
        sa.CheckConstraint(
            "artifact_hash ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_audits_artifact_hash_len64",
        ),
        sa.CheckConstraint(
            "report_hash ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_audits_report_hash_len64",
        ),
        sa.CheckConstraint(
            "verdict IN ('pass', 'changes_required', 'reject')",
            name="ck_strategy_audits_verdict_valid",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(findings) = 'array'",
            name="ck_strategy_audits_findings_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(limitations) = 'array'",
            name="ck_strategy_audits_limitations_array",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_strategy_audits_draft_id_audited_at",
        "strategy_audits", ["draft_id", "audited_at"], schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_audits_draft_id_audited_at",
        table_name="strategy_audits", schema="analytics",
    )
    op.drop_table("strategy_audits", schema="analytics")
