from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProviderCapability(StrEnum):
    ETF_INSTRUMENTS = "etf_instruments"
    ETF_DAILY_BARS = "etf_daily_bars"
    ETF_TRADING_CALENDAR = "etf_trading_calendar"
    INDEX_QUOTES = "index_quotes"
    STOCK_QUOTES = "stock_quotes"
    RESEARCH_REPORTS = "research_reports"
    MARKET_SNAPSHOT = "market_snapshot"


class ProviderRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    RESEARCH_ONLY = "research_only"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class ProviderDeclaration:
    provider_key: str
    capabilities: frozenset[ProviderCapability]
    role: ProviderRole
    requires_credentials: bool
    notes: str
    adjustment: str | None = None
    risk_warnings: tuple[str, ...] = field(default_factory=tuple)
    env_prefix: str | None = None
    credential_env_vars: tuple[str, ...] = field(default_factory=tuple)


PROVIDER_KEY_AKSHARE = "akshare"
PROVIDER_KEY_CIFANG = "cifang"
PROVIDER_KEY_RSSCAST = "rsscast"
PROVIDER_KEY_QUICKTINY_MCP = "quicktiny_mcp"
PROVIDER_KEY_FIXTURE_DEV = "fixture_dev"

ADJUSTMENT_NONE = "none"

ALLOWED_ADJUSTMENTS: frozenset[str] = frozenset({ADJUSTMENT_NONE})


def is_adjustment_allowed(value: str) -> bool:
    return value in ALLOWED_ADJUSTMENTS
