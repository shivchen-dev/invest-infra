from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from invest_pipeline.providers.akshare.config import AkshareAdapterConfig
from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    PROVIDER_KEY_AKSHARE,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)
from invest_pipeline.providers.errors import (
    ProviderAdapterNotImplementedError,
    ProviderAuthenticationError,
)


class _InstrumentLike(Protocol):
    symbol: str
    exchange: str


AKSHARE_DECLARATION = ProviderDeclaration(
    provider_key=PROVIDER_KEY_AKSHARE,
    capabilities=frozenset(
        {
            ProviderCapability.ETF_INSTRUMENTS,
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_TRADING_CALENDAR,
            ProviderCapability.INDEX_QUOTES,
            ProviderCapability.STOCK_QUOTES,
        }
    ),
    role=ProviderRole.SECONDARY,
    requires_credentials=True,
    notes=(
        "AkShare is an aggregation library. ARC-confirmed it covered ETF main data, "
        "historical quotes and trading calendar in archive scripts, but rate-limit / "
        "blocking events were observed. Selection is not frozen in ADR-0003; cannot be "
        "treated as production SLA."
    ),
    adjustment=ADJUSTMENT_NONE,
    risk_warnings=(
        "rate-limit and blocking events observed in archive",
        "upstream SLA not proven",
        "must not be marked as production SLA source per M0 / O-1",
    ),
    env_prefix="INVEST_PIPELINE_AKSHARE_",
    credential_env_vars=("INVEST_PIPELINE_AKSHARE_TOKEN",),
)


class AkshareEtfMarketDataProvider:
    """AkShare ETF market-data Provider (placeholder).

    Every fetch method raises ``ProviderAdapterNotImplementedError`` so the
    contract is visible without fabricating behavior. Real HTTP / SDK calls
    remain blocked until O-1 resolves and a new ADR lifts M0.
    """

    provider_key = PROVIDER_KEY_AKSHARE
    adjustment = ADJUSTMENT_NONE
    declaration = AKSHARE_DECLARATION

    def __init__(self, *, token: str, base_url: str, timeout_seconds: float) -> None:
        self._config = AkshareAdapterConfig(
            token=token,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        if not self._config.token:
            raise ProviderAuthenticationError(
                self.provider_key,
                "AkShare requires a token; INVEST_PIPELINE_AKSHARE_TOKEN must be set "
                "via the deployment Secret, never via the repository.",
            )

    @property
    def config(self) -> AkshareAdapterConfig:
        return self._config

    def _placeholder(self, capability: ProviderCapability) -> None:
        raise ProviderAdapterNotImplementedError(
            self.provider_key,
            (
                f"AkShare adapter is a placeholder for {capability.value!r}. "
                "Real HTTP / SDK calls are blocked until O-1 (Provider selection) is "
                "confirmed per ADR-0003. Rate-limit / blocking risks are recorded in "
                "the DATA-SOURCE-MIGRATION-MATRIX."
            ),
        )

    def fetch_instruments(self, as_of: date) -> None:
        del as_of
        self._placeholder(ProviderCapability.ETF_INSTRUMENTS)

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> None:
        del symbols, start_date, end_date
        self._placeholder(ProviderCapability.ETF_DAILY_BARS)

    def fetch_trading_calendar(
        self,
        start_date: date,
        end_date: date,
    ) -> None:
        del start_date, end_date
        self._placeholder(ProviderCapability.ETF_TRADING_CALENDAR)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"AkshareEtfMarketDataProvider(provider_key={self.provider_key!r})"
