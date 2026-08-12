"""Deterministic ``fixture_dev`` provider for stock price-limit facts.

Stage 4C Phase 1 Task 1.2 ships a direct-call fixture: the provider
returns the PR-02 three-layer evidence model
(``ProviderRequest`` / ``ProviderAttempt`` /
``ProviderBatch[PriceLimitRecord] | None``) with a deterministic
payload hash for the regimes in
:data:`DEFAULT_PRICE_LIMIT_REGIMES` plus the ``risk_warning`` and
IPO unlimited-session branches :class:`PriceLimitPolicy`
distinguishes.

Intentionally not catalog-routed in this slice: the
:class:`ProviderCapability.STOCK_PRICE_LIMITS` enum member and the
:class:`Dataset.STOCK_PRICE_LIMITS` dataset key are frozen without
a matching provider declaration, so
:func:`invest_pipeline.provider_routing.select_providers` for the
``stock_price_limits`` dataset continues to raise
:class:`NoEligibleProviderError`. The provider is callable directly
(``FixtureDevStockPriceLimitsProvider()``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import uuid4

from invest_domain.market_data.models import (
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
)
from invest_domain.market_data.price_limits import (
    KnownPriceLimit,
    PriceLimitInput,
    PriceLimitPolicy,
    PriceLimitResult,
    UnknownPriceLimit,
    UnlimitedPriceLimit,
)

_FIXTURE_DATE = date(2026, 8, 11)
_DATASET_KEY = "stock_price_limits"
_SIMULATED_FAILURE_ERROR_CODE = "simulated_failure"


@dataclass(frozen=True, slots=True)
class PriceLimitRecord:
    """One published price-limit fact and the policy result behind it."""

    instrument_id: str
    trade_date: date
    prev_close: Decimal
    policy_result: PriceLimitResult

    @property
    def result(self) -> PriceLimitResult:
        """Alias that keeps the policy result convenient for callers."""

        return self.policy_result

    @property
    def limit_up_price(self) -> Decimal | None:
        if isinstance(self.policy_result, KnownPriceLimit):
            return self.policy_result.limit_up_price
        return None

    @property
    def limit_down_price(self) -> Decimal | None:
        if isinstance(self.policy_result, KnownPriceLimit):
            return self.policy_result.limit_down_price
        return None

    @property
    def rule_version(self) -> str | None:
        if isinstance(self.policy_result, (KnownPriceLimit, UnlimitedPriceLimit)):
            return self.policy_result.regime_id
        return None

    @property
    def source_refs(self) -> tuple[str, ...]:
        return self.policy_result.source_refs


_FIXTURE_INPUTS: tuple[PriceLimitInput, ...] = (
    PriceLimitInput(
        instrument_id="600000",
        market="SSE",
        board="main",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:600000",),
    ),
    PriceLimitInput(
        instrument_id="600001",
        market="SSE",
        board="main",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="risk_warning",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:600001",),
    ),
    PriceLimitInput(
        instrument_id="000001",
        market="SZSE",
        board="main",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:000001",),
    ),
    PriceLimitInput(
        instrument_id="300000",
        market="SZSE",
        board="gem",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:300000",),
    ),
    PriceLimitInput(
        instrument_id="300001",
        market="SZSE",
        board="gem",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="risk_warning",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:300001",),
    ),
    PriceLimitInput(
        instrument_id="688001",
        market="SSE",
        board="star",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=5,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:688001",),
    ),
    PriceLimitInput(
        instrument_id="688002",
        market="SSE",
        board="star",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=10,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:688002",),
    ),
    PriceLimitInput(
        instrument_id="830000",
        market="BSE",
        board="bse",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:830000",),
    ),
    PriceLimitInput(
        instrument_id="830001",
        market="BSE",
        board="bse",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="risk_warning",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:830001",),
    ),
    PriceLimitInput(
        instrument_id="830002",
        market="BSE",
        board="bse",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=1,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:830002",),
    ),
    PriceLimitInput(
        instrument_id="999999",
        market="SSE",
        board="unsupported",
        trade_date=_FIXTURE_DATE,
        listed_trade_session_no=100,
        listing_status="normal",
        reference_price=Decimal("10.00"),
        source_refs=("fixture_dev:price-limit:999999",),
    ),
)
_FIXTURE_BY_SYMBOL = {item.instrument_id: item for item in _FIXTURE_INPUTS}


def _now() -> datetime:
    return datetime.now(UTC)


def _result_payload(result: PriceLimitResult) -> dict[str, Any]:
    if isinstance(result, KnownPriceLimit):
        return {
            "kind": "known",
            "limit_up_price": str(result.limit_up_price),
            "limit_down_price": str(result.limit_down_price),
            "regime_id": result.regime_id,
            "reference_price": str(result.reference_price),
            "source_refs": list(result.source_refs),
        }
    if isinstance(result, UnlimitedPriceLimit):
        return {
            "kind": "unlimited",
            "regime_id": result.regime_id,
            "session_no": result.session_no,
            "source_refs": list(result.source_refs),
        }
    return {
        "kind": "unknown",
        "reason": result.reason,
        "required_fields": list(result.required_fields),
        "source_refs": list(result.source_refs),
    }


class FixtureDevStockPriceLimitsProvider:
    """Small, offline provider that publishes only policy-known facts."""

    def __init__(
        self,
        *,
        policy: PriceLimitPolicy | None = None,
        simulate_failure: bool = False,
    ) -> None:
        self._policy = policy or PriceLimitPolicy()
        self._simulate_failure = simulate_failure

    @property
    def provider_key(self) -> str:
        return "fixture_dev"

    @property
    def is_simulating_failure(self) -> bool:
        return self._simulate_failure

    def simulate_failure(self) -> None:
        self._simulate_failure = True

    def reset(self) -> None:
        self._simulate_failure = False

    def fetch_price_limits(
        self,
        symbols: Sequence[str],
        trade_date: date,
    ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[PriceLimitRecord] | None]:
        try:
            ordered_symbols = tuple(symbols)
        except TypeError:
            ordered_symbols = ()

        # Validate inputs up-front so the request_key / params JSON
        # serialisation can never blow up on a non-string symbol or
        # an unsupported date. The provider returns a failed attempt
        # in those cases — see :class:`FailClosedContractTest`.
        invalid_symbols = (
            not ordered_symbols
            or len(set(ordered_symbols)) != len(ordered_symbols)
            or any(
                not isinstance(symbol, str)
                or not symbol.strip()
                or symbol not in _FIXTURE_BY_SYMBOL
                for symbol in ordered_symbols
            )
        )
        invalid_date = not isinstance(trade_date, date) or trade_date != _FIXTURE_DATE

        started_at = _now()
        request = ProviderRequest(
            provider_key=self.provider_key,
            dataset_key=_DATASET_KEY,
            request_key=self._request_key(ordered_symbols, trade_date),
            params={
                "symbols": list(ordered_symbols),
                "trade_date": trade_date.isoformat() if isinstance(trade_date, date) else None,
            },
            created_at=started_at,
        )
        attempt_id = uuid4()

        if self._simulate_failure:
            return self._failed(
                request,
                started_at,
                ProviderFailureStage.PROVIDER,
                _SIMULATED_FAILURE_ERROR_CODE,
                "fixture_dev forced failure",
            )
        if invalid_date:
            return self._failed(
                request,
                started_at,
                ProviderFailureStage.CONTRACT,
                "unsupported_trade_date",
                "fixture has no facts for this trade date",
            )
        if invalid_symbols:
            return self._failed(
                request,
                started_at,
                ProviderFailureStage.CONTRACT,
                "unknown_symbol",
                "fixture input contains an empty, duplicate, or unknown symbol",
            )

        records: list[PriceLimitRecord] = []
        payload: list[dict[str, Any]] = []
        for symbol in ordered_symbols:
            facts = _FIXTURE_BY_SYMBOL[symbol]
            result = self._policy.evaluate(facts)
            if isinstance(result, UnknownPriceLimit):
                return self._failed(
                    request,
                    started_at,
                    ProviderFailureStage.CONTRACT,
                    "policy_unknown",
                    f"price-limit policy returned unknown for {symbol}",
                )
            records.append(
                PriceLimitRecord(
                    instrument_id=symbol,
                    trade_date=trade_date,
                    prev_close=facts.reference_price,
                    policy_result=result,
                )
            )
            payload.append({"input": facts.instrument_id, "result": _result_payload(result)})

        finished_at = _now()
        attempt = ProviderAttempt(
            request_id=uuid4(),
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=_duration_ms(started_at, finished_at),
        )
        batch = ProviderBatch(
            attempt_id=attempt_id,
            records=tuple(records),
            raw_payload_hash=sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            warnings=(),
            status=ProviderBatchStatus.SUCCEEDED,
        )
        return request, attempt, batch

    @staticmethod
    def _request_key(symbols: Sequence[str], trade_date: object) -> str:
        date_key = trade_date.isoformat() if isinstance(trade_date, date) else "invalid"
        # Coerce non-string symbols to ``repr`` so a malformed input
        # cannot blow up the ``str.join`` step — the validation that
        # rejects non-string / blank symbols runs after the request
        # key is built, so the key has to be defensible on its own.
        safe_symbols = (symbol if isinstance(symbol, str) else repr(symbol) for symbol in symbols)
        return f"price-limits-{date_key}-{'-'.join(safe_symbols)}"

    @staticmethod
    def _failed(
        request: ProviderRequest,
        started_at: datetime,
        stage: ProviderFailureStage,
        code: str,
        message: str,
    ) -> tuple[ProviderRequest, ProviderAttempt, None]:
        finished_at = _now()
        return (
            request,
            ProviderAttempt(
                request_id=uuid4(),
                attempt_number=1,
                status=ProviderAttemptStatus.FAILED,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=_duration_ms(started_at, finished_at),
                error_stage=stage,
                error_code=code,
                error_message=message,
            ),
            None,
        )


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(int((finished_at - started_at).total_seconds() * 1000), 0)


FixtureDevPriceLimitsProvider = FixtureDevStockPriceLimitsProvider

__all__ = [
    "FixtureDevPriceLimitsProvider",
    "FixtureDevStockPriceLimitsProvider",
    "PriceLimitRecord",
]
