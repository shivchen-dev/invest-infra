from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Protocol

from invest_domain.instruments import Instrument, InstrumentType
from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    PROVIDER_KEY_FIXTURE_DEV,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)

FIXTURE_DEV_PROVIDER_KEY = PROVIDER_KEY_FIXTURE_DEV


class ProviderBatch(Protocol):
    """Local Provider batch shape mirroring ADR-0003 §3.

    The full ``DailyBar`` value object belongs in ``packages/domain`` per
    ADR-0003 §3 + Phase 1-B. Until that lands, this Protocol expresses the
    adapter batch contract in plain primitives so adapters can be exercised
    without depending on a not-yet-implemented domain object.
    """

    provider_key: str
    requested_at: datetime
    received_at: datetime
    raw_payload_hash: str
    warnings: tuple[str, ...]

    def records(self) -> Sequence[object]: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FixtureDevInstrumentProvider:
    """Deterministic fixture of A-share ETFs used by tests and local dev.

    The dataset is intentionally tiny and only contains SSE / SZSE ETFs to
    match ADR-0004's market scope. None of these identifiers represent a
    recommendation; they are stable references used by `assets.py` smoke
    flows and pipeline acceptance tests.
    """

    provider_key = FIXTURE_DEV_PROVIDER_KEY

    def list_instruments(self) -> list[Instrument]:
        return [
            Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF),
            Instrument("510500", "中证500ETF", "SSE", InstrumentType.ETF),
            Instrument("159915", "创业板ETF", "SZSE", InstrumentType.ETF),
        ]


class _FixtureBatch:
    """Simple in-memory ProviderBatch carrying primitive records.

    Keeps the adapter contract visible without requiring the full
    ``DailyBar`` value object that ADR-0006 will land in Phase 1-B.
    """

    __slots__ = (
        "provider_key",
        "requested_at",
        "received_at",
        "raw_payload_hash",
        "warnings",
        "_records",
        "request_id",
    )

    def __init__(
        self,
        *,
        provider_key: str,
        records: Sequence[object],
        warnings: Sequence[str] = (),
        request_id: str | None = None,
    ) -> None:
        self.provider_key = provider_key
        self._records = tuple(records)
        self.request_id = request_id
        self.requested_at = _utcnow()
        self.received_at = _utcnow()
        self.raw_payload_hash = _payload_hash([record for record in self._records])
        self.warnings = tuple(warnings)

    def records(self) -> Sequence[object]:
        return self._records


class FixtureDevEtfMarketDataProvider:
    """Dev/test ETF market-data Provider.

    All methods return a deterministic empty batch with proper envelope
    metadata so application services can be exercised without hitting any
    external API. The fixture never claims to model market prices.
    """

    provider_key = FIXTURE_DEV_PROVIDER_KEY
    adjustment = ADJUSTMENT_NONE
    declaration = ProviderDeclaration(
        provider_key=FIXTURE_DEV_PROVIDER_KEY,
        capabilities=frozenset(
            {
                ProviderCapability.ETF_INSTRUMENTS,
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_TRADING_CALENDAR,
            }
        ),
        role=ProviderRole.PRIMARY,
        requires_credentials=False,
        notes=(
            "fixture_dev is dev/test only; explicitly NOT for production per "
            "M0-CODING-BRIEF Phase 1-D and ADR-0003 §8."
        ),
        adjustment=ADJUSTMENT_NONE,
        risk_warnings=("dev/test only",),
    )

    def fetch_instruments(self, as_of: date) -> _FixtureBatch:
        del as_of  # fixture is static; reserved for future schema versioning
        provider = FixtureDevInstrumentProvider()
        records = list(provider.list_instruments())
        return _FixtureBatch(
            provider_key=self.provider_key,
            records=records,
            warnings=(
                "fixture_dev is for dev/test only; production must use a real Provider.",
            ),
        )

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> _FixtureBatch:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        return _FixtureBatch(
            provider_key=self.provider_key,
            records=[],
            warnings=(
                f"fixture_dev returned zero daily bars for {len(tuple(symbols))} symbols "
                f"between {start_date.isoformat()} and {end_date.isoformat()}",
            ),
        )

    def fetch_trading_calendar(
        self,
        start_date: date,
        end_date: date,
    ) -> _FixtureBatch:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        return _FixtureBatch(
            provider_key=self.provider_key,
            records=[],
            warnings=(
                "fixture_dev returns an empty trading calendar; production must use a versioned calendar.",
            ),
        )
