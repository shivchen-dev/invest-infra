# ADR-0013：Provider–Engine–Event 架构增强

## Status

Accepted for Phase 0 / implementation gated by checkpoints

## Date

2026-08-13

## Context

Provider catalog、routing、factory、Dagster 编排与 Repository/UoW 已分别承担
声明、选择、构造、作业调度和事务持久化职责。当前需要为后续运行时收敛冻结
权威关系，同时避免把 Provider 接入误建成交易系统或第二套调度框架。

本 ADR 借鉴 vn.py 的 Gateway / Engine / Event 思想，用于理解“外部能力适配、
应用生命周期、批次结果通知”的边界；不引入 vn.py 依赖、代码、交易模型或其
线程事件循环。

## Decision

### 1. 权威关系

- catalog 是 Provider 声明与 capability 的唯一权威源；
- routing 是 dataset 到 Provider 的选择策略唯一权威源；
- factory/Registry 是 adapter 构造的唯一运行时入口；Registry 必须复用 catalog、
  routing 和既有 factory 逻辑，不维护第二份清单；
- Dagster 是作业图与调度的唯一权威源；Engine 不替代 Dagster；
- PipelineRun 及 raw/core/analytics 表是持久化运行事实；
- Event Dispatcher 只传递已经发生的批次结果，不参与事实恢复、重放或调度。

### 2. Registry / Engine 首版边界

首版 `ProviderRuntimeRegistry` 只提供 Provider 解析与声明查询，内部复用既有
选择、显式启用、凭据门禁和 adapter 构造。它不提供动态插件扫描、运行时卸载、
全局 singleton 或自动 fallback。

首版 Application Engine 只服务 `stock_daily_bars_by_trade_date`，负责 preflight、
运行冲突检查、Provider 解析、主备执行、结果归类和 PipelineRun 终态；request /
attempt / batch 与 Core facts 仍由现有 ETL 服务负责。Engine 不拥有长期数据库
Session，也不直接包含 SQLAlchemy、Dagster 或 Provider SDK 细节。

### 3. 事件两消费者门禁

只有同一批次结果已有至少两个独立、已批准且可测试的消费者时，才实现
Event Dispatcher。候选消费者包括运行审计/PipelineRun 与 Provider quality/
可观测性聚合；未满足门禁则取消该阶段，不为抽象而实现事件层。

事件首版限定为 `ProviderBatchCompleted`、`ProviderBatchFailed`、
`CoreFactsPublished`、`AnalyticsObservationPublished` 和
`PipelineRunCompleted`。Dispatcher 同步、按注册顺序、仅限单次 Engine 执行；
事件不得携带完整 payload、凭据或大型领域对象，不使用消息队列、线程或异步总线。

## Rollback

Registry 迁移先保持旧 factory 入口作为兼容适配器，单个调用点可恢复为直接
factory 调用。Engine 迁移可将 Asset/CLI 切回原服务调用。事件层通过 No-op
Dispatcher 回滚并删除接线；不新增数据库结构，且不得出现“数据已回滚但发布
成功事件”的状态。

## Non-goals

- 不实现订单、成交、持仓、账户、风控、撮合、策略执行或交易 Gateway；
- 不复制 vn.py 的类名、代码结构或交易领域语义；
- 不替换 Dagster 或新增 scheduler、消息队列、微服务、outbox；
- 不改变 Stage 4C 的数据规则、分析指标、Provider 选择或事实持久化语义；
- 不在本 ADR 中扩展 ResearchEvidenceBundle、Dashboard、分钟线、Tick 或 Level-2。

## Consequences

后续实现必须逐 Checkpoint 推进，并保留既有行为基线、独立测试和回滚路径。架构
增强只收敛已有职责，不产生新的 Provider/capability 或事实权威源。
