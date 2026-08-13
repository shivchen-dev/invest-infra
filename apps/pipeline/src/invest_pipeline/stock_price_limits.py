"""Stock price-limits ETL service (Stage 4C Phase 1 Task 1.3).

The service module hosts the testable, asset-agnostic ETL logic for
the ``stock_price_limits`` vertical slice. Dagster assets in
:mod:`invest_pipeline.assets` are thin wrappers that wire the
``FixtureDevStockPriceLimitsProvider`` and the configured
:class:`SqlAlchemyUnitOfWork` into these functions.

Two transactions make up the slice:

- :func:`write_stock_price_limits_raw` calls the Provider, persists the
  PR-02 three-layer evidence bundle to ``raw.provider_requests`` /
  ``raw.provider_attempts`` / ``raw.provider_batches``, and returns a
  :class:`RawEtlResult` carrying the assigned UUIDs.
  Failed attempts persist the request + attempt only; no batch row is
  created, per ``ck_provider_attempts_failed_has_error`` and the
  domain rule that a failed attempt must not yield a
  :class:`ProviderBatch`.
- :func:`upsert_stock_price_limits` re-opens a fresh UoW, locates the
  latest successful attempt for the ``(provider, dataset, request_key)``
  triplet, deserializes the records from the attempt's
  ``response_payload_json`` sidecar, resolves the active
  ``core.instruments.id`` per ``(exchange, instrument_id)`` and
  upserts the price-limit rows into ``core.stock_price_limits`` under
  the ADR-0006 §3 revision rules. ``unknown`` status fails closed
  (raises :class:`ValueError`): the application service refuses to
  write ``core`` rows for an indeterminate policy result so an
  upstream regime coverage gap cannot silently land in
  ``core.stock_price_limits``.

Both functions accept a ``session_factory`` so unit tests can inject a
factory that hands out a :class:`unittest.mock.MagicMock` session -
the asset-level integration is verified via the test suite without
booting a real database.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from invest_domain.market_data.models import (
    ProviderAttemptStatus,
)
from invest_storage import (
    NewPriceLimit,
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
)
from invest_storage.unit_of_work import SessionProvider, SqlAlchemyUnitOfWork
from sqlalchemy.orm import sessionmaker

_PRICE_LIMITS_SCHEMA_VERSION = 1
_VALID_STATUSES: frozenset[str] = frozenset({"known", "unlimited", "unknown"})


@dataclass(frozen=True, slots=True)
class RawEtlResult:
    """Return shape of :func:`write_stock_price_limits_raw`.

    Carries the storage-assigned UUIDs plus the terminal status of the
    attempt so the asset metadata can surface whether the batch was
    actually persisted or the attempt failed before producing one.
    """

    request_id: UUID
    attempt_id: UUID
    batch_id: UUID | None
    request_status: str
    attempt_status: str
    record_count: int


@dataclass(frozen=True, slots=True)
class PriceLimitUpsertSummary:
    """Return shape of :func:`upsert_stock_price_limits`.

    Mirrors :class:`invest_pipeline.etf_daily_bars.UpsertSummary` so the
    stock-price-limits asset surfaces an identical summary shape. The
    two counts sum to the number of sidecar records the upstream
    attempt persisted; a re-collect of identical content therefore
    reports ``inserted=0`` and ``skipped=record_count`` so the operator
    can see at a glance that the run was idempotent. ``skipped`` covers
    both ``(exchange, instrument_id)`` lookups that did not match an
    active ``core.instruments`` row and ``unknown`` status records
    that the application service refused to write.
    """

    inserted: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.skipped


class _ProviderPort(Protocol):
    """Structural port for the stock price-limits Provider.

    Mirrors the subset of :class:`FixtureDevStockPriceLimitsProvider`
    the service depends on so a stub provider can be injected in unit
    tests.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_price_limits(
        self,
        symbols: Sequence[str],
        trade_date: date,
    ) -> tuple[Any, Any, Any]: ...


UnitOfWorkFactory = Any


