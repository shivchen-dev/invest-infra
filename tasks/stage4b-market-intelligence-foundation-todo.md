# Stage 4B Market Intelligence Foundation — Todo

- [x] Phase 0：Observation / Bundle / Projection contract freeze
- [x] Phase 0：ETF Universe、as-of、quality、freshness、algorithm version freeze
- [x] Phase 0：ADR/Architecture/OpenWiki alignment
- [x] Phase 1：Analytics Market Observation domain model
- [x] Phase 1：Market Temperature deterministic builder
- [x] Phase 1：Hash and quality focused tests
- [x] Checkpoint A：Domain and architecture gates pass（Domain gate；存储/生产门禁仍待后续阶段）
- [x] Phase 2：Snapshot/item migration and persistence
- [x] Phase 2：Idempotency, revision, rollback, PostgreSQL integration
- [x] Checkpoint B：Storage and migration gates pass（Storage 226 tests；迁移 upgrade/downgrade/upgrade；integration 106 tests）
- [x] Phase 3：ResearchEvidenceBundle binding（含迁移、Repository、UoW、历史快照幂等语义）
- [x] Phase 3：Context Projection and Evidence ID validation
- [x] Phase 3：Fake Runner/ResearchResult integration
- [x] Checkpoint C：Full traceability passes
- [x] Phase 4：Market Temperature read-only API
- [x] Phase 4：OpenAPI and security contract
- [x] Phase 4：Seeded acceptance report
- [x] Final：ARC independent review and worktree audit

## Slice 2：Market Breadth（Contract & Builder, 2026-08）

在 Phase 0–4 收板后启动。首切片只冻结 domain contract 与 builder，
不动 Market Temperature Evidence/Bundle 语义，不新增 Provider、UI
或 Agent Tool。

- [x] Slice 2 Phase 0：Universe / scope / algorithm version 冻结（`ashare_active_universe_v1` / `1.0.0`）
- [x] Slice 2 Phase 1：`MarketBreadthInput` + `build_market_breadth()` 纯函数 builder
- [x] Slice 2 Phase 1：first-slice 三项指标（`advancing_ratio` / `declining_ratio` / `above_ma20_ratio`）clip & quantise
- [x] Slice 2 Phase 1：empty / stale / unknown / suspended fail-closed 路径
- [x] Slice 2 Phase 1：hash / observation-id / scope 稳定性 focused 测试（15 项）
- [x] Slice 2 Checkpoint A：Domain / arch-check / ruff format pass
- [ ] Slice 2 Phase 2：Repository / migration / UoW（沿用 `analytics.market_observation_snapshots`，待 A 股 daily bars 接入后启动）
- [ ] Slice 2 Phase 3：`/api/v1/market-breadth/latest` OpenAPI 冻结 + Router
- [ ] Slice 2 Phase 4：Bundle 注册（评估是否把 Market Breadth snapshot 加入 `ResearchEvidenceBundle`）
- [ ] Slice 2 Phase 5：A 股 daily bars Provider 走 Provider Contract + Catalog + Data Admission
