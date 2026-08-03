"""QuickTiny MCP adapter package (PR-03, DATA-SOURCE-MIGRATION-MATRIX.md §9.1 / §9.2).

The package is split into three cooperating modules plus this
``__init__.py`` so the public surface stays flat and importable from
CI / local dev without an MCP transport.

Boundary rules:

- ``config.py`` never imports ``httpx`` and never touches the network —
  it is a pure pydantic ``BaseSettings`` object (disabled by default per
  matrix §6, ``base_url`` defaulting to the official MCP endpoint,
  ``token`` stored as :class:`pydantic.SecretStr`).
- ``models.py`` is the *only* module that exposes response / result
  shapes to the application layer. Models are frozen, ``slots=True``
  dataclasses with a deterministic ``raw_payload_hash``. The module
  never imports ``httpx``.
- ``client.py`` is the only module that may own an ``httpx.Client``; the
  transport is injectable so CI runs against ``httpx.MockTransport``
  and never reaches the network.

PR-03 deliberately **does not** map responses to
:class:`invest_domain.market_data.models.DailyBar`, does not advertise
``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` / ``INDEX_DAILY_BARS`` and does
not extend :mod:`invest_pipeline.provider_factory`. The catalog
declaration :data:`invest_pipeline.provider_catalog.QUICKTINY_MCP` stays
the single source of truth for the role / capability set.
"""

from __future__ import annotations

from invest_pipeline.adapters.quicktiny_mcp.client import QuickTinyMcpClient
from invest_pipeline.adapters.quicktiny_mcp.config import QuickTinyMcpSettings
from invest_pipeline.adapters.quicktiny_mcp.models import (
    QuickTinyMcpMarketSnapshot,
    QuickTinyMcpResponse,
    QuickTinyMcpToolCallResult,
    QuickTinyMcpToolDescriptor,
    QuickTinyMcpToolListResult,
    hash_market_snapshot_records,
    normalise_market_snapshot,
    record_to_mapping,
)

__all__ = [
    "QuickTinyMcpClient",
    "QuickTinyMcpMarketSnapshot",
    "QuickTinyMcpResponse",
    "QuickTinyMcpSettings",
    "QuickTinyMcpToolCallResult",
    "QuickTinyMcpToolDescriptor",
    "QuickTinyMcpToolListResult",
    "hash_market_snapshot_records",
    "normalise_market_snapshot",
    "record_to_mapping",
]