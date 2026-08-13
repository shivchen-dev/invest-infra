# Implementation Plan: Provider–Engine–Event 架构增强

## Overview

在 Stage 4C-MVP 完成后，以 Stock Daily 为首个垂直切片，收敛 Provider 运行时
注册与应用编排；只有出现两个真实消费者后才加入同步、run-scoped 批次事件。
详细架构和边界见
`docs/plan/invest-infra-provider-engine-event-architecture-enhancement-plan.md`。

## Architecture Decisions

- 复用 catalog、routing、factory、PipelineRun、Repository/UoW 和 Dagster；
- Registry 是既有机制的深模块，不是第二份 provider 权威源；
- Engine 以单一用例为粒度，首版只有 `execute(command) -> outcome`；
- Event Dispatcher 条件实施，不承担调度、持久化或重放；
- 所有实现阶段必须在 Stage 4C Checkpoint B 关闭之后。

## Task List

### Phase 0: 基线与决策冻结

- [x] T0.1：完成并确认 Stage 4C-MVP Checkpoint B
- [x] T0.2：记录 Stock Daily 现有行为基线和 focused test 命令
- [x] T0.3：编写并评审 Provider–Engine–Event ADR

### Checkpoint A: Architecture Gate

- [x] Stage 4C 已关闭
- [x] 权威关系、非目标、首个垂直切片和回滚方式已获用户确认
- [x] 未开始业务代码改动（门禁完成后才开始实现）

### Phase 1: Provider Runtime Registry

- [x] T1.1：为 catalog/routing/factory 增加 characterization tests
- [x] T1.2：实现最小 Registry 与不可变解析结果
- [x] T1.3：迁移 Stock Daily 单一调用点并验证兼容行为

### Checkpoint B: Provider Resolution

- [x] 选择、启用、凭据、能力和 fallback 行为与基线一致
- [x] 无数据库 migration、无外部网络依赖
- [x] 旧 factory 入口仍可回滚使用

### Phase 2: Stock Daily Application Engine

- [x] T2.1：冻结 Stock Daily command/outcome 合同
- [x] T2.2：抽取 Engine 生命周期并保留现有 ETL 服务
- [x] T2.3：迁移 Dagster Asset，稳定后迁移手工入口（手工入口暂不迁移）
- [x] T2.4：覆盖 duplicate/failed/partial/stale/fallback 状态

### Checkpoint C: Vertical Slice

- [x] raw/core/analytics 内容与 Asset metadata 保持基线兼容
- [x] PipelineRun 生命周期、幂等和 fail-closed 验证通过
- [x] Engine 单测不启动 Dagster、不连接真实 Provider

### Phase 3: Provider Health

- [x] T3.1：冻结派生健康状态与 as_of 语义
- [x] T3.2：实现只读 health snapshot
- [x] T3.3：接入 Engine preflight，不改变 provider selection

### Checkpoint D: Health

- [x] fixture 可确定性重算
- [x] 无证据返回 unknown
- [x] 不新增数据库表

### Phase 4: Conditional Batch Events — Cancelled

因当前没有两个真实、已批准、可测试的事件消费者，用户决定取消本阶段。
因此不冻结事件合同、不实现 Dispatcher、不接入 Engine，也不需要 Checkpoint E。

- [x] T4.0：双消费者门禁未满足，取消 Phase 4
- [x] T4.1：不适用
- [x] T4.2：不适用
- [x] T4.3：不适用

### Checkpoint E: Events — Not Applicable

Phase 4 已按双消费者门禁取消；没有事件实现，也没有事件验收项。

### Phase 5: Review and Expansion Decision

- [x] T5.1：执行全量技术验收和工作树审计
- [x] T5.2：完成当前 Stock Daily 切片收口，扩展下一个切片不在本次授权范围
- [x] T5.3：保留旧接线，未提前清理

### Checkpoint F: Complete

- [x] focused/full tests、Ruff、架构检查、diff 检查通过
- [x] 相关 PostgreSQL round-trip/replay：本计划未新增 migration 或 PostgreSQL 结构，判定不适用
- [x] 文档、ADR、代码和测试保持一致
- [x] 用户审核并决定关闭当前计划，Phase 4 已取消

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Engine 过宽 | High | 首版单用例、单入口 |
| Provider 权威漂移 | High | Registry 只消费既有 catalog/routing |
| Event/事务不一致 | High | 事件只引用持久化 ID，覆盖 rollback 测试 |
| 4C 被打断 | High | Phase 0 硬门禁 |
| 大范围迁移 | High | 单垂直切片和独立回滚提交 |

## Closed Decisions

- Checkpoint A 已批准并完成。
- Phase 4 未满足两个真实消费者门禁，已取消；未来只有出现两个已批准消费者时才可重新立项。
- 当前计划收口于 Stock Daily；扩展下一个垂直切片需要新的用户授权。
