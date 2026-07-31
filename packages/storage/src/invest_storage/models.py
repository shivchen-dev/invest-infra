from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym, synonym

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class InstrumentRow(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        Index(
            "uq_instruments_symbol_exchange_active",
            "symbol",
            "exchange",
            unique=True,
            postgresql_where=text("delist_date IS NULL"),
        ),
        Index("ix_instruments_exchange", "exchange"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="CNY", default="CNY"
    )
    list_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delist_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default="unknown",
        default="unknown",
    )
    underlying_index: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_symbol_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderRequestRow(Base):
    """A logical Provider request, independent of any single network attempt.

    Per ADR-0003 §6.3 (PR-02). One ``provider_requests`` row exists for
    every logical request ``(provider_key, dataset_key, request_key)``;
    the natural unique constraint prevents duplicates. Multiple
    :class:`ProviderAttemptRow` rows can belong to the same request.
    """

    __tablename__ = "provider_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_provider_requests_status_valid",
        ),
        CheckConstraint(
            "length(provider_key) > 0",
            name="ck_provider_requests_provider_key_nonempty",
        ),
        CheckConstraint(
            "length(dataset_key) > 0",
            name="ck_provider_requests_dataset_key_nonempty",
        ),
        CheckConstraint(
            "length(request_key) > 0",
            name="ck_provider_requests_request_key_nonempty",
        ),
        UniqueConstraint(
            "provider_key",
            "dataset_key",
            "request_key",
            name="uq_provider_requests_logical_key",
        ),
        Index("ix_provider_requests_status", "status"),
        Index("ix_provider_requests_created_at", "created_at"),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    requested_by_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProviderAttemptRow(Base):
    """A single network or SDK attempt to satisfy a :class:`ProviderRequestRow`.

    Per ADR-0003 §6.4 (PR-02). A request can have multiple attempts
    (retries, transport fail-overs); ``attempt_no`` is 1-based and
    unique within the parent request. Failed attempts leave no batch
    row behind; ``raw_payload_*`` columns stay NULL for them.
    """

    __tablename__ = "provider_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_provider_attempts_status_valid",
        ),
        CheckConstraint(
            "attempt_no >= 1",
            name="ck_provider_attempts_attempt_no_positive",
        ),
        CheckConstraint(
            "(status <> 'succeeded' OR response_payload_sha256 IS NOT NULL)",
            name="ck_provider_attempts_succeeded_has_hash",
        ),
        CheckConstraint(
            "(status <> 'failed' OR (error_stage IS NOT NULL "
            "AND error_code IS NOT NULL))",
            name="ck_provider_attempts_failed_has_error",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_provider_attempts_finished_after_started",
        ),
        UniqueConstraint(
            "provider_request_id",
            "attempt_no",
            name="uq_provider_attempts_request_attempt_no",
        ),
        Index("ix_provider_attempts_provider_request_id", "provider_request_id"),
        Index("ix_provider_attempts_status", "status"),
        Index("ix_provider_attempts_started_at", "started_at"),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "raw.provider_requests.id",
            name="fk_provider_attempts_provider_request_id_raw_provider_requests",
        ),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_request_id_text: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_payload_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    response_payload_json: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    response_payload_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RawProviderBatchRow(Base):
    """A standardized data batch produced by a successful/partial attempt.

    Per ADR-0003 §6.5 (PR-02). Only ``SUCCEEDED`` / ``PARTIAL`` attempts
    produce a batch row. ``payload_sha256`` is required (the batch
    always carries the response digest).
    """

    __tablename__ = "provider_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'partial')",
            name="ck_provider_batches_status_valid",
        ),
        CheckConstraint(
            "record_count >= 0",
            name="ck_provider_batches_record_count_nonneg",
        ),
        CheckConstraint(
            "length(provider_key) > 0",
            name="ck_provider_batches_provider_key_nonempty",
        ),
        CheckConstraint(
            "length(dataset_key) > 0",
            name="ck_provider_batches_dataset_key_nonempty",
        ),
        CheckConstraint(
            "length(payload_sha256) > 0",
            name="ck_provider_batches_payload_sha256_nonempty",
        ),
        Index("ix_provider_batches_provider_attempt_id", "provider_attempt_id"),
        Index(
            "ix_provider_batches_provider_request_id", "provider_request_id"
        ),
        Index(
            "ix_provider_batches_provider_dataset",
            "provider_key",
            "dataset_key",
        ),
        Index("ix_provider_batches_status", "status"),
        Index("ix_provider_batches_created_at", "created_at"),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "raw.provider_requests.id",
            name="fk_provider_batches_provider_request_id_raw_provider_requests",
        ),
        nullable=False,
    )
    provider_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "raw.provider_attempts.id",
            name="fk_provider_batches_provider_attempt_id_raw_provider_attempts",
        ),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineRunRow(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'partial', 'cancelled')",
            name="ck_pipeline_runs_status_valid",
        ),
        Index("ix_pipeline_runs_job_key", "job_key"),
        Index("ix_pipeline_runs_status", "status"),
        Index("ix_pipeline_runs_dagster_run_id", "dagster_run_id"),
        {"schema": "ops"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dagster_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_key: Mapped[str] = mapped_column(String(120), nullable=False)
    partition_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    algorithm_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CandidatePoolRunRow(Base):
    """One execution of a candidate-pool calculation (ADR-0008 / plan §5.6).

    PR-03 introduces the ``analytics.candidate_pool_runs`` table as the
    persistent record of a candidate-pool calculation. The natural unique
    key ``(trade_date, algorithm_key, algorithm_version, parameter_hash,
    input_snapshot_id)`` enforces that two distinct runs cannot claim
    the same inputs and policy fingerprint - this is the guard that
    prevents accidental double-publication.

    The state machine is enforced by :meth:`invest_domain.candidate_pool.
    models.CandidatePoolRun.transition_to` and persisted via
    :meth:`invest_storage.repositories.SqlAlchemyCandidatePoolRunRepository
    .transition_status`; the database CHECK constraint
    ``ck_candidate_pool_runs_status_valid`` only enforces the value
    vocabulary, not the legal transition graph.
    """

    __tablename__ = "candidate_pool_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('calculated', 'validated', 'published', 'rejected')",
            name="ck_candidate_pool_runs_status_valid",
        ),
        CheckConstraint(
            "length(algorithm_key) > 0",
            name="ck_candidate_pool_runs_algorithm_key_nonempty",
        ),
        CheckConstraint(
            "length(algorithm_version) > 0",
            name="ck_candidate_pool_runs_algorithm_version_nonempty",
        ),
        CheckConstraint(
            "length(parameter_set_key) > 0",
            name="ck_candidate_pool_runs_parameter_set_key_nonempty",
        ),
        CheckConstraint(
            "length(parameter_hash) > 0",
            name="ck_candidate_pool_runs_parameter_hash_nonempty",
        ),
        CheckConstraint(
            "input_row_count >= 0",
            name="ck_candidate_pool_runs_input_row_count_nonneg",
        ),
        CheckConstraint(
            "included_count >= 0",
            name="ck_candidate_pool_runs_included_count_nonneg",
        ),
        CheckConstraint(
            "included_count <= input_row_count",
            name="ck_candidate_pool_runs_included_le_input",
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_candidate_pool_runs_finished_after_started",
        ),
        CheckConstraint(
            "published_at IS NULL OR published_at >= started_at",
            name="ck_candidate_pool_runs_published_after_started",
        ),
        CheckConstraint(
            "rejected_at IS NULL OR rejected_at >= started_at",
            name="ck_candidate_pool_runs_rejected_after_started",
        ),
        CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name="ck_candidate_pool_runs_rejected_has_reason",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_candidate_pool_runs_published_has_timestamp",
        ),
        UniqueConstraint(
            "trade_date",
            "algorithm_key",
            "algorithm_version",
            "parameter_hash",
            "input_snapshot_id",
            name="uq_candidate_pool_runs_natural_key",
        ),
        Index("ix_candidate_pool_runs_status", "status"),
        Index("ix_candidate_pool_runs_trade_date", "trade_date"),
        Index(
            "ix_candidate_pool_runs_trade_date_status",
            "trade_date",
            "status",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    algorithm_key: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    parameter_set_key: Mapped[str] = mapped_column(String(80), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    input_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    included_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidatePoolItemRow(Base):
    """One per-instrument judgment belonging to a :class:`CandidatePoolRunRow`.

    PR-03 introduces the ``analytics.candidate_pool_items`` table to
    persist every include / exclude decision produced by the calculator
    (plan §5.7). The composite primary key ``(run_id, instrument_id)``
    enforces the ADR-0008 invariant that each input instrument appears
    exactly once per run. ``metrics``, ``rule_results`` and
    ``exclusion_reasons`` are JSONB to keep the storage free of
    ORM-specific value objects.
    """

    __tablename__ = "candidate_pool_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_candidate_pool_items_run_id_analytics_candidate_pool_runs",
        ),
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_candidate_pool_items_instrument_id_core_instruments",
        ),
        CheckConstraint(
            "(NOT included) OR (rank IS NOT NULL AND total_score IS NOT NULL)",
            name="ck_candidate_pool_items_included_has_rank_and_score",
        ),
        CheckConstraint(
            "(NOT included) OR rank >= 1",
            name="ck_candidate_pool_items_rank_positive_when_included",
        ),
        CheckConstraint(
            "NOT included OR jsonb_array_length(exclusion_reasons) = 0",
            name="ck_candidate_pool_items_included_has_no_exclusions",
        ),
        CheckConstraint(
            "included OR jsonb_array_length(exclusion_reasons) >= 1",
            name="ck_candidate_pool_items_excluded_has_reasons",
        ),
        Index("ix_candidate_pool_items_run_id", "run_id"),
        Index("ix_candidate_pool_items_instrument_id", "instrument_id"),
        Index(
            "ix_candidate_pool_items_run_id_included",
            "run_id",
            "included",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )
    rule_results: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    exclusion_reasons: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailyBarRow(Base):
    """One row of standardized daily OHLCV data per ADR-0005 / ADR-0006.

    The composite primary key ``(instrument_id, trade_date, adjustment,
    revision)`` is enforced by the database so the same business content
    can coexist across revisions without losing history. ``row_hash``
    is the deterministic business-content digest computed by the domain
    layer (:meth:`invest_domain.market_data.models.DailyBar.
    compute_row_hash`); the storage layer treats it as an opaque audit
    token and does not recompute it. The audit fields
    ``source_provider`` / ``source_batch_id`` / ``observed_at`` are NOT
    part of the row hash, so re-collects from a different batch do not
    require a new revision.
    """

    __tablename__ = "daily_bars"
    __table_args__ = (
        CheckConstraint(
            "revision >= 1",
            name="ck_daily_bars_revision_positive",
        ),
        CheckConstraint(
            "adjustment = 'none'",
            name="ck_daily_bars_adjustment_none_only",
        ),
        CheckConstraint(
            "trading_status IN ('normal', 'suspended')",
            name="ck_daily_bars_trading_status_valid",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_daily_bars_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(row_hash) > 0",
            name="ck_daily_bars_row_hash_nonempty",
        ),
        CheckConstraint(
            "open IS NULL OR open > 0",
            name="ck_daily_bars_open_positive",
        ),
        CheckConstraint(
            "high IS NULL OR high > 0",
            name="ck_daily_bars_high_positive",
        ),
        CheckConstraint(
            "low IS NULL OR low > 0",
            name="ck_daily_bars_low_positive",
        ),
        CheckConstraint(
            "close IS NULL OR close > 0",
            name="ck_daily_bars_close_positive",
        ),
        CheckConstraint(
            "prev_close IS NULL OR prev_close > 0",
            name="ck_daily_bars_prev_close_positive",
        ),
        CheckConstraint(
            "volume IS NULL OR volume >= 0",
            name="ck_daily_bars_volume_nonneg",
        ),
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_daily_bars_amount_nonneg",
        ),
        CheckConstraint(
            "high IS NULL OR close IS NULL OR open IS NULL OR low IS NULL "
            "OR high >= GREATEST(open, close, low)",
            name="ck_daily_bars_high_ge_ohlc",
        ),
        CheckConstraint(
            "low IS NULL OR close IS NULL OR open IS NULL OR high IS NULL "
            "OR low <= LEAST(open, close, high)",
            name="ck_daily_bars_low_le_ohlc",
        ),
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_daily_bars_instrument_id_core_instruments",
        ),
        ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_daily_bars_source_batch_id_raw_provider_batches",
        ),
        Index("ix_daily_bars_instrument_trade_date", "instrument_id", "trade_date"),
        Index("ix_daily_bars_trade_date", "trade_date"),
        Index("ix_daily_bars_source_batch_id", "source_batch_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    high: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    low: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    close: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    prev_close: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    volume: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    amount: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    adjustment: Mapped[str] = mapped_column(String(16), primary_key=True)
    trading_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InputSnapshotRow(Base):
    __tablename__ = "input_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "content_hash",
            name="uq_input_snapshots_date_hash",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_input_snapshots_content_hash_len64",
        ),
        CheckConstraint(
            "row_count >= 1",
            name="ck_input_snapshots_row_count_positive",
        ),
        Index("ix_input_snapshots_snapshot_date", "snapshot_date"),
        Index("ix_input_snapshots_content_hash", "content_hash"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
