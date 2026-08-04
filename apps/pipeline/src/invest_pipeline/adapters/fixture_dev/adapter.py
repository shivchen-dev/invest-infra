"""fixture_dev ETF instrument adapter (PR-05).

The adapter returns the three-layer PR-02 evidence model:
``(ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None)``.
The deterministic fixture is loaded from
``etf_instruments.json`` so tests and local dev always see the same
16-ETF SSE / SZSE universe (ADR-0004 phase 1 market scope).

PR-06 extends the adapter with :meth:`FixtureDevInstrumentProvider.
fetch_daily_bars` (the previous placeholder returned an empty batch).
The on-disk daily-bars fixture
``etf_daily_bars.json`` carries 6 trading days of OHLCV per ETF
(2026-07-23 to 2026-07-30) so the full
``fixture_dev -> raw.* -> core.daily_bars`` pipeline can be exercised
end-to-end with deterministic content. Records are converted to
domain :class:`invest_domain.market_data.models.DailyBar` instances
with ``revision=1``; the storage layer bumps the revision if the
business content has actually changed (ADR-0006 §3).

Callers that need to exercise the failure path (contract tests for
``raw.provider_attempts`` CHECK constraints, retry policies, etc.) can
either pass ``simulate_failure=True`` to the constructor or call
:meth:`simulate_failure` after construction to force the next
``fetch_instruments`` call into the failed-attempt branch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.instruments.models import InstrumentId, _validate_optional_exchange
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)
from invest_domain.market_data.values import Adjust, TradingStatus
from invest_domain.shared.values import Currency

_FIXTURE_PATH = Path(__file__).resolve().parent / "etf_instruments.json"
_DAILY_BARS_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "etf_daily_bars.json"
)
_RECORDS_SCHEMA_VERSION = 1
_DAILY_BARS_SCHEMA_VERSION = 1
_SIMULATED_FAILURE_ERROR_CODE = "simulated_failure"
_SIMULATED_FAILURE_ERROR_MESSAGE = (
    "fixture_dev forced failure for contract tests "
    "(set simulate_failure=False or call reset() to resume normal mode)"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _load_fixture_records() -> list[dict[str, Any]]:
    """Load and validate the on-disk ETF fixture.

    The JSON is the canonical source of truth for the fixture; this
    helper raises :class:`ValueError` if a required field is missing so
    the adapter never silently returns an incomplete set.
    """

    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(
            f"fixture_dev etf_instruments.json must be a list, got {type(payload).__name__}"
        )
    required = {"symbol", "name", "exchange", "instrument_type", "status"}
    cleaned: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(
                f"fixture_dev etf_instruments.json[{index}] must be a dict, "
                f"got {type(entry).__name__}"
            )
        missing = required - set(entry)
        if missing:
            raise ValueError(
                f"fixture_dev etf_instruments.json[{index}] is missing fields: {sorted(missing)}"
            )
        cleaned.append(dict(entry))
    return cleaned


def _record_to_instrument(record: dict[str, Any]) -> Instrument:
    """Build a domain :class:`Instrument` from a JSON fixture row."""

    _validate_optional_exchange(record["exchange"])
    list_date_raw = record.get("list_date")
    delist_date_raw = record.get("delist_date")
    return Instrument(
        symbol=record["symbol"],
        name=record["name"],
        exchange=record["exchange"],
        instrument_type=InstrumentType(record["instrument_type"]),
        currency=Currency(record.get("currency", Currency.CNY.value)),
        list_date=date.fromisoformat(list_date_raw) if list_date_raw else None,
        delist_date=date.fromisoformat(delist_date_raw) if delist_date_raw else None,
        status=InstrumentStatus(record["status"]),
        underlying_index=record.get("underlying_index"),
        category=record.get("category"),
        provider_symbol_map={"fixture_dev": record["symbol"]},
    )


def _serialize_records(records: Sequence[Instrument]) -> str:
    """Build the JSONB sidecar that carries standardized records through raw.*.

    The payload is stored on ``raw.provider_attempts.response_payload_json``
    so the downstream ``etf_instruments`` asset can deserialize the
    records back into domain :class:`Instrument` instances without
    re-calling the Provider. The schema version is part of the payload
    so future format changes can be detected.
    """

    payload = {
        "schema_version": _RECORDS_SCHEMA_VERSION,
        "records": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "exchange": item.exchange,
                "instrument_type": item.instrument_type.value,
                "currency": item.currency.value,
                "list_date": item.list_date.isoformat() if item.list_date else None,
                "delist_date": (
                    item.delist_date.isoformat() if item.delist_date else None
                ),
                "status": item.status.value,
                "underlying_index": item.underlying_index,
                "category": item.category,
            }
            for item in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def deserialize_records(payload_json: str | bytes | bytearray | None) -> list[Instrument]:
    """Inverse of :func:`_serialize_records`; used by the core-instruments asset."""

    if payload_json is None:
        return []
    if isinstance(payload_json, (bytes, bytearray)):
        payload_json = payload_json.decode("utf-8")
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        raise ValueError(
            f"records payload must be a dict, got {type(payload).__name__}"
        )
    if payload.get("schema_version") != _RECORDS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported records payload schema_version "
            f"{payload.get('schema_version')!r}; expected {_RECORDS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            f"records payload 'records' must be a list, got {type(raw_records).__name__}"
        )
    return [_record_to_instrument(entry) for entry in raw_records]


def _load_daily_bars_records() -> list[dict[str, Any]]:
    """Load and validate the on-disk daily-bars fixture.

    Mirrors :func:`_load_fixture_records`: the JSON is the canonical
    source of truth, the helper raises :class:`ValueError` on missing
    fields so the adapter never silently returns malformed data. The
    fixture is a flat list of ``symbol / trade_date / OHLCV`` rows; the
    adapter filters by ``symbols`` and ``[start_date, end_date]`` per
    request.
    """

    if not _DAILY_BARS_FIXTURE_PATH.exists():
        raise FileNotFoundError(
            f"fixture_dev etf_daily_bars.json not found at "
            f"{_DAILY_BARS_FIXTURE_PATH}"
        )
    payload = json.loads(_DAILY_BARS_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(
            f"fixture_dev etf_daily_bars.json must be a list, got {type(payload).__name__}"
        )
    required = {
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "prev_close",
        "volume",
        "amount",
        "trading_status",
    }
    cleaned: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise ValueError(
                f"fixture_dev etf_daily_bars.json[{index}] must be a dict, "
                f"got {type(entry).__name__}"
            )
        missing = required - set(entry)
        if missing:
            raise ValueError(
                f"fixture_dev etf_daily_bars.json[{index}] is missing fields: "
                f"{sorted(missing)}"
            )
        cleaned.append(dict(entry))
    return cleaned


def _daily_bars_record_to_raw(
    record: dict[str, Any],
    *,
    source_batch_id: Any,
    observed_at: datetime,
    provider_key: str = "fixture_dev",
) -> dict[str, Any]:
    """Build the raw dict shape the ``core.daily_bars`` sidecar persists.

    The sidecar carries the original ``symbol`` (not the placeholder
    ``instrument_id``) so the application service can re-resolve the
    real ``core.instruments.id`` via ``(symbol, exchange)`` at upsert
    time. ``provider_key`` stamps the ``source_provider`` audit field
    so the sidecar reflects the real provider
    (``"fixture_dev"`` / ``"cifangquant"``) instead of always
    defaulting to the fixture identifier.
    """

    return {
        "symbol": record["symbol"],
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


def serialize_daily_bars(
    records: Sequence[dict[str, Any]],
    *,
    source_batch_id: Any,
    observed_at: datetime,
    provider_key: str = "fixture_dev",
) -> str:
    """Build the JSONB sidecar that carries standardized bars through ``raw.*``.

    Mirrors :func:`_serialize_records` for the daily-bar payload. The
    ``records`` argument is the filtered subset of the JSON fixture
    (each entry is a ``symbol / trade_date / OHLCV`` dict); the
    ``source_batch_id`` and ``observed_at`` are stamped by the
    adapter. The application service reads the sidecar, looks up the
    real ``core.instruments.id`` per ``symbol`` and constructs the
    final :class:`invest_domain.market_data.models.DailyBar` for the
    repository.

    ``provider_key`` is the audit field the sidecar's
    ``source_provider`` records against ``core.daily_bars``. The
    default keeps existing callers (fixture_dev-only smoke paths)
    source-compatible; the application service passes
    ``request.provider_key`` so real CifangQuant runs store
    ``"cifangquant"`` instead of leaking the fixture identifier into
    the audit column.
    """

    payload = {
        "schema_version": _DAILY_BARS_SCHEMA_VERSION,
        "records": [
            _daily_bars_record_to_raw(
                record,
                source_batch_id=source_batch_id,
                observed_at=observed_at,
                provider_key=provider_key,
            )
            for record in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def deserialize_daily_bars(
    payload_json: str | bytes | bytearray | None,
) -> list[dict[str, Any]]:
    """Inverse of :func:`serialize_daily_bars`; used by the core-daily-bars asset.

    The application service uses the returned dicts as a transport
    shape: it looks up the real ``core.instruments.id`` by
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
        raise ValueError(
            f"daily-bars payload must be a dict, got {type(payload).__name__}"
        )
    if payload.get("schema_version") != _DAILY_BARS_SCHEMA_VERSION:
        raise ValueError(
            "unsupported daily-bars payload schema_version "
            f"{payload.get('schema_version')!r}; expected {_DAILY_BARS_SCHEMA_VERSION}"
        )
    raw_records = payload.get("records", [])
    if not isinstance(raw_records, list):
        raise ValueError(
            f"daily-bars payload 'records' must be a list, got {type(raw_records).__name__}"
        )
    return [dict(entry) for entry in raw_records]