def _coerce_session_factory(
    session_factory: SessionProvider | sessionmaker[Any],
) -> sessionmaker[Any]:
    """Return a ``sessionmaker`` regardless of the caller-supplied shape.

    The public API accepts either a :class:`SessionProvider` callable
    or a SQLAlchemy ``sessionmaker``; both are accepted by
    :class:`SqlAlchemyUnitOfWork`, but the type checker is happier when
    we narrow to a single shape.
    """

    return session_factory  # type: ignore[return-value]


def _now() -> datetime:
    return datetime.now(UTC)


def _build_sidecar_record(record: Any) -> dict[str, Any]:
    """Build one sidecar dict from a fetched :class:`PriceLimitRecord`.

    The sidecar stores the raw string forms of the decimal prices so the
    downstream upsert can ``Decimal(...)`` them at parse time without
    losing precision through an intermediate ``float``. ``status`` is
    kept as the policy result's vocabulary (``known`` / ``unlimited``
    / ``unknown``); the upsert path refuses ``unknown`` records
    outright.
    """

    limit_up = record.limit_up_price
    limit_down = record.limit_down_price
    return {
        "instrument_id": record.instrument_id,
        "exchange": record.exchange,
        "trade_date": record.trade_date.isoformat(),
        "regime_id": record.rule_version,
        "limit_up_price": str(limit_up) if limit_up is not None else None,
        "limit_down_price": str(limit_down) if limit_down is not None else None,
        "status": record.status,
        "reference_price": str(record.prev_close),
        "row_hash": record.row_hash,
    }


