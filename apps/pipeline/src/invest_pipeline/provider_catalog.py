"""Provider catalog declarations for the V2 pipeline (stdlib only).

This module is a **declaration catalog**, not an adapter implementation.
It records the ``provider_key``, ``role``, ``capabilities`` and
``enabled_by_default`` flag of providers that V2 knows about by name.
It is deliberately small:

* No HTTP, MCP or SDK transport is imported.
* No API key, token or credential handling is wired in.
* No runtime provider selection, factory or registry is implemented.
* No Dagster asset, schedule or database migration is added.
* No external network call is issued.

The catalog exists so the rest of the V2 codebase can reference
provider identifiers by their stable string values (see
``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`` §3) without
having to import a placeholder adapter. Today it only records the
Quicktiny MCP provider as ``research_only``; the matrix already lists
``akshare`` / ``cifangquant`` / ``rsscast`` / ``fixture_dev`` roles but
those entries are intentionally deferred to later increments — adding
them here without an accompanying adapter would be premature.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProviderRole(StrEnum):
    """Stable role identifiers for a provider in the V2 pipeline.

    The string values are frozen by ``DATA-SOURCE-MIGRATION-MATRIX.md``
    §3 and must not change without an ADR. ``RESEARCH_ONLY`` declares
    that the provider is not a production SLA source and must not be
    used as a primary or secondary ingest path.
    """

    RESEARCH_ONLY = "research_only"
    SECONDARY = "secondary"
    PRIMARY = "primary"
    OUT_OF_SCOPE_FOR_ETF = "out_of_scope_for_etf"
    FIXTURE_DEV = "fixture_dev"


class ProviderCapability(StrEnum):
    """Stable capability identifiers a provider may advertise.

    The string values are the canonical names referenced from
    ``DATA-SOURCE-MIGRATION-MATRIX.md`` §2. ``ETF_DAILY_BARS``,
    ``ETF_MASTER_DATA`` and ``INDEX_DAILY_BARS`` exist as identifiers so
    the catalog can explicitly **omit** them when a provider is not
    allowed to serve them; Quicktiny MCP does not advertise any of
    these capabilities.
    """

    RESEARCH = "research"
    MARKET_SNAPSHOT = "market_snapshot"
    ETF_DAILY_BARS = "etf_daily_bars"
    ETF_MASTER_DATA = "etf_master_data"
    INDEX_DAILY_BARS = "index_daily_bars"


@dataclass(frozen=True, slots=True)
class ProviderDeclaration:
    """A single provider declaration row.

    Attributes
    ----------
    provider_key:
        Stable, lower_snake_case provider identifier (for example
        ``"quicktiny_mcp"``). Persisted in ``raw.provider_batches``.
    role:
        Role the provider plays in the V2 pipeline. Drives runtime
        selection (out of scope for this increment).
    capabilities:
        Immutable tuple of capabilities the provider advertises. The
        tuple is empty-safe and ordered for deterministic output.
    enabled_by_default:
        Whether the provider is enabled by default. Real providers in
        V2 default to ``False`` per the migration matrix §6.
    """

    provider_key: str
    role: ProviderRole
    capabilities: tuple[ProviderCapability, ...]
    enabled_by_default: bool


QUICKTINY_MCP = ProviderDeclaration(
    provider_key="quicktiny_mcp",
    role=ProviderRole.RESEARCH_ONLY,
    capabilities=(
        ProviderCapability.RESEARCH,
        ProviderCapability.MARKET_SNAPSHOT,
    ),
    enabled_by_default=False,
)
"""Quicktiny MCP provider declaration (research_only).

The role and capability set mirror ``DATA-SOURCE-MIGRATION-MATRIX.md``
§3 — Quicktiny is research_only and is explicitly **not** an ETF
master-data or ETF daily-bars provider. The provider is disabled by
default per matrix §6.
"""


_PROVIDER_CATALOG: dict[str, ProviderDeclaration] = {
    QUICKTINY_MCP.provider_key: QUICKTINY_MCP,
}


def lookup_provider(provider_key: str) -> ProviderDeclaration:
    """Return the declaration registered under ``provider_key``.

    Parameters
    ----------
    provider_key:
        The provider identifier to look up.

    Raises
    ------
    KeyError
        If no provider is registered under ``provider_key``. The raised
        ``KeyError`` carries the requested key as its argument so
        callers (and tests) can assert on it directly.
    """
    try:
        return _PROVIDER_CATALOG[provider_key]
    except KeyError as exc:
        raise KeyError(provider_key) from exc


__all__ = [
    "ProviderCapability",
    "ProviderDeclaration",
    "ProviderRole",
    "QUICKTINY_MCP",
    "lookup_provider",
]