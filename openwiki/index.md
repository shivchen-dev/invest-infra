---
okf_version: "0.1"
---

# Files

- [OpenWiki Quickstart](quickstart.md) - Entry point for the invest-infra OpenWiki knowledge base. Describes the modular-monolith layout, links every major concept page, and summarizes local startup, migrations, personal daily scheduling and replay/backfill operations, testing, opt-in CifangQuant / Tushare / JiuwenSwarm validation, the DC-2 ETF profile and Stage 4A evidence / context slices, the ADR-0012 evidence-driven Research lifecycle (PR-7 API + JiuwenSwarm adapter + orchestration service + context-projection loader + PR-W03 dashboard / PR-W05 case workspace read models), the PR-MCP-MINIMAL read-only MCP server, the DC-3 exposure collection slice, the Research Cockpit web workbench (widget runtime + dashboard widgets + safe markdown renderer), the centralized provider credential store, the Stage 4B Market Intelligence foundation (Market Observation / Temperature / Breadth read slices + Tushare-stock by-date pipeline + TDX offline fallback + Research Evidence Bundle chain), the Stage 4C Core Data Layer Integration (versioned price-limit domain policy + Stock Price-Limit raw/core persistence + Market Breadth v2 + Limit Sentiment + 18-revision chain), the ADR-0013 Provider–Engine–Event Phase 0 seam (ProviderRuntimeRegistry + StockDailyBars Engine/Application + provider publishability gate), the HiThink reserved provider catalog entry, the WorkBuddy daily-report governance (M0/M1/M2: validator + immutable archive + accepted-only latest-pointer) plus WorkBuddy candidate intake (M0 contract: parser + immutable archive + symbol/projection dedupe + shared-directory gateway), and the Stage 4D External Integration Workbench (Bridge ingest + `integration` schema + External Workflow Run / Artifact / Observation read API + Opportunity Radar + Integration Health + Research-Case evidence link + gated admission-decision command). Two independently-evolving pipelines that share the strict `YYYY-MM-DD` / safe-path-segment identity contract.

# Directories

- [_plan](_plan/)
- [api](api/)
- [architecture](architecture/)
- [domain](domain/)
- [migrations](migrations/)
- [pipeline](pipeline/)
- [storage](storage/)
- [testing-and-ops](testing-and-ops/)