def serialize_stock_price_limits(
    sidecar_records: Sequence[dict[str, Any]],
    *,
    source_batch_id: Any,
    observed_at: datetime,
    provider_key: str = "fixture_dev",
) -> str:
    """Build the deterministic JSONB sidecar the core asset reads back.

    The sidecar is stamped onto ``raw.provider_attempts.response_payload_json``
    so the downstream ``upsert_stock_price_limits`` asset can
    deserialize the records back into :class:`NewPriceLimit` instances
    without re-calling the Provider. The schema version is part of the
    payload so future format changes can be detected. The output is
    sorted (``sort_keys=True``) so re-collects of identical content
    produce byte-identical payloads, which keeps the
    ``raw.provider_attempts.response_payload_sha256`` stable across
    reruns.
    """

    payload = {
        "schema_version": _PRICE_LIMITS_SCHEMA_VERSION,
        "records": [
            {
                **record,
                "source_provider": provider_key,
                "observed_at": observed_at.isoformat(),
                "source_batch_id": str(source_batch_id),
            }
            for record in sidecar_records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def deserialize_stock_price_limits(
    payload_json: str | bytes | bytearray | None,
) -> list[dict[str, Any]]:
    """Inverse of :func:`serialize_stock_price_limits`.

    The application service uses the returned dicts as a transport
    shape: it looks up the real ``core.instruments.id`` by
    ``(exchange, instrument_id)`` and constructs the final
    :class:`NewPriceLimit` for the repository. Unknown statuses are
    kept in the returned dicts - the service refuses them at the
    upsert stage, not here.
    """

    if payload_json is None:
        return []
    if isinstance(payload_json, (bytes, bytearray)):
        payload_json = payload_json.decode("utf-8")
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise ValueError(
            f"stock price-limits payload must be a dict, got {type(payload).__name__}"
        )
    if payload.get("schema_version") != _PRICE_LIMITS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported stock price-limits payload schema_version "
            f"{payload.get('schema_version')!r}; expected "
            f"{_PRICE_LIMITS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            f"stock price-limits payload 'records' must be a list, "
            f"got {type(raw_records).__name__}"
        )
    return [dict(entry) for entry in raw_records]


def write_stock_price_limits_raw(
    provider: _ProviderPort,
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    symbols: Sequence[str],
    trade_date: date,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> RawEtlResult:
    """Run the PR-02 three-layer evidence write for stock price limits.

    The function persists the ``(ProviderRequest, ProviderAttempt,
    ProviderBatch)`` triple returned by ``provider.fetch_price_limits``
    in order so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The logical request is resolved through
    :meth:`SqlAlchemyProviderRequestRepository.get_or_create` so a
    re-run of the same ``(provider_key, dataset_key, request_key)``
    triplet reuses the existing ``raw.provider_requests`` row instead
    of triggering the ``uq_provider_requests_logical_key`` constraint;
    a fresh attempt (and batch, when appropriate) is still recorded so
    the audit trail captures the rerun.

    The attempt is added with status ``running`` and
    ``response_payload_json=None`` first, then the batch (when present)
    is added so the sidecar can stamp the persisted
    ``raw.provider_batches.id`` onto every record's
    ``source_batch_id`` audit field. The attempt is finalised through
    :meth:`SqlAlchemyProviderAttemptRepository.mark_succeeded` which
    stamps ``status='succeeded'``, ``response_payload_sha256`` and the
    JSONB sidecar in one go. Mirrors the two-step add/mark_succeeded
    pattern :func:`invest_pipeline.stock_daily_bars.write_stock_daily_bars_raw`
    uses for the daily-bars sidecar so the two price-quoting slices
    share the same write-side semantics.

    Failure semantics:

    - ``ProviderAttempt.status == FAILED`` - only the request (status
      ``failed``) and the attempt (status ``failed`` with mandatory
      ``error_stage`` / ``error_code``) are persisted. No batch row is
      created, mirroring the domain contract that a failed attempt
      leaves no batch behind.
    - ``ProviderAttempt.status == SUCCEEDED`` and a non-``None`` batch
      - the request, the attempt (with the sidecar carrying the
      persisted ``source_batch_id``) and the batch are all persisted.
    - ``ProviderAttempt.status == SUCCEEDED`` and ``batch is None`` -
      the request and attempt are persisted with status ``partial``;
      no batch is created.
    """

    if not symbols:
        raise ValueError("write_stock_price_limits_raw requires at least one symbol")

    request, attempt, batch = provider.fetch_price_limits(symbols, trade_date)
    finished_at = attempt.finished_at or _now()

    factory = _coerce_session_factory(session_factory)
    with unit_of_work_factory(factory) as uow:
        stored_request = uow.provider_requests.get_or_create(
            NewProviderRequest(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                status="pending",
                request_params=dict(request.params),
            )
        )

        existing_attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=1000
        )
        next_attempt_no = (
            max(a.attempt_no for a in existing_attempts) + 1
            if existing_attempts
            else attempt.attempt_number
        )

        if attempt.status is ProviderAttemptStatus.FAILED:
            stored_attempt = uow.provider_attempts.add(
                NewProviderAttempt(
                    provider_request_id=stored_request.id,
                    attempt_no=next_attempt_no,
                    started_at=attempt.started_at,
                    finished_at=finished_at,
                    status="failed",
                    error_stage=attempt.error_stage.value
                    if attempt.error_stage is not None
                    else "provider",
                    error_code=attempt.error_code or "unknown_error",
                    error_message=attempt.error_message,
                )
            )
            uow.provider_requests.mark_status(
                stored_request.id, status="failed", completed_at=finished_at
            )
            return RawEtlResult(
                request_id=stored_request.id,
                attempt_id=stored_attempt.id,
                batch_id=None,
                request_status="failed",
                attempt_status="failed",
                record_count=0,
            )

        stored_attempt = uow.provider_attempts.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=next_attempt_no,
                started_at=attempt.started_at,
                finished_at=finished_at,
                status="running",
                response_payload_sha256=None,
                response_payload_json=None,
            )
        )

        stored_batch_id: UUID | None = None
        record_count = 0
        request_status = "succeeded"
        response_payload_json: str | None = None
        if batch is not None:
            stored_batch = uow.provider_batches.add(
                NewProviderBatch(
                    provider_request_id=stored_request.id,
                    provider_attempt_id=stored_attempt.id,
                    provider_key=request.provider_key,
                    dataset_key=request.dataset_key,
                    record_count=len(batch.records),
                    payload_sha256=batch.raw_payload_hash,
                    status=batch.status.value,
                    warnings=list(batch.warnings),
                )
            )
            stored_batch_id = stored_batch.id
            record_count = len(batch.records)
            sidecar_records = [_build_sidecar_record(r) for r in batch.records]
            response_payload_json = serialize_stock_price_limits(
                sidecar_records,
                source_batch_id=stored_batch.id,
                observed_at=finished_at,
                provider_key=request.provider_key,
            )
        else:
            request_status = "partial"

        uow.provider_attempts.mark_succeeded(
            stored_attempt.id,
            finished_at=finished_at,
            response_payload_sha256=batch.raw_payload_hash
            if batch is not None
            else "0" * 64,
            response_payload_json=response_payload_json,
        )

        uow.provider_requests.mark_status(
            stored_request.id,
            status=request_status,
            completed_at=finished_at,
        )
        return RawEtlResult(
            request_id=stored_request.id,
            attempt_id=stored_attempt.id,
            batch_id=stored_batch_id,
            request_status=request_status,
            attempt_status="succeeded",
            record_count=record_count,
        )


