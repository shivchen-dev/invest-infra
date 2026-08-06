"""Wire research_evidence_packs.research_case_id to research_cases.case_id.

Revision ID: 20260807_0013
Revises: 20260807_0012
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0013"
down_revision: str | None = "20260807_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK_NAME = "fk_research_evidence_packs_research_case_id_research_cases"
_INDEX_NAME = "ix_research_evidence_packs_research_case_id"
_CONTENT_HASH_UQ_NAME = "uq_research_evidence_packs_content_hash"


def upgrade() -> None:
    op.add_column(
        "research_evidence_packs",
        sa.Column(
            "research_case_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="analytics",
    )
    op.create_foreign_key(
        _FK_NAME,
        "research_evidence_packs",
        "research_cases",
        ["research_case_id"],
        ["case_id"],
        source_schema="analytics",
        referent_schema="analytics",
    )
    op.create_index(
        _INDEX_NAME,
        "research_evidence_packs",
        ["research_case_id"],
        schema="analytics",
    )
    op.create_unique_constraint(
        _CONTENT_HASH_UQ_NAME,
        "research_evidence_packs",
        ["content_hash"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONTENT_HASH_UQ_NAME,
        "research_evidence_packs",
        schema="analytics",
        type_="unique",
    )
    op.drop_index(
        _INDEX_NAME,
        table_name="research_evidence_packs",
        schema="analytics",
    )
    op.drop_constraint(
        _FK_NAME,
        "research_evidence_packs",
        schema="analytics",
        type_="foreignkey",
    )
    op.drop_column(
        "research_evidence_packs",
        "research_case_id",
        schema="analytics",
    )