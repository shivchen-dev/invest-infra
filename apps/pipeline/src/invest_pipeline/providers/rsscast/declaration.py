from __future__ import annotations

from invest_pipeline.providers.capabilities import (
    PROVIDER_KEY_RSSCAST,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)


RSSCAST_DECLARATION = ProviderDeclaration(
    provider_key=PROVIDER_KEY_RSSCAST,
    capabilities=frozenset(
        {
            ProviderCapability.STOCK_QUOTES,
            ProviderCapability.INDEX_QUOTES,
        }
    ),
    role=ProviderRole.RESEARCH_ONLY,
    requires_credentials=True,
    notes=(
        "RssCast was used in archive data-pipeline/src/collector/rsscast.py to cover "
        "stock / index MCP quotes. It MUST NOT be marked as supporting ETF_DAILY_BARS; "
        "no ETF daily-bar adapter will be wired for RssCast in v2."
    ),
    adjustment=None,
    risk_warnings=(
        "ETF_DAILY_BARS not in scope",
        "research-only; cannot become a v2 ETF Provider",
    ),
    env_prefix="INVEST_PIPELINE_RSSCAST_",
    credential_env_vars=("INVEST_PIPELINE_RSSCAST_TOKEN",),
)
