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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    requested_by_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
            "(status <> 'failed' OR (error_stage IS NOT NULL AND error_code IS NOT NULL))",
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "raw.provider_requests.id",
            name="fk_provider_attempts_provider_request_id_raw_provider_requests",
        ),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_request_id_text: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
        Index("ix_provider_batches_provider_request_id", "provider_request_id"),
        Index(
            "ix_provider_batches_provider_dataset",
            "provider_key",
            "dataset_key",
        ),
        Index("ix_provider_batches_status", "status"),
        Index("ix_provider_batches_created_at", "created_at"),
        {"schema": "raw"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    algorithm_key: Mapped[str] = mapped_column(String(80), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(80), nullable=False)
    parameter_set_key: Mapped[str] = mapped_column(String(80), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "analytics.input_snapshots.id",
            name="fk_cpool_runs_snapshot_id",
        ),
        nullable=False,
    )
    input_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    included_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    instrument_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResearchEvidencePackRow(Base):
    """One immutable ``EvidencePack`` observation (Phase 2B persistence closure).

    Persists :class:`invest_domain.research.models.EvidencePack`. The
    synthetic ``id`` UUID is the storage-assigned primary key; the
    business idempotency key is the
    ``(instrument_id, as_of_date, schema_version, factor_set_version,
    content_hash)`` UNIQUE constraint enforced by the database.

    ``research_case_id`` is a nullable FK to
    ``analytics.research_cases.case_id``. The column is nullable so a
    legacy pack authored before the lifecycle owner was wired into the
    CaseContext shape can coexist with a case-bound pack without a
    backfill migration; the database rejects an unknown ``case_id`` at
    the FK boundary, so a pack with a non-null ``research_case_id``
    always references a real ResearchCase row.
    """

    __tablename__ = "research_evidence_packs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_packs_instrument",
        ),
        ForeignKeyConstraint(
            ["input_snapshot_id"],
            ["analytics.input_snapshots.id"],
            name="fk_research_packs_snapshot",
        ),
        ForeignKeyConstraint(
            ["candidate_pool_run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_research_packs_candidate_run",
        ),
        ForeignKeyConstraint(
            ["research_case_id"],
            ["analytics.research_cases.case_id"],
            name="fk_research_evidence_packs_research_case_id_research_cases",
        ),
        UniqueConstraint(
            "instrument_id",
            "as_of_date",
            "schema_version",
            "factor_set_version",
            "content_hash",
            name="uq_research_evidence_packs_natural_key",
        ),
        UniqueConstraint(
            "content_hash",
            name="uq_research_evidence_packs_content_hash",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_research_evidence_packs_content_hash_len64",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_research_evidence_packs_payload_object",
        ),
        Index(
            "ix_research_evidence_packs_instrument_as_of_date",
            "instrument_id",
            "as_of_date",
        ),
        Index("ix_research_evidence_packs_content_hash", "content_hash"),
        Index(
            "ix_research_evidence_packs_research_case_id",
            "research_case_id",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    factor_set_key: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    candidate_pool_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    research_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    freshness_status: Mapped[str] = mapped_column(String(24), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EtfProfileRow(Base):
    """One static ETF metadata record, 1-1 with ``core.instruments``.

    Stage DC-2 introduces ``core.etf_profiles`` (migration
    ``20260804_0008_etf_profiles``). The table mirrors the
    :class:`invest_domain.etf_profile.models.EtfProfile` field set;
    the storage layer treats it as an opaque audit row and the domain
    validator runs on every domain-side construction. ``instrument_id``
    is BOTH the storage primary key and the foreign key to
    ``core.instruments.id``, so any ``core.instruments`` row can have
    at most one ``core.etf_profiles`` row.

    The textual fields ``manager``, ``benchmark_index``, ``category``
    and ``fund_type`` carry ``CHECK (length(...) > 0)`` so the
    database never persists a meaningless empty string. The fee /
    amount fields use ``NUMERIC(38, 18)`` to keep ``Decimal`` precision
    end-to-end; the domain contract (``management_fee`` and
    ``custody_fee`` in ``[0, 1)``, ``aum`` and ``shares`` strictly
    positive) is the source of truth and the storage layer reflects it
    as defensive ``range`` checks so a buggy application-service path
    cannot smuggle an out-of-contract value past the domain validator.
    """

    __tablename__ = "etf_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_etf_profiles_instrument_id_core_instruments",
        ),
        CheckConstraint(
            "manager IS NULL OR length(manager) > 0",
            name="ck_etf_profiles_manager_nonempty",
        ),
        CheckConstraint(
            "benchmark_index IS NULL OR length(benchmark_index) > 0",
            name="ck_etf_profiles_benchmark_index_nonempty",
        ),
        CheckConstraint(
            "category IS NULL OR length(category) > 0",
            name="ck_etf_profiles_category_nonempty",
        ),
        CheckConstraint(
            "fund_type IS NULL OR length(fund_type) > 0",
            name="ck_etf_profiles_fund_type_nonempty",
        ),
        CheckConstraint(
            "management_fee IS NULL OR (management_fee >= 0 AND management_fee < 1)",
            name="ck_etf_profiles_management_fee_range",
        ),
        CheckConstraint(
            "custody_fee IS NULL OR (custody_fee >= 0 AND custody_fee < 1)",
            name="ck_etf_profiles_custody_fee_range",
        ),
        CheckConstraint(
            "aum IS NULL OR aum > 0",
            name="ck_etf_profiles_aum_positive",
        ),
        CheckConstraint(
            "shares IS NULL OR shares > 0",
            name="ck_etf_profiles_shares_positive",
        ),
        Index("ix_etf_profiles_manager", "manager"),
        Index("ix_etf_profiles_category", "category"),
        Index("ix_etf_profiles_fund_type", "fund_type"),
        {"schema": "core"},
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    manager: Mapped[str | None] = mapped_column(String(120), nullable=True)
    benchmark_index: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    inception_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    fund_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    management_fee: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    custody_fee: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    aum: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    shares: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ResearchContextPackRow(Base):
    __tablename__ = "research_context_packs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_context_packs_instrument_id_core_instruments",
        ),
        UniqueConstraint("content_hash", name="uq_research_context_packs_content_hash"),
        CheckConstraint(
            "length(content_hash) = 64", name="ck_research_context_packs_content_hash_len64"
        ),
        CheckConstraint(
            "context_version >= 1", name="ck_research_context_packs_context_version_positive"
        ),
        Index("ix_research_context_packs_instrument_version", "instrument_id", "context_version"),
        Index("ix_research_context_packs_instrument_created_at", "instrument_id", "created_at"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResearchContextItemRow(Base):
    __tablename__ = "research_context_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pack_id"],
            ["analytics.research_context_packs.id"],
            name="fk_research_context_items_pack_context_packs",
            ondelete="CASCADE",
        ),
        UniqueConstraint("pack_id", "item_hash", name="uq_research_context_items_pack_item_hash"),
        CheckConstraint(
            "value_type IN ('text', 'decimal', 'date', 'json')",
            name="ck_research_context_items_value_type_valid",
        ),
        Index("ix_research_context_items_pack_id", "pack_id"),
        Index("ix_research_context_items_context_type_key", "context_type", "key"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pack_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    context_type: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence_score: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    item_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EtfProfileFieldRow(Base):
    """One piece of evidence for one ETF-profile field.

    Stage DC-2 ``PR-ETF-PROFILE-04`` introduces
    ``analytics.etf_profile_fields`` (Alembic migration
    ``20260805_0009_etf_profile_fields``) as the persistent record of
    every :class:`invest_domain.etf_profile.models.FieldEvidence`
    observation. The natural idempotency key is ``content_hash`` (the
    deterministic digest computed by the domain layer over the
    business content) so re-collects of the same observation from the
    same provider / revision are a no-op. A different provider /
    revision produces a different ``content_hash`` and is stored as a
    coexisting row, preserving the full evidence history per the
    PR-ETF-PROFILE-01 conflict rules.

    The runtime value is stored in three discriminated columns
    (``field_value_text`` / ``field_value_numeric`` / ``field_value_date``)
    so the SQLAlchemy layer can preserve the exact ``Decimal`` precision
    and the exact ``date`` calendar semantics without forcing a single
    JSONB-typed envelope. The ``value_type`` column tells the
    repository which column carries the canonical value; the other two
    stay ``NULL`` for any given row. ``None`` is the carrier for
    ``unknown`` / ``not disclosed`` and is allowed for every
    ``value_type`` (the ``MISSING`` ``quality_status`` keeps the value
    ``NULL`` by contract).

    The ``source_*`` columns mirror :class:`FieldEvidenceSource` so the
    full provider provenance is preserved per row; the combination
    ``(source_provider, source_dataset, source_revision, content_hash)``
    is therefore unique per business observation. The instrument
    foreign key points at ``core.instruments.id`` so the storage layer
    rejects writes that reference an unknown instrument.
    """

    __tablename__ = "etf_profile_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_etf_profile_fields_instrument_id_core_instruments",
        ),
        CheckConstraint(
            "value_type IN ('text', 'decimal', 'date')",
            name="ck_etf_profile_fields_value_type_valid",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_etf_profile_fields_content_hash_len64",
        ),
        CheckConstraint(
            "length(field_key) > 0",
            name="ck_etf_profile_fields_field_key_nonempty",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_etf_profile_fields_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_etf_profile_fields_source_dataset_nonempty",
        ),
        CheckConstraint(
            "source_revision >= 1",
            name="ck_etf_profile_fields_source_revision_positive",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_etf_profile_fields_confidence_score_range",
        ),
        CheckConstraint(
            "((value_type = 'text' AND field_value_numeric IS NULL "
            "AND field_value_date IS NULL) OR "
            "(value_type = 'decimal' AND field_value_text IS NULL "
            "AND field_value_date IS NULL) OR "
            "(value_type = 'date' AND field_value_text IS NULL "
            "AND field_value_numeric IS NULL))",
            name="ck_etf_profile_fields_value_columns_match",
        ),
        Index(
            "uq_etf_profile_fields_content_hash",
            "content_hash",
            unique=True,
        ),
        Index(
            "ix_etf_profile_fields_instrument_id",
            "instrument_id",
        ),
        Index(
            "ix_etf_profile_fields_instrument_field_key",
            "instrument_id",
            "field_key",
        ),
        Index("ix_etf_profile_fields_field_key", "field_key"),
        Index("ix_etf_profile_fields_source_provider", "source_provider"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    field_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_value_numeric: Mapped[Any | None] = mapped_column(Numeric(38, 18), nullable=True)
    field_value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence_score: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IndexIdentityRow(Base):
    """Stable index identity row.

    Stage DC-3 introduces ``core.indexes`` (migration
    ``20260806_0011_dc3_exposure``) as the canonical store of every
    known market index. ``index_code`` is the natural business key
    (e.g. ``"000300.SH"``) and is enforced unique at the database
    boundary; the synthetic ``id`` (``UUID``) is the stable internal
    identifier that
    :class:`IndexProfileRow`, :class:`IndexConstituentSnapshotRow` and
    :class:`EtfIndexMappingRow` all FK back to.

    Plan 1 of the DC-3 design separates **identity** (this row, owned
    by ``core.indexes``) from **observation** (per-source metadata
    snapshots in ``core.index_profiles``). The identity table is the
    canonical join target; observation rows store the as-collected
    business content (the observed name / category that varies per
    provider and per revision) and FK to the identity by ``index_id``.

    The ``index_name`` / ``category`` columns here carry the **latest
    observed** name / category so a join to the identity alone is
    enough to render an index in dashboards; the per-observation name
    is still preserved on :class:`IndexProfileRow` for replay.
    """

    __tablename__ = "indexes"
    __table_args__ = (
        CheckConstraint(
            "length(index_code) > 0",
            name="ck_indexes_index_code_nonempty",
        ),
        CheckConstraint(
            "length(index_name) > 0",
            name="ck_indexes_index_name_nonempty",
        ),
        UniqueConstraint("index_code", name="uq_indexes_index_code"),
        Index("ix_indexes_index_code", "index_code"),
        Index("ix_indexes_category", "category"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_code: Mapped[str] = mapped_column(String(64), nullable=False)
    index_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profiles: Mapped[list[IndexProfileRow]] = relationship(
        back_populates="index_identity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    constituent_snapshots: Mapped[list[IndexConstituentSnapshotRow]] = relationship(
        back_populates="index_identity",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    mappings: Mapped[list[EtfIndexMappingRow]] = relationship(
        back_populates="index_identity",
        passive_deletes=True,
    )


class IndexProfileRow(Base):
    """One immutable ``index_profile`` observation.

    Stage DC-3 introduces ``core.index_profiles`` (migration
    ``20260806_0011_dc3_exposure``) as the persistent record of every
    :class:`invest_domain.exposure.models.IndexProfile` observation.
    Per Plan 1, the index identity lives in :class:`IndexIdentityRow`
    and this row is a **revisioned observation**: multiple rows can
    coexist for the same ``index_id`` (same underlying market index)
    with different ``revision`` numbers and ``content_hash`` values so
    the full observation history is preserved. Re-collects of the same
    observation are a no-op on ``content_hash`` while a different
    observation produces a new ``revision`` row.

    The :class:`invest_domain.exposure.models.IndexProfile` dataclass
    is content-only (carries no ``id`` field); the storage layer
    provides the synthetic ``id`` (PK) and the
    ``index_id`` FK to :class:`IndexIdentityRow`. Application code
    threads one ``index_id`` through both writes — the invariant is
    verified by :meth:`tests.storage.test_exposure_repositories_mock
    .CrossRepositoryIndexIdTests.test_index_id_matches_mapping_index_id`.

    ``index_name`` / ``category`` are denormalized onto the observation
    row so a historical replay sees the **observed** name even when
    the identity row's canonical name has since drifted. The
    provenance columns mirror :class:`ExposureProvenance` so the full
    provider provenance is preserved per row; ``content_hash`` is the
    natural idempotency key.
    """

    __tablename__ = "index_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["index_id"],
            ["core.indexes.id"],
            name="fk_index_profiles_index_id_core_indexes",
        ),
        ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_index_profiles_source_batch_id_raw_provider_batches",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_index_profiles_content_hash_len64",
        ),
        CheckConstraint(
            "length(index_name) > 0",
            name="ck_index_profiles_index_name_nonempty",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_index_profiles_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_index_profiles_source_dataset_nonempty",
        ),
        CheckConstraint(
            "source_revision >= 1",
            name="ck_index_profiles_source_revision_positive",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_index_profiles_revision_positive",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_index_profiles_confidence_range",
        ),
        UniqueConstraint(
            "index_id", "revision", name="uq_index_profiles_index_id_revision"
        ),
        Index("uq_index_profiles_content_hash", "content_hash", unique=True),
        Index("ix_index_profiles_index_id", "index_id"),
        Index("ix_index_profiles_source_provider", "source_provider"),
        Index("ix_index_profiles_category", "category"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    index_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    index_identity: Mapped[IndexIdentityRow] = relationship(back_populates="profiles")


class IndexConstituentSnapshotRow(Base):
    """One immutable snapshot of the constituents of an index.

    Stage DC-3 ``PR-EXPOSURE-03`` introduces
    ``core.index_constituent_snapshots`` (Alembic migration
    ``20260806_0011_dc3_exposure``) as the persistent record of every
    :class:`invest_domain.exposure.models.IndexConstituentSnapshot`
    observation. Snapshots are immutable per ADR-0006 §3: the same
    ``(index_id, as_of_date, revision)`` triplet is a no-op; a new
    observation with a different ``content_hash`` produces a new
    revision.

    Per Plan 1 the ``index_id`` column FKs to
    :class:`IndexIdentityRow.id` so the storage layer rejects snapshots
    that reference an unknown index. The natural idempotency key is
    ``content_hash``; the ``(index_id, as_of_date, revision)`` UNIQUE
    constraint is the version-key guard. Child rows
    (:class:`IndexConstituentRow`) FK back to this table with
    ``ON DELETE CASCADE`` so a snapshot's constituents are removed
    when the snapshot is dropped.
    """

    __tablename__ = "index_constituent_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["index_id"],
            ["core.indexes.id"],
            name="fk_index_constituent_snapshots_index_id_core_indexes",
        ),
        ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_index_snapshots_source_batch_raw_provider_batches",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_index_constituent_snapshots_content_hash_len64",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_index_constituent_snapshots_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_index_constituent_snapshots_source_dataset_nonempty",
        ),
        CheckConstraint(
            "source_revision >= 1",
            name="ck_index_constituent_snapshots_source_revision_positive",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_index_constituent_snapshots_revision_positive",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_index_constituent_snapshots_confidence_range",
        ),
        UniqueConstraint(
            "index_id", "as_of_date", "revision",
            name="uq_index_constituent_snapshots_natural_key",
        ),
        Index(
            "uq_index_constituent_snapshots_content_hash",
            "content_hash",
            unique=True,
        ),
        Index(
            "ix_index_constituent_snapshots_index_id_as_of_date",
            "index_id",
            "as_of_date",
        ),
        Index(
            "ix_index_constituent_snapshots_index_id_observed_at",
            "index_id",
            "observed_at",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    index_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    index_identity: Mapped[IndexIdentityRow] = relationship(
        back_populates="constituent_snapshots"
    )
    constituents: Mapped[list[IndexConstituentRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class IndexConstituentRow(Base):
    """One constituent of an :class:`IndexConstituentSnapshotRow`.

    Stage DC-3 ``PR-EXPOSURE-03`` introduces
    ``core.index_constituents`` (Alembic migration
    ``20260806_0011_dc3_exposure``). One row per
    ``(snapshot_id, stock_code)`` pair; the composite uniqueness is
    enforced at the database level so the same stock cannot appear
    twice in a snapshot. ``revision`` mirrors the parent snapshot's
    revision so audit replays can join on the triplet without scanning.

    The ``weight`` column is the deterministic ``Decimal`` weight
    computed by the domain layer over ``[0, 1]``; the database CHECK
    constraints mirror the domain contract so a buggy application path
    cannot smuggle an out-of-range value past the validator. The FK to
    :class:`IndexConstituentSnapshotRow` carries ``ON DELETE CASCADE``
    so a snapshot's constituents are removed when the parent is
    dropped.
    """

    __tablename__ = "index_constituents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["core.index_constituent_snapshots.id"],
            name="fk_index_constituents_snapshot_core_index_snapshots",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(stock_code) > 0",
            name="ck_index_constituents_stock_code_nonempty",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_index_constituents_weight_range",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_index_constituents_revision_positive",
        ),
        Index("ix_index_constituents_snapshot_id", "snapshot_id"),
        Index("ix_index_constituents_stock_code", "stock_code"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    snapshot: Mapped[IndexConstituentSnapshotRow] = relationship(
        back_populates="constituents"
    )


class EtfIndexMappingRow(Base):
    """One immutable ``(ETF, Index)`` mapping observation.

    Stage DC-3 ``PR-EXPOSURE-03`` introduces
    ``core.etf_index_mappings`` (Alembic migration
    ``20260806_0011_dc3_exposure``) as the persistent record of every
    :class:`invest_domain.exposure.models.EtfIndexMapping`
    observation. The natural idempotency key is ``content_hash``; the
    ``(etf_id, index_id, effective_from, revision)`` UNIQUE constraint
    is the version-key guard so two distinct revisions cannot claim the
    same effective-date slot.

    Per Plan 1, ``index_id`` FKs to :class:`IndexIdentityRow.id` —
    the **stable index identity** (not the per-observation profile
    row's synthetic id). The application layer threads the same
    ``index_id`` through both :class:`IndexProfileRow` /
    :class:`IndexConstituentSnapshotRow` writes and the
    :class:`EtfIndexMappingRow` write so the FK chain stays closed;
    the storage layer enforces the referential integrity at the
    database boundary. Violations surface as
    :class:`sqlalchemy.exc.IntegrityError`.

    ``effective_to`` is nullable so an open-ended mapping (``NULL`` =
    "this is the current mapping") coexists with closed mappings in
    the same table; the CHECK constraint rejects ``effective_to <
    effective_from``.
    """

    __tablename__ = "etf_index_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["etf_id"],
            ["core.instruments.id"],
            name="fk_etf_index_mappings_etf_id_core_instruments",
        ),
        ForeignKeyConstraint(
            ["index_id"],
            ["core.indexes.id"],
            name="fk_etf_index_mappings_index_id_core_indexes",
        ),
        ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_etf_index_mappings_source_batch_id_raw_provider_batches",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_etf_index_mappings_content_hash_len64",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_etf_index_mappings_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_etf_index_mappings_source_dataset_nonempty",
        ),
        CheckConstraint(
            "source_revision >= 1",
            name="ck_etf_index_mappings_source_revision_positive",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_etf_index_mappings_revision_positive",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_etf_index_mappings_confidence_range",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_etf_index_mappings_effective_to_after_from",
        ),
        UniqueConstraint(
            "etf_id", "index_id", "effective_from", "revision",
            name="uq_etf_index_mappings_natural_key",
        ),
        Index(
            "uq_etf_index_mappings_content_hash",
            "content_hash",
            unique=True,
        ),
        Index("ix_etf_index_mappings_etf_id", "etf_id"),
        Index("ix_etf_index_mappings_index_id", "index_id"),
        Index(
            "ix_etf_index_mappings_etf_id_effective_from",
            "etf_id",
            "effective_from",
        ),
        Index("ix_etf_index_mappings_source_provider", "source_provider"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    etf_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    index_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    index_identity: Mapped[IndexIdentityRow] = relationship(
        back_populates="mappings"
    )


class EtfHoldingSnapshotRow(Base):
    """One immutable snapshot of the holdings of an ETF.

    Stage DC-3 ``PR-EXPOSURE-03`` introduces
    ``core.etf_holding_snapshots`` (Alembic migration
    ``20260806_0011_dc3_exposure``) as the persistent record of every
    :class:`invest_domain.exposure.models.EtfHoldingSnapshot`
    observation. Snapshots are immutable per ADR-0006 §3: the same
    ``(etf_id, as_of_date, revision)`` triplet is a no-op; a new
    observation with a different ``content_hash`` produces a new
    revision.

    The natural idempotency key is ``content_hash``; the
    ``(etf_id, as_of_date, revision)`` UNIQUE constraint is the
    version-key guard. The ``etf_id`` column FKs to
    ``core.instruments.id`` so the storage layer rejects snapshots
    that reference an unknown instrument. Child rows
    (:class:`EtfHoldingRow`) FK back to this table with
    ``ON DELETE CASCADE``.
    """

    __tablename__ = "etf_holding_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["etf_id"],
            ["core.instruments.id"],
            name="fk_etf_holding_snapshots_etf_id_core_instruments",
        ),
        ForeignKeyConstraint(
            ["source_batch_id"],
            ["raw.provider_batches.id"],
            name="fk_etf_holding_snapshots_source_batch_id_raw_provider_batches",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_etf_holding_snapshots_content_hash_len64",
        ),
        CheckConstraint(
            "length(source_provider) > 0",
            name="ck_etf_holding_snapshots_source_provider_nonempty",
        ),
        CheckConstraint(
            "length(source_dataset) > 0",
            name="ck_etf_holding_snapshots_source_dataset_nonempty",
        ),
        CheckConstraint(
            "source_revision >= 1",
            name="ck_etf_holding_snapshots_source_revision_positive",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_etf_holding_snapshots_revision_positive",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_etf_holding_snapshots_confidence_range",
        ),
        UniqueConstraint(
            "etf_id", "as_of_date", "revision",
            name="uq_etf_holding_snapshots_natural_key",
        ),
        Index(
            "uq_etf_holding_snapshots_content_hash",
            "content_hash",
            unique=True,
        ),
        Index(
            "ix_etf_holding_snapshots_etf_id_as_of_date",
            "etf_id",
            "as_of_date",
        ),
        Index(
            "ix_etf_holding_snapshots_etf_id_observed_at",
            "etf_id",
            "observed_at",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    etf_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EtfHoldingRow(Base):
    """One holding of an :class:`EtfHoldingSnapshotRow`.

    Stage DC-3 ``PR-EXPOSURE-03`` introduces ``core.etf_holdings``
    (Alembic migration ``20260806_0011_dc3_exposure``). One row per
    ``(snapshot_id, stock_code)`` pair; the composite uniqueness is
    enforced at the database level so the same stock cannot appear
    twice in a snapshot. ``revision`` mirrors the parent snapshot's
    revision so audit replays can join on the triplet without scanning.

    The ``weight`` column is the deterministic ``Decimal`` weight
    computed by the domain layer over ``[0, 1]``; the database CHECK
    constraints mirror the domain contract. The FK to
    :class:`EtfHoldingSnapshotRow` carries ``ON DELETE CASCADE`` so a
    snapshot's holdings are removed when the parent is dropped.
    """

    __tablename__ = "etf_holdings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["core.etf_holding_snapshots.id"],
            name="fk_etf_holdings_snapshot_id_core_etf_holding_snapshots",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(stock_code) > 0",
            name="ck_etf_holdings_stock_code_nonempty",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_etf_holdings_weight_range",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_etf_holdings_revision_positive",
        ),
        Index("ix_etf_holdings_snapshot_id", "snapshot_id"),
        Index("ix_etf_holdings_stock_code", "stock_code"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[Any] = mapped_column(Numeric(38, 18), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResearchCaseRow(Base):
    """Lifecycle owner row for one research question (ADR-0012 / Phase 2A).

    Persists :class:`invest_domain.research.research_case.ResearchCase`.
    The synthetic ``case_id`` UUID is the primary key. The CHECK
    constraints reject whitespace-only ``question`` / ``horizon`` via
    ``btrim(...) <> ''`` (mirrors the domain's ``non-blank`` contract)
    and enforce the terminal-state ``closed_at`` invariant.
    """

    __tablename__ = "research_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["instrument_id"],
            ["core.instruments.id"],
            name="fk_research_cases_instrument_id_core_instruments",
        ),
        ForeignKeyConstraint(
            ["candidate_pool_run_id"],
            ["analytics.candidate_pool_runs.id"],
            name="fk_research_cases_cpool_run_id_analytics_cpool_runs",
        ),
        CheckConstraint(
            "status IN ('draft', 'ready', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_research_cases_status_valid",
        ),
        CheckConstraint(
            "btrim(question) <> ''",
            name="ck_research_cases_question_nonblank",
        ),
        CheckConstraint(
            "btrim(horizon) <> ''",
            name="ck_research_cases_horizon_nonblank",
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= created_at",
            name="ck_research_cases_closed_at_after_created_at",
        ),
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled')) = (closed_at IS NOT NULL)",
            name="ck_research_cases_terminal_iff_closed_at_set",
        ),
        Index("ix_research_cases_instrument_as_of_date", "instrument_id", "as_of_date"),
        Index("ix_research_cases_status", "status"),
        {"schema": "analytics"},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candidate_pool_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class ResearchRunRow(Base):
    """Lifecycle owner row for one ``ResearchRun`` execution attempt.

    PR-5.5 Slice 1 persists :class:`invest_domain.research.research_run
    .ResearchRun` into ``analytics.research_runs``. The synthetic
    ``run_id`` UUID is the storage-assigned primary key and mirrors the
    domain aggregate's primary identifier. ``case_id`` and
    ``evidence_pack_id`` are FK constraints to the existing
    Phase 2A ``research_cases`` and Phase 2B ``research_evidence_packs``
    tables so the run cannot reference an unknown case or evidence
    pack.

    The state-machine vocabulary (queued / running / succeeded /
    failed / cancelled) is enforced by the
    ``ck_research_runs_status_valid`` CHECK constraint; the
    cross-column invariants (queued has no timestamps / error,
    terminal states carry ``finished_at``, etc.) live in the domain
    layer because SQL cannot express the full transition graph.

    ``external_request_id`` and ``external_session_id`` are nullable
    reservations for the later JiuwenSwarm adapter: the domain layer
    remains independent of the SDK while the storage layer carries
    the indexes the adapter will need. The ``uq_research_runs_external
    _session_id`` PARTIAL UNIQUE INDEX guarantees that two rows cannot
    share a non-null ``external_session_id`` so a
    JiuwenSwarm session id maps to exactly one research run.
    ``status``-based compare-and-set UPDATEs use ``updated_at`` as the
    audit timestamp and ``where status = :previous`` as the
    concurrency guard.
    """

    __tablename__ = "research_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id"],
            ["analytics.research_cases.case_id"],
            name="fk_research_runs_case_id_research_cases",
        ),
        ForeignKeyConstraint(
            ["evidence_pack_id"],
            ["analytics.research_evidence_packs.id"],
            name="fk_research_runs_evidence_pack_id_research_evidence_packs",
        ),
        CheckConstraint(
            (
                "status IN ('queued', 'running', 'succeeded', 'failed', "
                "'cancelled')"
            ),
            name="status_valid",
        ),
        CheckConstraint(
            "btrim(runner_key) <> ''",
            name="runner_key_nonempty",
        ),
        CheckConstraint(
            "btrim(playbook_key) <> ''",
            name="playbook_key_nonempty",
        ),
        CheckConstraint(
            "attempt >= 1",
            name="attempt_positive",
        ),
        CheckConstraint(
            "external_request_id IS NULL OR btrim(external_request_id) <> ''",
            name="external_request_id_nonempty",
        ),
        CheckConstraint(
            "external_session_id IS NULL OR btrim(external_session_id) <> ''",
            name="external_session_id_nonempty",
        ),
        CheckConstraint(
            (
                "started_at IS NULL OR finished_at IS NULL "
                "OR finished_at >= started_at"
            ),
            name="finished_after_started",
        ),
        Index("ix_research_runs_status", "status"),
        Index("ix_research_runs_case_id", "case_id"),
        Index(
            "ix_research_runs_external_request_id",
            "external_request_id",
        ),
        Index(
            "uq_research_runs_external_session_id",
            "external_session_id",
            unique=True,
            postgresql_where=text("external_session_id IS NOT NULL"),
        ),
        {"schema": "analytics"},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    runner_key: Mapped[str] = mapped_column(String(120), nullable=False)
    playbook_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_request_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    external_session_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ResearchResultRow(Base):
    """Immutable conclusion row produced by a succeeded :class:`ResearchRun`.

    PR-5.5 Slice 1 persists :class:`invest_domain.research.research_run
    .ResearchResult` into ``analytics.research_results``. The synthetic
    ``result_id`` UUID is the storage-assigned primary key; the natural
    unique constraint ``uq_research_results_run_id`` enforces the
    one-immutable-result-per-run invariant so a succeeded run cannot
    publish two rows.

    ``risks`` and ``evidence_ids`` are JSONB arrays; the
    ``jsonb_typeof(...) = 'array'`` and
    ``jsonb_array_length(evidence_ids) >= 1`` CHECK constraints reject
    malformed payloads at the database boundary so a buggy
    application-service path cannot smuggle non-array evidence past
    the validator. The immutable ``run_id`` FK back to
    ``analytics.research_runs.run_id`` plus the unique constraint on
    the same column together guarantee that a result, once published,
    can never be replaced or duplicated.
    """

    __tablename__ = "research_results"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_research_results_run_id"),
        ForeignKeyConstraint(
            ["run_id"],
            ["analytics.research_runs.run_id"],
            name="fk_research_results_run_id_research_runs",
        ),
        ForeignKeyConstraint(
            ["evidence_pack_id"],
            ["analytics.research_evidence_packs.id"],
            name=(
                "fk_research_results_evidence_pack_id_research_evidence_packs"
            ),
        ),
        CheckConstraint(
            "btrim(conclusion) <> ''",
            name="conclusion_nonblank",
        ),
        CheckConstraint(
            "btrim(report_markdown) <> ''",
            name="report_markdown_nonblank",
        ),
        CheckConstraint(
            "btrim(model_key) <> ''",
            name="model_key_nonblank",
        ),
        CheckConstraint(
            "btrim(model_version) <> ''",
            name="model_version_nonblank",
        ),
        CheckConstraint(
            "btrim(playbook_version) <> ''",
            name="playbook_version_nonblank",
        ),
        CheckConstraint(
            "btrim(adapter_version) <> ''",
            name="adapter_version_nonblank",
        ),
        CheckConstraint(
            "jsonb_typeof(risks) = 'array'",
            name="risks_array",
        ),
        CheckConstraint(
            "jsonb_typeof(evidence_ids) = 'array'",
            name="evidence_ids_array",
        ),
        CheckConstraint(
            "jsonb_array_length(evidence_ids) >= 1",
            name="evidence_ids_nonempty",
        ),
        Index("ix_research_results_run_id", "run_id"),
        Index(
            "ix_research_results_evidence_pack_id",
            "evidence_pack_id",
        ),
        {"schema": "analytics"},
    )

    result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        default=list,
    )
    evidence_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    model_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    playbook_version: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
