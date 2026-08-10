"""Stock daily-bars ETL service (vertical slice on top of PR-06).

Mirrors :mod:`invest_pipeline.etf_daily_bars` but for A-share stocks
and the ``stock_daily_bars`` dataset key. The slice only adds a new
service module — Dagster assets and real Provider wiring are left for
a follow-up — and reuses every PR-06 building block so the contract
stays symmetric:

- :func:`write_stock_daily_bars_raw` calls the Provider, persists the
  PR-02 three-layer evidence bundle to ``raw.provider_requests`` /
  ``raw.provider_attempts`` / ``raw.provider_batches``, and returns a
  :class:`RawEtlResult` carrying the assigned UUIDs. The standardized
  daily-bar records are serialised into a JSONB sidecar on the
  attempt's ``response_payload_json`` — same wire pattern the ETF
  service uses — but the sidecar carries **both** ``symbol`` and
  ``exchange`` so the upsert service does not have to infer the
  exchange from the code prefix. The exchange comes from the
  provider's ``symbol_and_exchange_for_instrument_id`` reverse lookup;
  stock symbols span more than one exchange prefix (SH 6xxxxx, SZ
  0xxxxx / 3xxxxx) so guessing by prefix would mis-route a non-trivial
  share of the universe. Failed attempts persist the request + attempt
  only; no batch row is created, mirroring the contract :mod:`etf_daily_bars`
  enforces.
- :func:`upsert_stock_daily_bars` re-opens a fresh UoW, locates the
  latest successful attempt for the ``(provider, dataset, request_key)``
  triplet, deserializes the sidecar, resolves the real
  ``core.instruments.id`` for every ``(symbol, exchange)`` pair, and
  upserts the standardized bars into ``core.daily_bars`` under the
  ADR-0006 §3 revision rules.

Both functions accept a ``session_factory`` so unit tests can inject a
factory that hands out a :class:`unittest.mock.MagicMock` session —
the asset-level integration is verified via the test suite without
booting a real database.

The slice intentionally stops short of touching the ETF service,
:mod:`invest_pipeline.assets`, the Tushare ``etf`` adapter, or any
CLI wiring. The Tushare ``StockTushareProvider`` already carries the
``symbol_and_exchange_for_instrument_id`` reverse lookup (added in an
earlier PR); no further Provider interface changes are required for
this slice.
"""

from __future__ import annotations

import json
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

from invest_pipeline.etf_instruments import (
    RawEtlResult,
    UnitOfWorkFactory,
    _coerce_session_factory,
)

_STOCK_DAILY_BARS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class UpsertSummary:
    """Return shape of :func:`upsert_stock_daily_bars`.

    Mirrors :class:`invest_pipeline.etf_daily_bars.UpsertSummary` so
    the stock and ETF downstream assets surface identically. The two
    counts sum to the number of sidecar records the upstream attempt
    persisted; a re-collect of identical content therefore reports
    ``inserted=0`` and ``skipped=record_count`` so the operator can see
    at a glance that the run was idempotent.
    """

    inserted: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.skipped


class _StockProviderPort(Protocol):
    """Structural port for the stock daily-bars Provider.

    Mirrors the subset of :class:`invest_pipeline.adapters.tushare.StockTushareProvider`
    the service depends on so a stub provider can be injected in unit
    tests. Distinct from the ETF daily-bars Protocol because the
    reverse lookup must return ``(symbol, exchange)`` — stocks span
    more than one exchange prefix so the ETF's symbol-only reverse
    lookup would force the upsert to guess the exchange by code
    prefix, which is exactly what we are not allowed to do.

    :meth:`symbol_and_exchange_for_instrument_id` is the only
    authoritative way the service recovers SSE / SZSE for a fetched
    bar; a ``None`` return surfaces as :class:`LookupError` so a
    placeholder leak between provider instances fails loudly instead
    of silently defaulting ``exchange`` to ``"SSE"``.
    """

    @property
    def provider_key(self) -> str: ...

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[Any, Any, Any]: ...

    def symbol_and_exchange_for_instrument_id(
        self, instrument_id: Any
    ) -> tuple[str, str] | None: ...


def _now() -> datetime:
    return datetime.now(UTC)


