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
    Index,
    Integer,
    MetaData,
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