"""PR-5.5 Slice 1 — persistence closure for ``ResearchRun`` / ``ResearchResult``.

Adds two new tables to the ``analytics`` schema so the existing domain
aggregate (Phase 2 of the evidence-driven Research lifecycle, ADR-0012)
can survive a database round trip without importing the JiuwenSwarm
adapter or any Research API surface:

* ``analytics.research_runs`` — lifecycle owner for one execution
  attempt of a playbook against one evidence pack.  Carries the full
  :class:`invest_domain.research.research_run.ResearchRun` state machine
  (``queued`` / ``running`` / ``succeeded`` / ``failed`` /
  ``cancelled``) plus the ``(external_request_id,
  external_session_id)`` reservation so the later JiuwenSwarm adapter
  can index on session identity without coupling the domain to the SDK.

* ``analytics.research_results`` — immutable conclusion record
  produced by a succeeded :class:`ResearchRun`.  The natural unique
  key ``run_id`` enforces ``one immutable result per run`` at the
  database boundary (a succeeded run cannot publish two results).
  ``risks`` and ``evidence_ids`` are JSONB arrays; the structural
  checks reject non-array payloads, blank text fields, and an empty
  citation list.

Both tables chain on top of the Phase 2A ``research_cases`` head and
the Phase 2B ``research_evidence_packs`` table; the FK references
are explicit and named so a buggy application-service path cannot
smuggle an unknown identifier past the validator.

Revision ID: 20260807_0014
Revises: 20260807_0013
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0014"
down_revision: str | None = "20260807_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RUN_STATUS_VALUES = (
    "'queued'",
    "'running'",
    "'succeeded'",
    "'failed'",
    "'cancelled'",
)
_RUN_STATUS_LIST = ", ".join(_RUN_STATUS_VALUES)


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "evidence_pack_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("runner_key", sa.String(length=120), nullable=False),
        sa.Column("playbook_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column(
            "external_request_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "external_session_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_research_runs"),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["analytics.research_cases.case_id"],
            name="fk_research_runs_case_id_research_cases",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_pack_id"],
            ["analytics.research_evidence_packs.id"],
            name="fk_research_runs_evidence_pack_id_research_evidence_packs",
        ),
        sa.CheckConstraint(
            f"status IN ({_RUN_STATUS_LIST})",
            name="ck_research_runs_status_valid",
        ),
        sa.CheckConstraint(
            "btrim(runner_key) <> ''",
            name="ck_research_runs_runner_key_nonempty",
        ),
        sa.CheckConstraint(
            "btrim(playbook_key) <> ''",
            name="ck_research_runs_playbook_key_nonempty",
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name="ck_research_runs_attempt_positive",
        ),
        sa.CheckConstraint(
            "external_request_id IS NULL OR btrim(external_request_id) <> ''",
            name="ck_research_runs_external_request_id_nonempty",
        ),
        sa.CheckConstraint(
            "external_session_id IS NULL OR btrim(external_session_id) <> ''",
            name="ck_research_runs_external_session_id_nonempty",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at",
            name="ck_research_runs_finished_after_started",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_runs_status",
        "research_runs",
        ["status"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_runs_case_id",
        "research_runs",
        ["case_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_runs_external_request_id",
        "research_runs",
        ["external_request_id"],
        schema="analytics",
    )
    op.create_index(
        "uq_research_runs_external_session_id",
        "research_runs",
        ["external_session_id"],
        schema="analytics",
        unique=True,
        postgresql_where=sa.text("external_session_id IS NOT NULL"),
    )

    op.create_table(
        "research_results",
        sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "evidence_pack_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column(
            "risks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("model_key", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("playbook_version", sa.String(length=64), nullable=False),
        sa.Column("adapter_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("result_id", name="pk_research_results"),
        sa.UniqueConstraint("run_id", name="uq_research_results_run_id"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analytics.research_runs.run_id"],
            name="fk_research_results_run_id_research_runs",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_pack_id"],
            ["analytics.research_evidence_packs.id"],
            name="fk_research_results_evidence_pack_id_research_evidence_packs",
        ),
        sa.CheckConstraint(
            "btrim(conclusion) <> ''",
            name="ck_research_results_conclusion_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(report_markdown) <> ''",
            name="ck_research_results_report_markdown_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(model_key) <> ''",
            name="ck_research_results_model_key_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(model_version) <> ''",
            name="ck_research_results_model_version_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(playbook_version) <> ''",
            name="ck_research_results_playbook_version_nonblank",
        ),
        sa.CheckConstraint(
            "btrim(adapter_version) <> ''",
            name="ck_research_results_adapter_version_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(risks) = 'array'",
            name="ck_research_results_risks_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_ids) = 'array'",
            name="ck_research_results_evidence_ids_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(evidence_ids) >= 1",
            name="ck_research_results_evidence_ids_nonempty",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_research_results_run_id",
        "research_results",
        ["run_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_research_results_evidence_pack_id",
        "research_results",
        ["evidence_pack_id"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_results_evidence_pack_id",
        table_name="research_results",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_results_run_id",
        table_name="research_results",
        schema="analytics",
    )
    op.drop_table("research_results", schema="analytics")

    op.drop_index(
        "uq_research_runs_external_session_id",
        table_name="research_runs",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_runs_external_request_id",
        table_name="research_runs",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_runs_case_id",
        table_name="research_runs",
        schema="analytics",
    )
    op.drop_index(
        "ix_research_runs_status",
        table_name="research_runs",
        schema="analytics",
    )
    op.drop_table("research_runs", schema="analytics")
