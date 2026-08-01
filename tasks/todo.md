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
- [x] Implement CifangQuant HTTP client/mapper/real adapter (fixture-first
      second increment; gated on O-1 / O-3 / O-4 — `enabled=False` by default,
      no real network, no Dagster wiring). httpx-based
      `CifangClient` (transport/sleep/clock injectable, 50-symbol chunking,
      401/403 fail-fast, 5xx/429/timeout retries up to 3 attempts, 4xx
      deterministic), mapper (SH→SSE / SZ→SZSE, ETF filter, nullable
      prev_close/amount preserved, `adjust=none` enforced), evidence-tuple
      adapter. Minimal Domain fix: `DailyBar.prev_close` allowed `None`
      per ADR-0005 §3 + ADR-0011 §2 (covered by
      `packages/domain/tests/test_market_data.py`); MockTransport
      / fake-clock tests in
      `apps/pipeline/tests/unit/test_cifangquant_{client,mapping,adapter_e2e}.py`.
      `httpx` added to `apps/pipeline/pyproject.toml` and `uv.lock`.
      Provider stays disabled-by-default; no Dagster provider-selection,
      no DB migration, no production secret.
- [ ] Add opt-in provider smoke command
- [ ] Integrate provider selection into pipeline runtime
- [ ] Implement ingestion services and quality checks
- [ ] Add Dagster single-day and backfill jobs
- [ ] Run PostgreSQL and Dagster verification
- [ ] Run authorized CifangQuant smoke test (requires O-1/O-3/O-4)
- [x] ARC first-increment diff and acceptance review
