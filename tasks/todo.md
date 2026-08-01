# Phase 1 ETF Data Ingestion TODO

- [x] Reconcile current repository state and test baseline
- [x] Add CifangQuant primary-provider ADR (Proposed)
- [x] Implement first increment: disabled settings and placeholder adapter
- [x] Add first-increment contract tests
- [x] Register Quicktiny MCP as a `research_only` declaration in the code catalog
      (`apps/pipeline/src/invest_pipeline/provider_catalog.py` + unit tests
      `apps/pipeline/tests/unit/test_provider_catalog.py`); matrix and Phase 1
      plan updated to reflect the declaration, ETF / index daily-bars and ETF
      master-data capabilities explicitly absent, `enabled_by_default=False`,
      unknown lookup raises `KeyError`. No HTTP / MCP transport, no Dagster
      asset, no DB migration, no credentials.
- [ ] Implement CifangQuant HTTP client/mapper/real adapter (requires O-1/O-3/O-4)
- [ ] Add opt-in provider smoke command
- [ ] Integrate provider selection into pipeline runtime
- [ ] Implement ingestion services and quality checks
- [ ] Add Dagster single-day and backfill jobs
- [ ] Run PostgreSQL and Dagster verification
- [ ] Run authorized CifangQuant smoke test
- [x] ARC first-increment diff and acceptance review
