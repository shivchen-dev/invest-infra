"""ETF daily-bars ETL service (PR-06).

The service module hosts the testable, asset-agnostic ETL logic for
the ``etf_daily_bars`` vertical slice. Dagster assets in
:mod:`invest_pipeline.assets` are thin wrappers that wire the
``FixtureDevInstrumentProvider`` and the configured
:class:`SqlAlchemyUnitOfWork` into these functions.

Two transactions make up the slice:

- :func:`write_etf_daily_bars_raw` calls the Provider, persists the
  PR-02 three-layer evidence bundle to ``raw.provider_requests`` /
  ``raw.provider_attempts`` / ``raw.provider_batches``, and returns a
  :class:`RawEtlResult` (re-exported from
  :mod:`invest_pipeline.etf_instruments`) carrying the assigned UUIDs.
  The standardized daily-bar records are serialised into a JSONB
  sidecar on the attempt's ``response_payload_json`` (the same wire
  pattern :mod:`invest_pipeline.etf_instruments` uses for ETF master
  data). Failed attempts persist the request + attempt only; no batch
  row is created (per ``ck_provider_attempts_failed_has_error`` and
  the domain rule that a failed attempt must not yield a
  :class:`ProviderBatch`).
- :func:`upsert_etf_daily_bars` re-opens a fresh UoW, locates the
  latest successful attempt for the (provider, dataset, request_key)
  triplet, deserializes the sidecar, resolves the real
  ``core.instruments.id`` for every ``symbol``, and upserts the
  standardized bars into ``core.daily_bars`` under the ADR-0006 §3
  revision rules: a re-collect of identical business content is a
  no-op; a content change increments the revision.

Both functions accept a ``session_factory`` so unit tests can inject a
factory that hands out a :class:`unittest.mock.MagicMock` session —
the asset-level integration is verified via the test suite without
booting a real database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttemptStatus,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_storage import (
    NewDailyBar,
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
)
from invest_storage.unit_of_work import SessionProvider, SqlAlchemyUnitOfWork
from sqlalchemy.orm import sessionmaker

from invest_pipeline.adapters.fixture_dev.adapter import (
    deserialize_daily_bars,
    serialize_daily_bars,
)
from invest_pipeline.etf_instruments import (
    RawEtlResult,
    UnitOfWorkFactory,
    _coerce_session_factory,
)

__all__ = [
    "RawEtlResult",
    "UpsertSummary",
    "upsert_etf_daily_bars",
    "write_etf_daily_bars_raw",
]


@dataclass(frozen=True, slots=True)
class UpsertSummary:
    """Return shape of :func:`upsert_etf_daily_bars`.

    Distinguishes rows that the repository actually inserted
    (``inserted``) from rows that the row-hash comparison left
    untouched (``skipped``). The two counts sum to the number of
    bars the Provider returned; a re-collect of identical content
    therefore reports ``inserted=0`` and ``skipped=record_count`` so
    the operator can see at a glance that the run was idempotent.
    """

    inserted: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.skipped


class _ProviderPort(Protocol):
    """Structural port for the ETF daily-bars Provider.

    Mirrors the subset of :class:`FixtureDevInstrumentProvider` the
    service depends on so a stub provider can be injected in unit
    tests. Retained as a slice-specific Protocol — the
    ``fetch_daily_bars`` signature (symbols + date range) differs
    semantically from :mod:`invest_pipeline.etf_instruments`'s
    ``fetch_instruments`` (as_of date), so a generic shared base would
    buy nothing.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[Any, Any, Any]: ...


def _now() -> datetime:
    return datetime.now(UTC)


