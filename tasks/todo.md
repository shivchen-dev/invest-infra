# DC-2 ETF Profile 第一切片

- [x] `EtfProfile` domain contract
- [x] `core.etf_profiles` migration/model/repository
- [x] Focused tests and migration-chain verification
- [x] AkShare Profile adapter + mapper + evidence ETL
- [x] Real Provider Profile collection verification

## Boundary note (replaces the old verified blocker)

- Controlled read-only smoke on 2026-08-05 confirmed two static Profile channels for this slice:
  - `fund_name_em` returned 27,414 rows.
  - `fund_etf_spot_em` returned 1,565 rows.
- Boundary: `fund_etf_fund_info_em(fund=...)` remains a historical NAV channel and must not be a source for `EtfProfile` fields; NAV stays on the dedicated `fund_etf_fund_daily_em` path and is not back-filled into `core.etf_profiles`.
- Unverified fields remain `None`: manager, benchmark, inception, fees, AUM. AUM is never equated with total market value.
- Out of this DC-2 first-slice scope: API/Web/Dagster wiring, indices, constituents, holdings.

---

# Stage 3 Completion Checklist

- [x] Full local baseline
- [x] Web unit tests (8 files, 54 tests passed on 2026-08-04)
- [x] Web typecheck/build after test setup
- [x] PostgreSQL Fixture E2E
- [x] Schedule/preflight verification
- [ ] Documentation refresh
- [ ] CifangQuant acceptance (blocked on external evidence)
- [ ] Ten-trading-day shadow run (blocked on runtime deployment)