class FixtureDevInstrumentProvider:
    """Deterministic fixture of A-share ETFs used by tests and local dev.

    Returns the PR-02 three-layer evidence model from
    :meth:`fetch_instruments` and :meth:`fetch_daily_bars`. The
    :meth:`list_instruments` convenience accessor is kept for the
    legacy single-layer Protocol surface.

    Use :meth:`simulate_failure` (or pass ``simulate_failure=True`` to
    the constructor) to force the next ``fetch_instruments`` call into
    the failed-attempt branch — a failed attempt carries the mandatory
    ``error_stage`` / ``error_code`` and produces no
    :class:`ProviderBatch`, exactly mirroring the contract enforced by
    the ``raw.provider_attempts`` CHECK constraints.
    """

    def __init__(self, *, simulate_failure: bool = False) -> None:
        self._simulate_failure = simulate_failure
        self._fixture_records = _load_fixture_records()
        self._instruments: tuple[Instrument, ...] = tuple(
            _record_to_instrument(record) for record in self._fixture_records
        )
        self._daily_bars_records: tuple[dict[str, Any], ...] = tuple(
            _load_daily_bars_records()
        )
        # Stable placeholder UUID per symbol so the adapter can
        # build a domain :class:`DailyBar` without knowing the real
        # ``core.instruments.id``. The application service re-maps
        # ``symbol -> core.instruments.id`` before persisting.
        self._placeholder_instrument_ids: dict[str, InstrumentId] = {
            record["symbol"]: InstrumentId.generate()
            for record in self._daily_bars_records
        }

    @property
    def provider_key(self) -> str:
        return "fixture_dev"

    def list_instruments(self) -> Sequence[Instrument]:
        return self._instruments

    def list_daily_bars_records(self) -> Sequence[dict[str, Any]]:
        """Return the parsed daily-bars fixture rows (test-only helper)."""

        return self._daily_bars_records

    def placeholder_instrument_id(self, symbol: str) -> InstrumentId | None:
        """Return the stable placeholder UUID the adapter assigned to ``symbol``."""

        return self._placeholder_instrument_ids.get(symbol)

    def symbol_for_instrument_id(self, instrument_id: InstrumentId) -> str | None:
        """Return the symbol whose placeholder UUID matches ``instrument_id``.

        Reverse lookup against :attr:`_placeholder_instrument_ids`. The
        application service calls this for every ``DailyBar`` carried
        on a :class:`ProviderBatch` so the sidecar stores the
        provider-native symbol (e.g. ``"510300"``) rather than the
        audit-only ``BarSource.provider_key``. Returns ``None`` if the
        UUID was not generated by this provider instance — that
        indicates a placeholder leak between provider instances and
        the application service surfaces it as a hard error.
        """

        for symbol, placeholder_id in self._placeholder_instrument_ids.items():
            if placeholder_id == instrument_id:
                return symbol
        return None

    def simulate_failure(self) -> None:
        """Force the next :meth:`fetch_instruments` call into the failure branch."""

        self._simulate_failure = True

    def reset(self) -> None:
        """Clear any prior :meth:`simulate_failure` request."""

        self._simulate_failure = False

    @property
    def is_simulating_failure(self) -> bool:
        return self._simulate_failure

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        """Return the PR-02 three-layer evidence bundle for ETF master data.

        On the normal (non-failure) path the adapter returns a
        ``succeeded`` :class:`ProviderAttempt` and a
        :class:`ProviderBatch` whose ``raw_payload_hash`` is the SHA-256
        of the JSON fixture file (the closest analogue to a real
        Provider response) and whose ``records`` carry the standardized
        :class:`Instrument` instances.

        On the failure path the adapter returns a
        ``failed`` :class:`ProviderAttempt` with the mandatory
        ``error_stage`` / ``error_code`` / ``error_message`` populated
        and ``ProviderBatch=None`` — a failed attempt must not produce a
        batch row, per the domain model and the
        ``ck_provider_attempts_failed_has_error`` constraint.
        """

        if self._simulate_failure:
            return self._build_failure_bundle(as_of)
        return self._build_success_bundle(as_of)

    def _build_success_bundle(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument]]:
        instruments = list(self._instruments)
        started = _now()
        finished = _now()
        raw_payload_hash = sha256(_FIXTURE_PATH.read_bytes()).hexdigest()

        request_id = uuid4()
        attempt_id = uuid4()

        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key="etf_instruments",
            request_key=f"instruments-{as_of.isoformat()}",
            params={"as_of": as_of.isoformat()},
            created_at=started,
        )
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started,
            finished_at=finished,
            duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
        )
        batch = ProviderBatch(
            attempt_id=attempt_id,
            records=tuple(instruments),
            raw_payload_hash=raw_payload_hash,
            warnings=(),
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def _build_failure_bundle(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, None]:
        started = _now()
        finished = _now()
        request_id = uuid4()

        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key="etf_instruments",
            request_key=f"instruments-{as_of.isoformat()}",
            params={"as_of": as_of.isoformat()},
            created_at=started,
        )
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.FAILED,
            started_at=started,
            finished_at=finished,
            duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
            error_stage=ProviderFailureStage.PROVIDER,
            error_code=_SIMULATED_FAILURE_ERROR_CODE,
            error_message=_SIMULATED_FAILURE_ERROR_MESSAGE,
        )
        return request, attempt, None

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
        """Return the PR-02 three-layer evidence bundle for daily bars.

        Filters the on-disk ``etf_daily_bars.json`` by ``symbols`` and
        ``[start_date, end_date]`` and constructs domain
        :class:`invest_domain.market_data.models.DailyBar` instances
        with ``revision=1``. The ``BarSource.source_batch_id`` is the
        batch's ``attempt_id`` so the lineage
        ``raw.provider_attempts -> core.daily_bars`` is enforced by the
        FK. The application service re-maps
        ``symbol -> core.instruments.id`` at upsert time; the
        ``InstrumentId`` carried on the returned bars is a stable
        placeholder UUID (see :attr:`placeholder_instrument_id`).

        On :meth:`simulate_failure` the adapter returns a failed
        attempt with no batch — the application service skips the
        ``core.daily_bars`` upsert in that case (a failed attempt
        leaves no batch behind per the domain model and
        ``ck_provider_attempts_failed_has_error``).
        """

        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )

        started = _now()
        finished = _now()
        request_id = uuid4()
        attempt_id = uuid4()

        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key="etf_daily_bars",
            request_key=(
                f"daily-bars-{start_date.isoformat()}-{end_date.isoformat()}-"
                f"{'-'.join(symbols)}"
            ),
            params={
                "symbols": list(symbols),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            created_at=started,
        )

        if self._simulate_failure:
            attempt = ProviderAttempt(
                request_id=request_id,
                attempt_number=1,
                status=ProviderAttemptStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
                error_stage=ProviderFailureStage.PROVIDER,
                error_code=_SIMULATED_FAILURE_ERROR_CODE,
                error_message=_SIMULATED_FAILURE_ERROR_MESSAGE,
            )
            return request, attempt, None

        bars, matched_records = self._build_daily_bars(
            symbols,
            start_date,
            end_date,
            source_batch_id=attempt_id,
            observed_at=finished,
        )
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started,
            finished_at=finished,
            duration_ms=max(int((finished - started).total_seconds() * 1000), 0),
        )
        batch = ProviderBatch(
            attempt_id=attempt_id,
            records=tuple(bars),
            raw_payload_hash=self._daily_bars_raw_hash(matched_records),
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    def _build_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
        *,
        source_batch_id: Any,
        observed_at: datetime,
    ) -> tuple[list[DailyBar], list[dict[str, Any]]]:
        symbol_set = {item for item in symbols}
        bars: list[DailyBar] = []
        matched: list[dict[str, Any]] = []
        for record in self._daily_bars_records:
            if record["symbol"] not in symbol_set:
                continue
            trade_date = date.fromisoformat(record["trade_date"])
            if trade_date < start_date or trade_date > end_date:
                continue
            instrument_id = self._placeholder_instrument_ids[record["symbol"]]
            source = BarSource(
                provider_key=self.provider_key,
                source_batch_id=source_batch_id,
                observed_at=observed_at,
            )
            bar = DailyBar.build(
                instrument_id=instrument_id,
                trade_date=trade_date,
                open=Decimal(record["open"]),
                high=Decimal(record["high"]),
                low=Decimal(record["low"]),
                close=Decimal(record["close"]),
                prev_close=Decimal(record["prev_close"]),
                volume=Decimal(record["volume"]),
                amount=Decimal(record["amount"]),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus(record["trading_status"]),
                source=source,
                revision=1,
            )
            bars.append(bar)
            matched.append(record)
        return bars, matched

    def _daily_bars_raw_hash(self, records: Sequence[dict[str, Any]]) -> str:
        """Return a deterministic SHA-256 of the matched batch payload.

        Mirrors the instruments path (the SHA-256 of the JSON fixture
        file) but scoped to the matched ``(symbol, trade_date)`` rows
        so ``raw.provider_batches.payload_sha256`` is
        request-scoped rather than file-scoped.
        """

        payload = json.dumps(
            [
                {
                    "symbol": record["symbol"],
                    "trade_date": record["trade_date"],
                }
                for record in records
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "FixtureDevInstrumentProvider",
    "deserialize_daily_bars",
    "deserialize_records",
    "serialize_daily_bars",
]
