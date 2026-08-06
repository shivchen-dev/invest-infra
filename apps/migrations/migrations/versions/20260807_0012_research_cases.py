"""analytics research_cases storage.

Revision ID: 20260807_0012
Revises: 20260806_0011
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0012"
down_revision: str | None = "20260806_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_cases",
        sa.Column("case_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "candidate_pool_run_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("case_id", name="pk_research_cases"),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_cases_instrument_id_core_instruments",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_pool_run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_research_cases_cpool_run_id_analytics_cpool_runs",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_research_cases_status_valid",
        ),
        sa.CheckConstraint(
            "btrim(question) <> ''", name="ck_research_cases_question_nonblank"
        ),
        sa.CheckConstraint(
            "btrim(horizon) <> ''", name="ck_research_cases_horizon_nonblank"
        ),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at",
            name="ck_research_cases_closed_at_after_created_at",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (closed_at IS NOT NULL)",
            name="ck_research_cases_terminal_iff_closed_at_set",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_cases_instrument_as_of_date",
        "research_cases",
        ["instrument_id", "as_of_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_cases_status",
        "research_cases",
        ["status"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_cases_status",
        table_name="research_cases",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_cases_instrument_as_of_date",
        table_name="research_cases",
        schema="analytics",
    )
    op.drop_table("research_cases", schema="analytics")
