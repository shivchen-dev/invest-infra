# DC-3 Completion Plan

## Completion contract

DC-3 is complete only when a real, opt-in AkShare run can resolve an existing ETF
instrument, collect index constituents and reported ETF holdings, persist the exposure
records transactionally, and run through an explicit CLI and a disabled-by-default
Dagster job. Fixture-only success is insufficient.

The upstream does not provide a stable ETF-to-index code or a true mapping effective
date. Therefore the real workflow requires controlled operator inputs for
`index_code` and `mapping_effective_from`; observation time must never be substituted
for the effective date.

## Ordered slices

1. Real collection service
   - Resolve ETF by explicit `(exchange, symbol)` business key.
   - Fetch/map CSIndex constituents and latest reported ETF holdings.
   - Create the stable local index identity and controlled ETF-index mapping.
   - Persist profile, constituents, mapping and holdings in one transaction.
2. Explicit CLI
   - Require network confirmation and controlled mapping inputs.
   - Keep AkShare optional/lazily imported and emit deterministic errors.
3. Dagster wiring
   - Add one opt-in asset/job; no default schedule or silent network access.
4. Verification
   - Unit and PostgreSQL integration tests, idempotency and rollback coverage.
   - Real AkShare manual run against an existing local ETF.
   - Full repository gates and documentation status update.

## Risks

- AkShare availability and schema drift: validate every row and fail closed.
- ETF/index ambiguity: require explicit exchange, symbol, index code and effective date.
- Periodic holdings mistaken for PCF: preserve the
  `reported_portfolio_holdings` dataset key and latest-quarter semantics.
- Network side effects in CI: real collection remains explicit and disabled by default.

## Completion evidence (2026-08-06)

- Real endpoint validation: ETF `510300` / index `000300`, reported holdings year `2025`.
- PostgreSQL target: isolated `invest-postgres-v2` database after Alembic upgrade to
  `20260806_0011`.
- Real AkShare schema drift handled: `季度=2025年1季度股票投资明细` is normalized to
  the 2025 Q1 report date while unknown suffixes still fail closed.
- Idempotency verified with revision `2`: two real runs returned identical IDs, business
  content hashes, and raw payload hashes for all persisted sections.
- Safety gates: CLI requires both environment enablement and `--confirm-network`;
  Dagster asset defaults disabled and has no schedule or sensor.
- Automated verification: pipeline, exposure-domain, focused mapper/service/CLI/asset/job,
  architecture, and touched-file lint gates pass.
