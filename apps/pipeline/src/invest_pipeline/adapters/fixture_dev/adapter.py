from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import TypeVar
from uuid import uuid4

from invest_domain.instruments import Instrument, InstrumentType
from invest_domain.market_data.models import (
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderRequest,
)

T = TypeVar("T")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FixtureDevInstrumentProvider:
    """Deterministic fixture of A-share ETFs used by tests and local dev.

    Returns a tiny SSE / SZSE ETF set per ADR-0004 market scope. The
    adapter exposes :meth:`list_instruments` for the simple Protocol
    surface and :meth:`fetch_instruments` for the three-layer PR-02
    evidence model.
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

    def fetch_instruments(
        self, as_of: date
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
        """Fetch instruments as the PR-02 three-layer evidence bundle.

        The fixture always succeeds: it builds a deterministic
        :class:`ProviderRequest`, a :class:`ProviderAttempt` in the
        ``succeeded`` state, and a :class:`ProviderBatch` carrying the
        resolved instruments. ``request_id`` and ``attempt_id`` use
        placeholder UUIDs - the application service replaces them with
        the storage-assigned UUIDs when it persists the three rows in
        order.
        """
        instruments = self.list_instruments()
        started = _now()
        finished = _now()
        payload = repr([i.symbol for i in instruments]).encode("utf-8")
        raw_payload_hash = sha256(payload).hexdigest()

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
            records=instruments,
            raw_payload_hash=raw_payload_hash,
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

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