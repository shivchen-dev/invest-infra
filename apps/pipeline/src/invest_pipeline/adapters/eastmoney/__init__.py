"""Eastmoney (东方财富) adapter package (three-provider plan, Phase 1).

Phase 1 of the V2 three-provider plan
(``tasks/plan-data-source-three-provider.md``) freezes the catalog
declaration and ships the configuration skeleton for the Eastmoney
adapter. The catalog entry
:data:`invest_pipeline.provider_catalog.EASTMONEY` records the
``research_only`` role, the three market-data capabilities
(``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` / indirect
``INDEX_DAILY_BARS``) and the ``enabled_by_default=False`` rule.

Phase 1 deliberately **does not**:

- Implement the HTTP client. Phase 2 adds the read-only client, the
  field mapper and the evidence-tuple adapter (mirroring the Cifang
  layout).
- Extend :mod:`invest_pipeline.provider_factory`. The runtime factory
  keeps its three-key surface (``fixture_dev`` / ``cifangquant`` /
  ``akshare``); the three-provider plan Phase 1 only adds the catalog
  declaration and the configuration skeleton.
- Touch the network, the database, the candidate-pool rules or any
  Dagster asset / schedule.
- Import ``httpx``. Construction is pure pydantic ``BaseSettings`` so
  the package is importable in CI without the optional HTTP transport.

Boundary rule: ``config.py`` never imports ``httpx`` and never reaches
the network; Phase 2 will add ``client.py`` / ``mapper.py`` /
``adapter.py`` that follow the Cifang adapter layout.
"""

from __future__ import annotations

from invest_pipeline.adapters.eastmoney.config import EastmoneySettings

__all__ = ["EastmoneySettings"]
