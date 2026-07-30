from __future__ import annotations

from invest_pipeline.providers.capabilities import (
    PROVIDER_KEY_QUICKTINY_MCP,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)


QUICKTINY_MCP_DECLARATION = ProviderDeclaration(
    provider_key=PROVIDER_KEY_QUICKTINY_MCP,
    capabilities=frozenset(
        {
            ProviderCapability.RESEARCH_REPORTS,
            ProviderCapability.MARKET_SNAPSHOT,
        }
    ),
    role=ProviderRole.RESEARCH_ONLY,
    requires_credentials=True,
    notes=(
        "quicktiny MCP was used in archive for report / market-snapshot helpers. "
        "It is explicitly out-of-scope as a standard ETF daily-bar Provider; v2 "
        "does not declare ETF_DAILY_BARS for it."
    ),
    adjustment=None,
    risk_warnings=(
        "ETF_DAILY_BARS not in scope",
        "report / snapshot helpers only; cannot substitute for an ETF Provider",
    ),
    env_prefix="INVEST_PIPELINE_QUICKTINY_MCP_",
    credential_env_vars=("INVEST_PIPELINE_QUICKTINY_MCP_TOKEN",),
)