def write_etf_daily_bars_raw(
    provider: _ProviderPort,
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> RawEtlResult:
    """Run the PR-02 three-layer evidence write for ETF daily bars.

    The function persists the ``(ProviderRequest, ProviderAttempt,
    ProviderBatch)`` triple returned by ``provider.fetch_daily_bars``
    in order so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The standardized bars are serialised into a JSONB sidecar on the
    attempt's ``response_payload_json`` so the downstream upsert
    service can re-read them without re-calling the Provider.

    Failure semantics (mirrors
    :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`):

    - ``ProviderAttempt.status == FAILED`` → only the request (status
      ``failed``) and the attempt (status ``failed`` with mandatory
      ``error_stage`` / ``error_code``) are persisted. No batch row is
      created.
    - ``ProviderAttempt.status == SUCCEEDED`` and a non-``None`` batch
      → the request, the attempt and the batch are all persisted. The
      attempt's ``response_payload_json`` carries the sidecar.
    - ``ProviderAttempt.status == SUCCEEDED`` and ``batch is None`` →
      the request and attempt are persisted with status ``partial``;
      no batch is created.
    """

    if not symbols:
        raise ValueError(
            "write_etf_daily_bars_raw requires at least one symbol"
        )
    if end_date < start_date:
        raise ValueError(
            f"end_date {end_date.isoformat()} must be on or after "
            f"start_date {start_date.isoformat()}"
        )

    request, attempt, batch = provider.fetch_daily_bars(
        symbols, start_date, end_date
    )
    finished_at = attempt.finished_at or _now()

    factory = _coerce_session_factory(session_factory)
    with unit_of_work_factory(factory) as uow:
        stored_request = uow.provider_requests.add(
            NewProviderRequest(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                status="pending",
                request_params=dict(request.params),
            )
        )

        if attempt.status is ProviderAttemptStatus.FAILED:
            stored_attempt = uow.provider_attempts.add(
                NewProviderAttempt(
                    provider_request_id=stored_request.id,
                    attempt_no=attempt.attempt_number,
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

        response_payload_json: str | None = None
        if batch is not None:
            sidecar_records = [
                {
                    "symbol": bar.source.provider_key,
                    "trade_date": bar.trade_date.isoformat(),
                    "open": format(bar.open, "f") if bar.open is not None else None,
                    "high": format(bar.high, "f") if bar.high is not None else None,
                    "low": format(bar.low, "f") if bar.low is not None else None,
                    "close": format(bar.close, "f") if bar.close is not None else None,
                    "prev_close": (
                        format(bar.prev_close, "f")
                        if bar.prev_close is not None
                        else None
                    ),
                    "volume": (
                        format(bar.volume, "f")
                        if bar.volume is not None
                        else None
                    ),
                    "amount": (
                        format(bar.amount, "f")
                        if bar.amount is not None
                        else None
                    ),
                    "trading_status": bar.trading_status.value,
                }
                for bar in batch.records
            ]
            response_payload_json = serialize_daily_bars(
                sidecar_records,
                source_batch_id=batch.attempt_id,
                observed_at=batch.records[0].source.observed_at
                if batch.records
                else finished_at,
            )

        stored_attempt = uow.provider_attempts.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=attempt.attempt_number,
                started_at=attempt.started_at,
                finished_at=finished_at,
                status="succeeded",
                response_payload_sha256=batch.raw_payload_hash
                if batch is not None
                else "0" * 64,
                response_payload_json=response_payload_json,
            )
        )

        stored_batch_id: UUID | None = None
        record_count = 0
        request_status = "succeeded"
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
        else:
            request_status = "partial"

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


def upsert_etf_daily_bars(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    provider_key: str = "fixture_dev",
    dataset_key: str = "etf_daily_bars",
    request_key: str | None = None,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> UpsertSummary:
    """Upsert standardized ETF daily bars into ``core.daily_bars``.

    The function locates the latest successful attempt for
    ``(provider_key, dataset_key, request_key)``, deserializes the
    sidecar, looks up the real ``core.instruments.id`` per
    ``(symbol, exchange)`` and delegates to
    :meth:`SqlAlchemyDailyBarRepository.upsert_many`. The repository
    applies the ADR-0006 §3 revision rules: identical business
    content is a no-op, content change increments the revision.

    ``request_key`` is required when the underlying request_key shape
    is not the conventional
    ``daily-bars-{start}-{end}-{symbols}``; callers that know the
    logical key should pass it explicitly. ``LookupError`` is raised
    if no successful attempt is found for the given logical key so a
    stale downstream trigger is surfaced loudly rather than silently
    producing zero rows.
    """

    if not request_key:
        raise ValueError(
            "upsert_etf_daily_bars requires an explicit request_key; "
            "the daily-bars logical key is not derivable from a single "
            "date"
        )

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
                "run etf_daily_bars_raw first"
            )
        attempts = uow.provider_attempts.list_by_request(
            stored_request.id, limit=10
        )
        succeeded_attempt = next(
            (a for a in attempts if a.status == "succeeded"), None
        )
        if succeeded_attempt is None:
            raise LookupError(
                f"no succeeded provider_attempts row for request "
                f"{stored_request.id}; etf_daily_bars_raw must have "
                "persisted a successful attempt first"
            )

        sidecar = deserialize_daily_bars(succeeded_attempt.response_payload_json)
        if not sidecar:
            return UpsertSummary(inserted=0, skipped=0)

        new_bars = _build_new_bars(
            sidecar=sidecar,
            source_batch_id=succeeded_attempt.id,
            instruments_lookup=uow.instruments.get_by_business_key,
        )
        if not new_bars:
            return UpsertSummary(inserted=0, skipped=len(sidecar))

        written = uow.daily_bars.upsert_many(new_bars)
        inserted = len(written)
        skipped = len(sidecar) - inserted
        return UpsertSummary(inserted=inserted, skipped=skipped)


def _build_new_bars(
    *,
    sidecar: Sequence[dict[str, Any]],
    source_batch_id: UUID,
    instruments_lookup: Any,
) -> list[NewDailyBar | DailyBar]:
    """Map the sidecar records to ``NewDailyBar`` / ``DailyBar`` rows.

    The function walks the sidecar, looks up the real
    ``core.instruments.id`` via the partial unique business key
    ``(symbol, exchange) WHERE delist_date IS NULL`` and constructs a
    domain :class:`DailyBar` for every record whose instrument is
    known. A sidecar record whose ``symbol`` does not match an active
    instrument row is silently dropped (with a ``print``-level warning
    not raised) — the application service treats it as a stale fixture
    and lets the operator fix the upstream ingest. The constructed
    :class:`DailyBar` carries the full audit ``BarSource`` so the
    repository only needs the standardized fields.
    """


    new_bars: list[NewDailyBar | DailyBar] = []
    for entry in sidecar:
        symbol = entry["symbol"]
        exchange = _exchange_for_symbol(symbol)
        instrument = instruments_lookup(exchange=exchange, symbol=symbol)
        if instrument is None:
            # Drop silently; caller can audit via the empty result.
            continue
        trade_date = date.fromisoformat(entry["trade_date"])
        observed_at = datetime.fromisoformat(entry["observed_at"])
        source = BarSource(
            provider_key=entry["source_provider"],
            source_batch_id=UUID(entry["source_batch_id"]),
            observed_at=observed_at,
        )
        bar = DailyBar.build(
            instrument_id=InstrumentId(instrument.instrument_id.value)
            if instrument.instrument_id is not None
            else InstrumentId.generate(),
            trade_date=trade_date,
            open=_maybe_decimal(entry["open"]),
            high=_maybe_decimal(entry["high"]),
            low=_maybe_decimal(entry["low"]),
            close=_maybe_decimal(entry["close"]),
            prev_close=_maybe_decimal(entry["prev_close"]),
            volume=_maybe_decimal(entry["volume"]),
            amount=_maybe_decimal(entry["amount"]),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus(entry["trading_status"]),
            source=source,
            revision=1,
        )
        new_bars.append(bar)
    return new_bars


def _exchange_for_symbol(symbol: str) -> str:
    """Return the SSE / SZSE exchange for a fixture_dev symbol.

    The fixture is hard-coded to A-share ETFs, and the SSE / SZSE
    split is stable across the universe (6xxxxx = SSE, 1xxxxx = SZSE).
    Looking the exchange up by symbol here keeps the sidecar free of
    the ``exchange`` field and keeps this service independent of
    :mod:`invest_pipeline.etf_instruments` (which would create a
    circular import).
    """

    if symbol.startswith("5") or symbol.startswith("6"):
        return "SSE"
    if symbol.startswith("1") or symbol.startswith("2"):
        return "SZSE"
    raise ValueError(
        f"cannot infer exchange for symbol {symbol!r}: fixture_dev only "
        "covers A-share SSE / SZSE ETFs"
    )


def _maybe_decimal(value: Any) -> Any:
    """Return ``Decimal(value)`` when ``value`` is a non-empty string, else ``None``."""

    from decimal import Decimal

    if value is None or value == "":
        return None
    return Decimal(value)
