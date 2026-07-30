from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    PROVIDER_KEY_CIFANG,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    is_adjustment_allowed,
)
from invest_pipeline.providers.cifang.config import CifangAdapterConfig
from invest_pipeline.providers.errors import (
    ProviderAdapterNotImplementedError,
    ProviderAuthenticationError,
)
from invest_pipeline.providers.fixture_dev import _FixtureBatch


CIFANG_DECLARATION = ProviderDeclaration(
    provider_key=PROVIDER_KEY_CIFANG,
    capabilities=frozenset(
        {
            ProviderCapability.ETF_INSTRUMENTS,
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.STOCK_QUOTES,
            ProviderCapability.INDEX_QUOTES,
        }
    ),
    role=ProviderRole.SECONDARY,
    requires_credentials=True,
    notes=(
        "Archive (data-pipeline/src/collector/cifang.py, src/config.py, "
        "scripts/cron_etf_kline_evening.py, scripts/sync_cifang_backfill.py) "
        "covered ETF list / real-time quotes / historical daily K via "
        "CIFANG_TOKEN and https://www.cifangquant.com/api. Archive default was qfq; "
        "v2 first release freezes adjustment='none' (ADR-0005), so old qfq/hfq MUST NOT "
        "be carried over."
    ),
    adjustment=ADJUSTMENT_NONE,
    risk_warnings=(
        "archive default qfq MUST NOT be carried over",
        "v2 only consumes adjustment='none'",
        "ETF_PROVIDER selection unfrozen (ADR-0003)",
    ),
    env_prefix="INVEST_PIPELINE_CIFANG_",
    credential_env_vars=("INVEST_PIPELINE_CIFANG_TOKEN",),
)


class CifangEtfMarketDataProvider:
    """Cifang ETF market-data Provider (placeholder).

    Every fetch method raises an explicit not-implemented signal so the
    adjustment='none' contract is visible while the archive's qfq default
    cannot be silently reintroduced.
    """

    provider_key = PROVIDER_KEY_CIFANG
    adjustment = ADJUSTMENT_NONE
    declaration = CIFANG_DECLARATION

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        adjustment: str,
        timeout_seconds: float,
    ) -> None:
        if not is_adjustment_allowed(adjustment):
            raise ValueError(
                "Cifang adjustment is locked to 'none' per ADR-0005; "
                f"refusing to construct with adjustment={adjustment!r}"
            )
        self._config = CifangAdapterConfig(
            token=token,
            base_url=base_url,
            adjustment=adjustment,
            timeout_seconds=timeout_seconds,
        )
        if not self._config.token:
            raise ProviderAuthenticationError(
                self.provider_key,
                "Cifang requires a token; INVEST_PIPELINE_CIFANG_TOKEN must be set "
                "via the deployment Secret, never via the repository.",
            )

    @property
    def config(self) -> CifangAdapterConfig:
        return self._config

    def _placeholder(self, capability: ProviderCapability) -> _FixtureBatch:
        raise ProviderAdapterNotImplementedError(
            self.provider_key,
            f"Cifang adapter is a placeholder for {capability.value!r}; "
            "old qfq/hfq behavior MUST NOT be re-enabled. v2 only consumes adjustment='none' "
            "and real HTTP stays blocked until O-1 is resolved.",
        )

    def fetch_instruments(self, as_of: date) -> _FixtureBatch:
        del as_of
        return self._placeholder(ProviderCapability.ETF_INSTRUMENTS)

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> _FixtureBatch:
        del symbols, start_date, end_date
        return self._placeholder(ProviderCapability.ETF_DAILY_BARS)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"CifangEtfMarketDataProvider(provider_key={self.provider_key!r})"
