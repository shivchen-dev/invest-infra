"""ACTIVE candidate strategies MVP Slice 0 — persistence closure for ``StrategyDraft``.

Adds ``analytics.strategy_drafts`` so the existing ``StrategyDraftRow``
can survive a database round trip without importing any strategy-domain,
repository or unit-of-work surface: eight columns matching the ORM row
exactly (no server defaults, no FKs, no triggers, no extra columns),
two uniques, six defensive CHECKs and one composite
``(strategy_key, created_at)`` index.

Revision ID: 20260826_0021
Revises: 20260814_0020
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0021"
down_revision: str | None = "20260814_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_drafts",
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_key", sa.String(length=120), nullable=False),
        sa.Column("proposed_version", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=False),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("source_refs", postgresql.JSONB, nullable=False),
        sa.Column("validation_result", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("draft_id", name="pk_strategy_drafts"),
        sa.UniqueConstraint(
            "strategy_key", "proposed_version",
            name="uq_strategy_drafts_strategy_key_proposed_version",
        ),
        sa.UniqueConstraint(
            "artifact_hash", name="uq_strategy_drafts_artifact_hash",
        ),
        sa.CheckConstraint(
            "btrim(strategy_key) <> ''",
            name="ck_strategy_drafts_strategy_key_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(proposed_version) <> ''",
            name="ck_strategy_drafts_proposed_version_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(artifact_ref) <> ''",
            name="ck_strategy_drafts_artifact_ref_nonblank",
        ),
        sa.CheckConstraint(
            "artifact_hash ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_drafts_artifact_hash_len64",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_refs) = 'array' "
            "AND jsonb_array_length(source_refs) > 0",
            name="ck_strategy_drafts_source_refs_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(validation_result) = 'object'",
            name="ck_strategy_drafts_validation_result_object",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_strategy_drafts_strategy_key_created_at",
        "strategy_drafts",
        ["strategy_key", "created_at"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_drafts_strategy_key_created_at",
        table_name="strategy_drafts",
        schema="analytics",
    )
    op.drop_table("strategy_drafts", schema="analytics")
