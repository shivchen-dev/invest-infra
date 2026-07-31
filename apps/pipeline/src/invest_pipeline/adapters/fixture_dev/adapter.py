"""fixture_dev ETF instrument adapter (PR-05).

The adapter returns the three-layer PR-02 evidence model:
``(ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None)``.
The deterministic fixture is loaded from
``etf_instruments.json`` so tests and local dev always see the same
12-ETF SSE / SZSE universe (ADR-0004 phase 1 market scope).

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
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from invest_domain.instruments import (
    Instrument,
    InstrumentStatus,
    InstrumentType,
)
from invest_domain.instruments.models import _validate_optional_exchange
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)
from invest_domain.shared.values import Currency

_FIXTURE_PATH = Path(__file__).resolve().parent / "etf_instruments.json"
_RECORDS_SCHEMA_VERSION = 1
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

    @property
    def provider_key(self) -> str:
        return "fixture_dev"

    def list_instruments(self) -> Sequence[Instrument]:
        return self._instruments

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
            dataset_key="instruments",
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
            dataset_key="instruments",
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
        """Return an empty PR-02 three-layer bundle for daily bars.

        The fixture has no canned daily-bar fixture yet; it always
        reports a successful empty batch so callers can exercise the
        full request / attempt / batch persistence path.
        """

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
            records=(),
            raw_payload_hash=sha256(b"[]").hexdigest(),
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch


__all__ = [
    "FixtureDevInstrumentProvider",
    "deserialize_records",
]
