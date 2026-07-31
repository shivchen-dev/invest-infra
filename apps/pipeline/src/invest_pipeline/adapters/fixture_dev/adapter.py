from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import TypeVar

from invest_domain.instruments import Instrument, InstrumentType
from invest_domain.market_data.models import ProviderBatch, ProviderBatchStatus

T = TypeVar("T")


class FixtureDevInstrumentProvider:
    """Deterministic fixture of A-share ETFs used by tests and local dev.

    Returns a tiny SSE / SZSE ETF set per ADR-0004 market scope. This is the
    sole adapter exposed under ``invest_pipeline.adapters`` for PR-1 and is
    intentionally minimal: just an instrument provider with no batch classes.
    """

    @property
    def provider_key(self) -> str:
        return "fixture_dev"

    def list_instruments(self) -> Sequence[Instrument]:
        return [
            Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF),
            Instrument("510500", "中证500ETF", "SSE", InstrumentType.ETF),
            Instrument("159915", "创业板ETF", "SZSE", InstrumentType.ETF),
        ]

    def fetch_instruments(self, as_of: date) -> ProviderBatch[Instrument]:
        """Fetch instruments as a ProviderBatch[Instrument].

        This method implements the EtfMarketDataProvider protocol from
        ``invest_domain.market_data.ports``. The fixture provider returns
        a deterministic batch with a fixed request/response timestamp.
        """
        instruments = self.list_instruments()
        now = datetime.now(timezone.utc)
        payload = repr([i.symbol for i in instruments]).encode("utf-8")
        return ProviderBatch(
            provider_key=self.provider_key,
            dataset_key="instruments",
            requested_at=now,
            received_at=now,
            records=instruments,
            raw_payload_hash=sha256(payload).hexdigest(),
            status=ProviderBatchStatus.SUCCEEDED,
        )
