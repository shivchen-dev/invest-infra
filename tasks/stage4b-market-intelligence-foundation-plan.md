# Stage 4B Market Intelligence Foundation — Implementation Plan

## Overview

以 GitHub/Gitee `main` `8caff02` 为基线，在不修改现有 ETF `EvidencePack` 8 因子合同的前提下，增加 Analytics-owned Market Observation，并由 Research Evidence Bundle 按 Case 绑定。首个垂直切片只实现基于现有 ETF Universe 的 Market Temperature。

## Architecture Decisions

- Market Intelligence 是 `Analytics` 子域，不是新的顶层领域或微服务。
- `EvidencePack` 保持 Research Case-scoped、不可变、固定 8 因子。
- `MarketObservationSnapshot` 保存可复用确定性市场事实。
- `ResearchEvidenceBundle` 绑定 ETF EvidencePack 与 Market Snapshot；Bundle 是 AI Research 的完整输入身份。
- `ContextProjection` 是 Bundle 的可重建读取视图，不是事实源。
- 首期不新增 Provider、不接商业研究数据、不新增 UI 和 Agent Tool。

## Task List

### Phase 0: Contract and ownership

- [ ] 冻结 Observation、Bundle、Projection 的字段和 hash 合同。
- [ ] 冻结 `etf_active_universe_v1`、as-of、quality、freshness 和 algorithm version。
- [ ] 更新 ADR/Architecture/OpenWiki，确保唯一 ownership 链路。

### Phase 1: Deterministic Observation

- [ ] 增加 Analytics-owned Market Observation domain model。
- [ ] 实现 canonical serialization、item hash、snapshot hash。
- [ ] 实现纯函数 Market Temperature builder。
- [ ] 增加 fixture ETF 的 complete/partial/missing/failed 测试。

### Checkpoint A

- [ ] Domain focused tests pass。
- [ ] 相同输入生成相同 hash 和 observation IDs。
- [ ] Builder 不访问 DB、Provider、环境变量或 AI。

### Phase 2: Persistence

- [ ] 增加 snapshot/item migration、row model、Repository 和 UoW。
- [ ] 增加幂等写入、历史保留和 rollback 测试。
- [ ] 增加显式 Pipeline/Dagster 编排入口。

### Checkpoint B

- [ ] PostgreSQL round-trip pass。
- [ ] upgrade/downgrade pass。
- [ ] 相同输入不重复写入，不同输入不覆盖旧快照。

### Phase 3: Research Bundle

- [ ] 增加 ResearchEvidenceBundle 的绑定和 hash。
- [ ] 兼容现有 ResearchRun.evidence_pack_id，并为新 Run 增加 bundle 引用。
- [ ] 增加 Context Projection 和 Evidence ID 校验。
- [ ] 扩展 Fake Runner 测试覆盖 Bundle 输入。

### Checkpoint C

- [ ] Run/Result 可追溯至 ETF EvidencePack 和 Market Snapshot。
- [ ] Result 不能修改任一上游事实。
- [ ] Bundle 变化产生新的输入身份。

### Phase 4: API and acceptance

- [ ] 增加 `GET /api/v1/market-temperature/latest`。
- [ ] 完成 OpenAPI、404/422/安全边界和只读测试。
- [ ] 完成 seeded Case → Observation → Bundle → Run → Result 验收。
- [ ] 生成 Stage 4B Phase 1 acceptance report。

## Verification

- Domain focused tests
- Pipeline focused tests
- Storage mock and PostgreSQL integration tests
- Migration chain round-trip
- API TestClient and OpenAPI freshness
- Ruff/architecture boundary check
- `git diff --check`

## Deferred

- Market Breadth
- Market Style
- Theme Intelligence
- ETF Rotation
- 新 Provider 和商业研究数据
- Market Intelligence UI
- Agent Tool