def _build_new_limits(
    *,
    sidecar: Sequence[dict[str, Any]],
    instruments_lookup: Any,
) -> tuple[list[NewPriceLimit], int]:
    """Map the sidecar records to ``NewPriceLimit`` rows.

    Walks the sidecar, looks up the real ``core.instruments.id`` via
    the partial unique business key ``(symbol, exchange) WHERE
    delist_date IS NULL`` and constructs a :class:`NewPriceLimit` for
    every record whose instrument is known. The exchange comes from
    the sidecar ``exchange`` field - populated by the raw writer from
    the provider's :attr:`PriceLimitRecord.exchange` - and is never
    inferred from the symbol prefix. A sidecar row whose
    ``(instrument_id, exchange)`` does not match an active instrument
    row is silently dropped so the operator sees the empty result via
    :attr:`PriceLimitUpsertSummary.skipped` rather than a hard error.

    ``unknown`` status records fail closed: the application service
    refuses to write ``core.stock_price_limits`` rows for indeterminate
    policy results so an upstream regime coverage gap cannot silently
    land in the core table.
    """

    new_limits: list[NewPriceLimit] = []
    skipped = 0
    for entry in sidecar:
        symbol = entry.get("instrument_id")
        exchange = entry.get("exchange")
        status = entry.get("status")
        if not isinstance(symbol, str) or not isinstance(exchange, str):
            raise ValueError(
                "stock price-limits sidecar record must carry string "
                f"instrument_id/exchange; got {symbol!r}/{exchange!r}"
            )
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"stock price-limits sidecar record carries unsupported "
                f"status {status!r} for {exchange}/{symbol}; expected one of "
                f"{sorted(_VALID_STATUSES)}"
            )
        if status == "unknown":
            raise ValueError(
                f"stock price-limits sidecar contains an 'unknown' status "
                f"record for {exchange}/{symbol}; refusing to upsert "
                "indeterminate policy results to core.stock_price_limits"
            )
        instrument = instruments_lookup(exchange=exchange, symbol=symbol)
        if instrument is None:
            skipped += 1
            continue
        instrument_uuid = (
            instrument.instrument_id.value
            if instrument.instrument_id is not None
            else None
        )
        if instrument_uuid is None:
            raise ValueError(
                f"instrument {exchange}/{symbol} resolved without a "
                "storage-side instrument_id; refusing to upsert a "
                "price-limit row with a null FK"
            )
        limit_up_raw = entry.get("limit_up_price")
        limit_down_raw = entry.get("limit_down_price")
        reference_raw = entry.get("reference_price")
        regime_id = entry.get("regime_id") or "unknown"
        new_limits.append(
            NewPriceLimit(
                instrument_id=instrument_uuid,
                trade_date=date.fromisoformat(entry["trade_date"]),
                regime_id=regime_id,
                limit_up_price=Decimal(limit_up_raw) if limit_up_raw else None,
                limit_down_price=Decimal(limit_down_raw) if limit_down_raw else None,
                status=status,
                reference_price=Decimal(reference_raw) if reference_raw else None,
                source_provider=entry["source_provider"],
                source_batch_id=UUID(entry["source_batch_id"]),
                observed_at=datetime.fromisoformat(entry["observed_at"]),
                row_hash=entry["row_hash"],
            )
        )
    return new_limits, skipped


