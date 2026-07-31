"""Candidate Pool persistence tables (PR-03)

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31

PR-03 adds the persistence layer for the ``candidate_pool`` bounded
context, per ADR-0008 / plan §5.6/§5.7:

- ``analytics.candidate_pool_runs`` — one row per candidate-pool
  calculation. Carries the natural unique key
  ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
  input_snapshot_id)`` so that two distinct runs cannot claim the same
  inputs and policy fingerprint (the guard against accidental
  double-publication). The state machine vocabulary
  ``('calculated', 'validated', 'published', 'rejected')`` is enforced
  by a CHECK constraint; legal transitions are governed by
  :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`.

- ``analytics.candidate_pool_items`` — one row per
  ``(run_id, instrument_id)`` pair, persisting every include / exclude
  decision produced by the calculator. The composite primary key
  ``(run_id, instrument_id)`` enforces the ADR-0008 invariant that
  each input instrument appears exactly once per run.

Both tables live in the ``analytics`` schema (created in the v2
baseline). Foreign keys reference ``analytics.candidate_pool_runs.id``
and ``core.instruments.id`` so a row cannot exist without its parent
run or instrument.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0003"
down_revision: str | None = "20260731_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS analytics"))

    # analytics.candidate_pool_runs
    op.create_table(
        "candidate_pool_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("algorithm_key", sa.String(length=80), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("parameter_set_key", sa.String(length=80), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_row_count", sa.Integer(), nullable=False),
        sa.Column("included_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("quality_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_pool_runs"),
        sa.UniqueConstraint(
            "trade_date",
            "algorithm_key",
            "algorithm_version",
            "parameter_hash",
            "input_snapshot_id",
            name="uq_candidate_pool_runs_natural_key",
        ),
        sa.CheckConstraint(
            "status IN ('calculated', 'validated', 'published', 'rejected')",
            name="ck_candidate_pool_runs_status_valid",
        ),
        sa.CheckConstraint(
            "length(algorithm_key) > 0",
            name="ck_candidate_pool_runs_algorithm_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_candidate_pool_runs_algorithm_version_nonempty",
        ),
        sa.CheckConstraint(
            "length(parameter_set_key) > 0",
            name="ck_candidate_pool_runs_parameter_set_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(parameter_hash) > 0",
            name="ck_candidate_pool_runs_parameter_hash_nonempty",
        ),
        sa.CheckConstraint(
            "input_row_count >= 0",
            name="ck_candidate_pool_runs_input_row_count_nonneg",
        ),
        sa.CheckConstraint(
            "included_count >= 0",
            name="ck_candidate_pool_runs_included_count_nonneg",
        ),
        sa.CheckConstraint(
            "included_count <= input_row_count",
            name="ck_candidate_pool_runs_included_le_input",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_candidate_pool_runs_finished_after_started",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at >= started_at",
            name="ck_candidate_pool_runs_published_after_started",
        ),
        sa.CheckConstraint(
            "rejected_at IS NULL OR rejected_at >= started_at",
            name="ck_candidate_pool_runs_rejected_after_started",
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name="ck_candidate_pool_runs_rejected_has_reason",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_candidate_pool_runs_published_has_timestamp",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_runs_status",
        "candidate_pool_runs",
        ["status"],
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_runs_trade_date",
        "candidate_pool_runs",
        ["trade_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_runs_trade_date_status",
        "candidate_pool_runs",
        ["trade_date", "status"],
        schema="analytics",
    )

    # analytics.candidate_pool_items
    op.create_table(
        "candidate_pool_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instrument_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("total_score", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rule_results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("exclusion_reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("run_id", "instrument_id", name="pk_candidate_pool_items"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_candidate_pool_items_run_id_analytics_candidate_pool_runs",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_candidate_pool_items_instrument_id_core_instruments",
        ),
        sa.CheckConstraint(
            "(NOT included) OR (rank IS NOT NULL AND total_score IS NOT NULL)",
            name="ck_candidate_pool_items_included_has_rank_and_score",
        ),
        sa.CheckConstraint(
            "(NOT included) OR rank >= 1",
            name="ck_candidate_pool_items_rank_positive_when_included",
        ),
        sa.CheckConstraint(
            "NOT included OR jsonb_array_length(exclusion_reasons) = 0",
            name="ck_candidate_pool_items_included_has_no_exclusions",
        ),
        sa.CheckConstraint(
            "included OR jsonb_array_length(exclusion_reasons) >= 1",
            name="ck_candidate_pool_items_excluded_has_reasons",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_items_run_id",
        "candidate_pool_items",
        ["run_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_items_instrument_id",
        "candidate_pool_items",
        ["instrument_id"],
        schema="analytics",
    )
    op.create_index(
        "ix_candidate_pool_items_run_id_included",
        "candidate_pool_items",
        ["run_id", "included"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_pool_items_run_id_included",
        table_name="candidate_pool_items",
        schema="analytics",
    )
    op.drop_index(
        "ix_candidate_pool_items_instrument_id",
        table_name="candidate_pool_items",
        schema="analytics",
    )
    op.drop_index(
        "ix_candidate_pool_items_run_id",
        table_name="candidate_pool_items",
        schema="analytics",
    )
    op.drop_table("candidate_pool_items", schema="analytics")

    op.drop_index(
        "ix_candidate_pool_runs_trade_date_status",
        table_name="candidate_pool_runs",
        schema="analytics",
    )
    op.drop_index(
        "ix_candidate_pool_runs_trade_date",
        table_name="candidate_pool_runs",
        schema="analytics",
    )
    op.drop_index(
        "ix_candidate_pool_runs_status",
        table_name="candidate_pool_runs",
        schema="analytics",
    )
    op.drop_table("candidate_pool_runs", schema="analytics")