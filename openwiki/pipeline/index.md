# Files

- [Pipeline overview](overview.md) - Dagster assets, ETL services, provider adapters, research orchestration, WorkBuddy integration, replay/backfill operations, and retired JiuwenSwarm compatibility code. JiuwenSwarm is not a current production path or acceptance dependency.
- [Provider–Engine–Event seam](provider-engine-event.md) - ADR-0013 Phase 0 / Phase 1 seam that introduces the ProviderRuntimeRegistry, the StockDailyBarsEngine command/outcome dataclasses, the StockDailyBarsApplication lifecycle, the ProviderHealthSnapshot derivation, and the Stage 4C fail-closed ProviderPublishDecision gate — the single typed entry point future Engine and Event layers will consume without re-implementing the catalog / factory / Dagster boundaries.