def write_stock_daily_bars_raw(
    provider: _StockProviderPort,
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> RawEtlResult:
    """Run the PR-02 three-layer evidence write for stock daily bars.

    Persists the ``(ProviderRequest, ProviderAttempt, ProviderBatch)``
    triple returned by ``provider.fetch_daily_bars`` in order so the
    FK wiring on ``provider_attempts`` and ``provider_batches``
    resolves against the storage-assigned UUIDs. The standardized bars
    are serialised into a JSONB sidecar on the attempt's
    ``response_payload_json``; every sidecar record carries both
    ``symbol`` and ``exchange`` so the downstream upsert can resolve
    the real ``core.instruments.id`` without inferring the exchange
    from the code prefix.

    Failure semantics (mirrors
    :func:`invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw`):

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
        raise ValueError("write_stock_daily_bars_raw requires at least one symbol")
    if end_date < start_date:
        raise ValueError(
            f"end_date {end_date.isoformat()} must be on or after "
            f"start_date {start_date.isoformat()}"
        )

    request, attempt, batch = provider.fetch_daily_bars(symbols, start_date, end_date)
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

        existing_attempts = uow.provider_attempts.list_by_request(stored_request.id, limit=1000)
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
            sidecar_records = [
                _build_sidecar_record(bar, request.provider_key, provider) for bar in batch.records
            ]
            response_payload_json = serialize_stock_daily_bars(
                sidecar_records,
                source_batch_id=stored_batch.id,
                observed_at=batch.records[0].source.observed_at if batch.records else finished_at,
                provider_key=request.provider_key,
            )
        else:
            request_status = "partial"

        uow.provider_attempts.mark_succeeded(
            stored_attempt.id,
            finished_at=finished_at,
            response_payload_sha256=batch.raw_payload_hash if batch is not None else "0" * 64,
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


def upsert_stock_daily_bars(
    session_factory: SessionProvider | sessionmaker[Any],
    *,
    provider_key: str = "tushare",
    dataset_key: str = "stock_daily_bars",
    request_key: str | None = None,
    unit_of_work_factory: UnitOfWorkFactory = SqlAlchemyUnitOfWork,
) -> UpsertSummary:
    """Upsert standardized stock daily bars into ``core.daily_bars``.

    The function locates the latest successful attempt for
    ``(provider_key, dataset_key, request_key)``, deserializes the
    sidecar, looks up the real ``core.instruments.id`` per
    ``(symbol, exchange)`` (the exchange is read from the sidecar, NOT
    inferred from the code prefix) and delegates to
    :meth:`SqlAlchemyDailyBarRepository.upsert_many`. The repository
    applies the ADR-0006 §3 revision rules: identical business
    content is a no-op, content change increments the revision.

    "Latest" is resolved client-side by the maximum ``finished_at``
    across the persisted ``succeeded`` attempts (with ``attempt_no``
    as a deterministic tiebreaker) — same selection rule as
    :func:`invest_pipeline.etf_daily_bars.upsert_etf_daily_bars` so a
    fresh Tushare run cannot be silently masked by an older baseline.
    Sidecar rows whose ``(symbol, exchange)`` does not match an active
    ``core.instruments`` row are silently dropped (with a count tracked
    via :attr:`UpsertSummary.skipped`) — the application service treats
    them as a stale fixture and lets the operator fix the upstream
    ingest.

    ``request_key`` is required because the daily-bars logical key is
    not derivable from a single date; callers that know the logical
    key pass it explicitly. ``provider_key`` defaults to ``"tushare"``
    (the only stock slice wired today) and ``dataset_key`` defaults
    to ``"stock_daily_bars"`` to match the dataset key the Tushare
    stock adapter stamps on the persisted request.
    """

    if not request_key:
        raise ValueError(
            "upsert_stock_daily_bars requires an explicit request_key; "
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
                "run stock_daily_bars_raw first"
            )
        attempts = uow.provider_attempts.list_by_request(stored_request.id, limit=1000)
        succeeded_attempts = [a for a in attempts if a.status == "succeeded"]
        if not succeeded_attempts:
            raise LookupError(
                f"no succeeded provider_attempts row for request "
                f"{stored_request.id}; stock_daily_bars_raw must have "
                "persisted a successful attempt first"
            )
        succeeded_attempt = max(
            succeeded_attempts,
            key=lambda a: (a.finished_at, a.attempt_no),
        )

        sidecar = deserialize_stock_daily_bars(succeeded_attempt.response_payload_json)
        if not sidecar:
            return UpsertSummary(inserted=0, skipped=0)

        new_bars = _build_new_bars(
            sidecar=sidecar,
            source_attempt_id=succeeded_attempt.id,
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
    source_attempt_id: UUID,
    instruments_lookup: Any,
) -> list[NewDailyBar | DailyBar]:
    """Map the sidecar records to ``NewDailyBar`` rows.

    The function walks the sidecar, looks up the real
    ``core.instruments.id`` via the partial unique business key
    ``(symbol, exchange) WHERE delist_date IS NULL`` and constructs a
    domain :class:`DailyBar` for every record whose instrument is
    known. The exchange comes from the sidecar ``exchange`` field —
    populated by the raw writer from the provider's
    ``symbol_and_exchange_for_instrument_id`` — and is never inferred
    from the symbol prefix. A sidecar row whose
    ``(symbol, exchange)`` does not match an active instrument row is
    silently dropped so the operator sees the empty result via
    :attr:`UpsertSummary.skipped` rather than a hard error.
    """

    new_bars: list[NewDailyBar | DailyBar] = []
    for entry in sidecar:
        symbol = entry["symbol"]
        exchange = entry["exchange"]
        if not isinstance(symbol, str) or not isinstance(exchange, str):
            raise ValueError(
                "stock daily-bars sidecar record must carry string "
                f"symbol/exchange; got {symbol!r}/{exchange!r}"
            )
        instrument = instruments_lookup(exchange=exchange, symbol=symbol)
        if instrument is None:
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


def _build_sidecar_record(
    bar: Any,
    provider_key: str,
    provider: _StockProviderPort,
) -> dict[str, Any]:
    """Build one sidecar record for a fetched ``DailyBar``.

    Resolves the bar's provider-native ``(symbol, exchange)`` via the
    provider's reverse lookup so the sidecar stores both fields and
    the downstream upsert can resolve the real ``core.instruments.id``
    without inferring the exchange from the symbol prefix. Raises
    :class:`LookupError` if the provider cannot resolve the bar's
    ``instrument_id``; a stale placeholder UUID indicates a leak
    between provider instances and the application service surfaces
    it as a hard error rather than silently coercing the audit field
    to the sidecar symbol.
    """

    resolved = provider.symbol_and_exchange_for_instrument_id(bar.instrument_id)
    if resolved is None:
        raise LookupError(
            f"{provider_key} could not resolve instrument_id "
            f"{bar.instrument_id!s} to a (symbol, exchange) pair for "
            f"trade_date {bar.trade_date.isoformat()}; the placeholder "
            "UUID was not generated by this provider instance — refusing "
            "to persist an audit-only value as the sidecar symbol"
        )
    symbol, exchange = resolved
    return {
        "symbol": symbol,
        "exchange": exchange,
        "trade_date": bar.trade_date.isoformat(),
        "open": format(bar.open, "f") if bar.open is not None else None,
        "high": format(bar.high, "f") if bar.high is not None else None,
        "low": format(bar.low, "f") if bar.low is not None else None,
        "close": format(bar.close, "f") if bar.close is not None else None,
        "prev_close": (format(bar.prev_close, "f") if bar.prev_close is not None else None),
        "volume": (format(bar.volume, "f") if bar.volume is not None else None),
        "amount": (format(bar.amount, "f") if bar.amount is not None else None),
        "trading_status": bar.trading_status.value,
    }


def _maybe_decimal(value: Any) -> Any:
    """Return ``Decimal(value)`` when ``value`` is a non-empty string, else ``None``."""

    from decimal import Decimal

    if value is None or value == "":
        return None
    return Decimal(value)


def serialize_stock_daily_bars(
    records: Sequence[dict[str, Any]],
    *,
    source_batch_id: Any,
    observed_at: datetime,
    provider_key: str = "tushare",
) -> str:
    """Build the JSONB sidecar that carries standardized stock daily bars.

    Mirrors :func:`invest_pipeline.adapters.fixture_dev.adapter.serialize_daily_bars`
    but stamps ``exchange`` on every record so the upsert path can
    resolve the real ``core.instruments.id`` via
    ``(symbol, exchange)`` without inferring the exchange from the code
    prefix. Kept private-shaped (leading underscore would conflict with
    the cross-module idempotency contract) and re-exported via
    :data:`__all__` so the test suite — and any future asset that wants
    to introspect a persisted attempt's payload — can round-trip the
    codec without having to import :mod:`invest_pipeline.etf_daily_bars`'s
    fixture-shaped serializer.
    """

    payload = {
        "schema_version": _STOCK_DAILY_BARS_SCHEMA_VERSION,
        "records": [
            {
                "symbol": record["symbol"],
                "exchange": record["exchange"],
                "trade_date": record["trade_date"],
                "open": record["open"],
                "high": record["high"],
                "low": record["low"],
                "close": record["close"],
                "prev_close": record["prev_close"],
                "volume": record["volume"],
                "amount": record["amount"],
                "trading_status": record["trading_status"],
                "source_provider": provider_key,
                "source_batch_id": str(source_batch_id),
                "observed_at": observed_at.isoformat(),
            }
            for record in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def deserialize_stock_daily_bars(
    payload_json: str | bytes | bytearray | None,
) -> list[dict[str, Any]]:
    """Inverse of :func:`serialize_stock_daily_bars`.

    The application service uses the returned dicts as a transport
    shape; it looks up the real ``core.instruments.id`` by
    ``(symbol, exchange)`` and constructs the final
    :class:`invest_domain.market_data.models.DailyBar` for the
    repository.
    """

    if payload_json is None:
        return []
    if isinstance(payload_json, (bytes, bytearray)):
        payload_json = payload_json.decode("utf-8")
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise ValueError(f"stock daily-bars payload must be a dict, got {type(payload).__name__}")
    if payload.get("schema_version") != _STOCK_DAILY_BARS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported stock daily-bars payload schema_version "
            f"{payload.get('schema_version')!r}; expected "
            f"{_STOCK_DAILY_BARS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            f"stock daily-bars payload 'records' must be a list, got {type(raw_records).__name__}"
        )
    return [dict(entry) for entry in raw_records]


__all__ = [
    "RawEtlResult",
    "UpsertSummary",
    "deserialize_stock_daily_bars",
    "serialize_stock_daily_bars",
    "upsert_stock_daily_bars",
    "write_stock_daily_bars_raw",
]  # type: ignore[no-redef]  # noqa: F811
