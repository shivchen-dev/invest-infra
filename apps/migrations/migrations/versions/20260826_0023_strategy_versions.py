"""Candidate strategies MVP Slice 1 — additive storage closure for ``StrategyVersion``.

Persists :class:`invest_domain.strategy.version.StrategyVersion` into
``analytics.strategy_versions``. The table mirrors the v1
:mod:`invest_domain.strategy.version` aggregate fields exactly: stable
``strategy_id`` PK, business keys ``strategy_key`` / ``version``,
immutable ``strategy.json`` reference and SHA-256 hash, the controlled
ingestion ``source_hashes`` JSONB array (non-empty, lowercase
SHA-256), the CIA approval binding metadata (``decision_ref`` /
``decision_hash`` / ``decided_by_agent_id`` / ``audit_id`` /
``approved_at``), the nullable manual ``activated_at`` timestamp and
the system ``created_at`` timestamp.

Revision ID: 20260826_0023
Revises: 20260826_0022
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0023"
down_revision: str | None = "20260826_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_versions",
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=512), nullable=False),
        sa.Column("artifact_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hashes", postgresql.JSONB, nullable=False),
        sa.Column("decision_ref", sa.String(length=512), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("decided_by_agent_id", sa.String(length=160), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("strategy_id", name="pk_strategy_versions"),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["analytics.strategy_audits.audit_id"],
            name="fk_strategy_versions_audit_id_strategy_audits",
        ),
        sa.UniqueConstraint(
            "strategy_key", "version",
            name="uq_strategy_versions_strategy_key_version",
        ),
        sa.UniqueConstraint(
            "artifact_hash",
            name="uq_strategy_versions_artifact_hash",
        ),
        sa.UniqueConstraint(
            "decision_hash",
            name="uq_strategy_versions_decision_hash",
        ),
        sa.CheckConstraint(
            "btrim(strategy_key) <> ''",
            name="ck_strategy_versions_strategy_key_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(version) <> ''",
            name="ck_strategy_versions_version_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(artifact_ref) <> ''",
            name="ck_strategy_versions_artifact_ref_nonblank",
        ),
        sa.CheckConstraint(
            "artifact_hash ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_versions_artifact_hash_len64",
        ),
        sa.CheckConstraint(
            "decision_hash ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_versions_decision_hash_len64",
        ),
        sa.CheckConstraint(
            "btrim(decision_ref) <> ''",
            name="ck_strategy_versions_decision_ref_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(decided_by_agent_id) <> ''",
            name="ck_strategy_versions_decided_by_agent_id_nonblank",
        ),
        sa.CheckConstraint(
            "activated_at IS NULL OR activated_at >= approved_at",
            name="ck_strategy_versions_activated_after_approved",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_hashes) = 'array' AND jsonb_array_length(source_hashes) > 0",
            name="ck_strategy_versions_source_hashes_array_nonempty",
        ),
        sa.CheckConstraint(
            "NOT jsonb_path_exists(source_hashes, "
            "'$[*] ? (@.type() != \"string\" || "
            "!(@ like_regex \"^[0-9a-f]{64}$\"))')",
            name="ck_strategy_versions_source_hashes_elements_lower_hex64",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_strategy_versions_audit_id",
        "strategy_versions",
        ["audit_id"],
        schema="analytics",
    )
    op.create_index(
        "uq_strategy_versions_activated_strategy_key",
        "strategy_versions",
        ["strategy_key"],
        unique=True,
        postgresql_where=sa.text("activated_at IS NOT NULL"),
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_strategy_versions_audit_id",
        table_name="strategy_versions",
        schema="analytics",
    )
    op.drop_index(
        "uq_strategy_versions_activated_strategy_key",
        table_name="strategy_versions",
        schema="analytics",
    )
    op.drop_table("strategy_versions", schema="analytics")