def upsert_stock_price_limits(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    trade_date: date,
    symbols: Sequence[str],
    provider_key: str = "fixture_dev",
    dataset_key: str = "stock_price_limits",
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> PriceLimitUpsertSummary:
    """Upsert price-limit facts into ``core.stock_price_limits``.

    The function locates the latest successful attempt for
    ``(provider_key, dataset_key="stock_price_limits",
    request_key=price-limits-{trade_date}-{symbols})``, deserializes the
    records from the attempt's ``response_payload_json`` sidecar,
    resolves the real ``core.instruments.id`` per
    ``(exchange, instrument_id)`` pair (the exchange comes from the
    sidecar, never from the symbol prefix) and delegates to
    :meth:`SqlAlchemyStockPriceLimitRepository.upsert_many`. The
    repository applies the ADR-0006 §3 revision rules: identical
    business content (``row_hash`` match) is a no-op, content change
    increments the revision.

    ``unknown`` status records fail closed with :class:`ValueError`:
    the application service refuses to write ``core.stock_price_limits``
    rows for indeterminate policy results so a stale regime cannot
    silently land in the core table. ``(exchange, instrument_id)``
    pairs that do not match an active ``core.instruments`` row are
    silently dropped (with a count tracked via
    :attr:`PriceLimitUpsertSummary.skipped`) - the application service
    treats them as a stale fixture and lets the operator fix the
    upstream universe ingest.

    Returns :class:`PriceLimitUpsertSummary` with ``inserted`` (rows
    actually written to ``core.stock_price_limits``) and ``skipped``
    (records the upsert refused - either unknown instruments or
    unparseable sidecar entries). Raises :class:`LookupError` if no
    successful attempt is found for the given logical key so a stale
    downstream trigger is surfaced loudly rather than silently
    producing zero rows.
    """

    if not symbols:
        raise ValueError("upsert_stock_price_limits requires at least one symbol")

    request_key = f"price-limits-{trade_date.isoformat()}-{'-'.join(symbols)}"
    factory = _coerce_session_factory(session_factory)
    with unit_of_work_factory(factory) as uow:
        stored_request = uow.provider_requests.get_by_logical_key(
            provider_key=provider_key,
            dataset_key=dataset_key,
            request_key=request_key,
        )
        if stored_request is None:
            raise LookupError(
                f"no provider_requests row for "
                f"({provider_key!r}, {dataset_key!r}, {request_key!r}); "
                "run write_stock_price_limits_raw first"
            )
        attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=1000
        )
        succeeded_attempts = [a for a in attempts if a.status == "succeeded"]
        if not succeeded_attempts:
            raise LookupError(
                f"no succeeded provider_attempts row for request "
                f"{stored_request.id}; write_stock_price_limits_raw must "
                "have persisted a successful attempt first"
            )
        succeeded_attempt = max(
            succeeded_attempts,
            key=lambda a: (a.finished_at, a.attempt_no),
        )

        sidecar = deserialize_stock_price_limits(succeeded_attempt.response_payload_json)
        if not sidecar:
            return PriceLimitUpsertSummary(inserted=0, skipped=0)

        new_limits, skipped = _build_new_limits(
            sidecar=sidecar,
            instruments_lookup=uow.instruments.get_by_business_key,
        )

        if not new_limits:
            return PriceLimitUpsertSummary(inserted=0, skipped=skipped)

        written = uow.stock_price_limits.upsert_many(new_limits)
        inserted = len(written)
        return PriceLimitUpsertSummary(inserted=inserted, skipped=skipped)


__all__ = [
    "PriceLimitUpsertSummary",
    "RawEtlResult",
    "deserialize_stock_price_limits",
    "serialize_stock_price_limits",
    "upsert_stock_price_limits",
    "write_stock_price_limits_raw",
]