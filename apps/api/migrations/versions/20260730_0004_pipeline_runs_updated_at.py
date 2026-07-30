"""app.pipeline_runs: lifecycle timestamps + status vocabulary CHECK

Revision ID: 20260730_0004
Revises: 20260730_0003
Create Date: 2026-07-30

This increment (M1 Storage increment 5) closes the M1 Storage loop by
introducing :class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`.
The repository depends on two schema details that the original ``0001``
migration did not capture:

1. Server-managed ``created_at`` / ``updated_at`` columns. The plan's
   domain-side :class:`invest_domain.pipeline.PipelineRun` exposes both
   fields; without server defaults the repository cannot round-trip
   them through the existing ORM ``Mapped[datetime]`` columns. Both
   columns are ``DateTime(timezone=True)`` to match every other audit
   timestamp in the storage layer.
2. A ``CHECK`` constraint enforcing the four-value ``status`` vocabulary
   (``pending`` / ``running`` / ``succeeded`` / ``failed``). The
   existing ``0001`` migration only declared ``status`` as a bounded
   string; this increment narrows the vocabulary so a typo or
   drift in the application layer is rejected at the database boundary.

Design notes (consistent with migration ``0003``):

- ``created_at`` uses ``now()`` as the default; ``updated_at`` uses
  ``now()`` plus an ``ON UPDATE`` clause so the storage layer can
  trust the database to refresh it without an explicit UPDATE in the
  repository. This mirrors the audit-timestamp convention already
  applied to ``core.instruments`` and ``raw.provider_batches``.
- The status CHECK constraint is added as a new ``ALTER TABLE``
  statement; no rows are rewritten, so the upgrade is metadata-only
  and runs in a single Alembic transaction.
- The downgrade drops the CHECK constraint and the two new columns in
  reverse order. No data is rewritten; the downgrade is metadata-only.

Out of scope (explicit non-goals):

- No application-layer repository code lives in this migration. The
  :class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`
  is defined in the storage package and tested through the mock-based
  ``test_pipeline_run_repository_mock`` suite plus the
  ``tests/storage/integration/test_pipeline_run_repository.py``
  Testcontainers suite.
- No Dagster asset is introduced; the pipeline simply exposes the rows
  it already records.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0004"
down_revision: str | None = "20260730_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"
TABLE = "pipeline_runs"

_PIPELINE_RUN_STATUS_VALUES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
)


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )

    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "ADD CONSTRAINT ck_pipeline_runs_status_valid "
            f"CHECK (status IN {_sql_tuple(_PIPELINE_RUN_STATUS_VALUES)})"
        )
    )

    # ``updated_at`` must follow the same ``now()`` ON UPDATE convention as
    # ``core.instruments`` and ``raw.provider_batches``. PostgreSQL does not
    # have a native ``ON UPDATE`` clause; we approximate it with a trigger
    # so the audit timestamp is refreshed automatically by every UPDATE.
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION "{SCHEMA}".set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at := now();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_pipeline_runs_set_updated_at
            BEFORE UPDATE ON "{SCHEMA}"."{TABLE}"
            FOR EACH ROW
            EXECUTE FUNCTION "{SCHEMA}".set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"DROP TRIGGER IF EXISTS trg_pipeline_runs_set_updated_at "
            f'ON "{SCHEMA}"."{TABLE}"'
        )
    )
    op.execute(
        sa.text(
            f'DROP FUNCTION IF EXISTS "{SCHEMA}".set_updated_at()'
        )
    )
    op.execute(
        sa.text(
            f'ALTER TABLE "{SCHEMA}"."{TABLE}" '
            "DROP CONSTRAINT IF EXISTS ck_pipeline_runs_status_valid"
        )
    )
    op.drop_column(TABLE, "updated_at", schema=SCHEMA)
    op.drop_column(TABLE, "created_at", schema=SCHEMA)


def _sql_tuple(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"({quoted})"