"""Stage 4B Phase 3 — evidence bundle linkage for research results.

Stage 4B Phase 3 lifts the analytical evidence bundle produced by
:mod:`invest_domain.research.evidence_bundle` into the storage layer.
Migration ``20260811_0016`` already created the
``analytics.research_evidence_bundles`` table and wired the
nullable ``research_runs.evidence_bundle_id`` FK, so this revision
covers the remaining closure:

* Add a nullable ``evidence_bundle_id`` UUID column to
  ``analytics.research_results`` with a FK to
  ``analytics.research_evidence_bundles.bundle_id`` and a supporting
  index for the future ``list results by bundle`` reader.
* The column is nullable so existing rows (pre-Phase-3 results) keep
  ``NULL`` and the migration is forward/backward compatible without a
  data backfill.

The change is intentionally minimal: no CHECK constraint, no default,
no data backfill. Phase 3 application code populates the column when
it publishes a result; legacy consumers see ``NULL`` which matches the
domain default.

Revision ID: 20260812_0017
Revises: 20260811_0016
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0017"
down_revision: str | None = "20260811_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_results",
        sa.Column(
            "evidence_bundle_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="analytics",
    )
    op.create_foreign_key(
        "fk_research_results_evidence_bundle_id_bundles",
        "research_results",
        "research_evidence_bundles",
        ["evidence_bundle_id"],
        ["bundle_id"],
        source_schema="analytics",
        referent_schema="analytics",
    )
    op.create_index(
        "ix_research_results_evidence_bundle_id",
        "research_results",
        ["evidence_bundle_id"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_results_evidence_bundle_id",
        table_name="research_results",
        schema="analytics",
    )
    op.drop_constraint(
        "fk_research_results_evidence_bundle_id_bundles",
        "research_results",
        type_="foreignkey",
        schema="analytics",
    )
    op.drop_column("research_results", "evidence_bundle_id", schema="analytics")
