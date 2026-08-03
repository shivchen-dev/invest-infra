"""RssCast MCP adapter package (PR-04, DATA-SOURCE-MIGRATION-MATRIX.md §1 / §3 / §5.4).

The package is split into three cooperating modules plus this
``__init__.py`` so the public surface stays flat and importable from
CI / local dev without an MCP transport.

Boundary rules:

- ``config.py`` never imports ``httpx`` and never touches the network —
  it is a pure pydantic ``BaseSettings`` object (disabled by default per
  matrix §6, ``base_url`` defaulting to the empty string because matrix
  §1 explicitly does not freeze a fixed endpoint, ``token`` stored as
  :class:`pydantic.SecretStr`).
- ``models.py`` is the *only* module that exposes response / result
  shapes to the application layer. Models are frozen, ``slots=True``
  dataclasses with deterministic ``request_params_hash`` /
  ``response_hash`` digests. The module never imports ``httpx``.
- ``client.py`` is the only module that may own an ``httpx.Client``; the
  transport is injectable so CI runs against ``httpx.MockTransport``
  and never reaches the network.

PR-04 deliberately **does not** map responses to
:class:`invest_domain.market_data.models.DailyBar`, does not advertise
``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` and does not extend
:mod:`invest_pipeline.provider_factory`. The catalog declaration
:data:`invest_pipeline.provider_catalog.RSSCAST` stays the single
source of truth for the role / capability set.
"""

from __future__ import annotations

from invest_pipeline.adapters.rsscast.client import RssCastMcpClient
from invest_pipeline.adapters.rsscast.config import RssCastMcpSettings
from invest_pipeline.adapters.rsscast.models import (
    RssCastMcpResearchResponse,
    RssCastMcpResponse,
    RssCastMcpToolDescriptor,
    RssCastMcpToolListResult,
    hash_research_responses,
    is_forbidden_tool_name,
    normalise_tool_list,
)

__all__ = [
    "RssCastMcpClient",
    "RssCastMcpResearchResponse",
    "RssCastMcpResponse",
    "RssCastMcpSettings",
    "RssCastMcpToolDescriptor",
    "RssCastMcpToolListResult",
    "hash_research_responses",
    "is_forbidden_tool_name",
    "normalise_tool_list",
]