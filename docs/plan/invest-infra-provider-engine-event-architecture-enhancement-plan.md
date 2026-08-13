# invest-infra Provider–Engine–Event 架构增强实施计划

> 文档版本：v1.0（评审稿）  
> 状态：Phase 0 已通过，进入实施  
> 编制日期：2026-08-13  
> 实现基线：`7b3468d`  
> 前置门禁：Stage 4C-MVP Checkpoint B 完成并由用户确认关闭

## 1. 结论

本项目可以借鉴 vn.py 的 Gateway、MainEngine、EventEngine 思想，但不引入
vn.py 代码、依赖或交易领域模型，也不另建一套与现有 Provider、Dagster、
Repository/UoW 平行的框架。

本计划只做三项增量增强：

1. 将已有 Provider catalog、factory、routing 收敛为一个统一的运行时注册入口；
2. 将重复的执行生命周期收敛到一个轻量 Application Engine；
3. 仅在出现至少两个真实消费者后，引入同步、进程内、单次运行范围的批次事件。

Stage 4C 已完成验收并关闭。本计划不得改变 4C 的范围、验收标准或已交付语义。

## 2. 现状证据与问题定义

### 2.1 已有能力必须复用

- Provider 声明、角色和能力已存在于
  `apps/pipeline/src/invest_pipeline/provider_catalog.py:110`、`:129`、`:198`；
- factory 已从 catalog 派生运行时 provider key，并承担显式启用及凭据门禁，见
  `apps/pipeline/src/invest_pipeline/provider_factory.py:84`、`:139`、`:196`；
- Dataset 到 capability 的稳定映射已存在，见
  `apps/pipeline/src/invest_pipeline/provider_routing/datasets.py:55`、`:108`；
- Tushare → TDX fallback 已有确定性应用编排，见
  `apps/pipeline/src/invest_pipeline/stock_daily_bars.py:464`、`:570`；
- PipelineRun 已有六状态合同，见
  `packages/domain/src/invest_domain/pipeline/models.py:33`、`:75`；
- Repository/UoW 已承担事务和运行状态持久化，见
  `packages/storage/src/invest_storage/unit_of_work.py:1`、`:150`；
- 研究执行已有可复用的“两事务 + 外部调用置于事务外”编排范式，见
  `apps/pipeline/src/invest_pipeline/research_orchestration_service.py:281`；
- 系统既定约束是模块化单体、PostgreSQL-first、不提前引入消息队列，见
  `README.md:7`、`:8`、`:9`。

### 2.2 当前真实问题

1. **声明、选择与构造分散。** catalog 描述能力，routing 负责选择，factory
   使用分支构造 adapter；调用方仍需了解多个入口及 provider 类型差异。
2. **执行生命周期分散。** Dagster Asset、手工 CLI、回填 CLI 分别处理 preflight、
   PipelineRun、异常归类、数据库生命周期和输出转换，存在规则漂移风险。
3. **跨阶段结果只有返回值、Dagster metadata 和日志。** 当前不需要全局事件总线，
   但当质量统计、运行审计等多个消费者同时依赖相同阶段结果时，继续在调用方逐一
   接线会形成重复耦合。

### 2.3 不成立的问题

- 系统并不缺 Provider 抽象，因此不新建 `Gateway` 基类替代现有 ports；
- Dagster 已承担作业图与调度，因此不新建第二套 scheduler；
- UoW 已承担事务，因此 Engine 不拥有长期 Session；
- Provider request/attempt/batch 已是证据事实，事件不得成为新的事实权威源。

## 3. 目标架构

```text
Dagster / CLI / Backfill（入口与调度）
                  │
                  ▼
        Application Engine（单次用例生命周期）
          ├── Provider Runtime Registry
          ├── Preflight / Failure Classification
          ├── PipelineRun Recorder
          └── 可选 Run-scoped Batch Event Dispatcher
                  │
                  ▼
Provider Adapter → Request/Attempt/Batch → Core Facts → Analytics
                  │
                  ▼
          Repository / Unit of Work / PostgreSQL
```

权威关系固定如下：

- catalog 是 provider 声明和 capability 的唯一权威源；
- routing 是 dataset/provider 选择策略的唯一权威源；
- factory/registry 是 adapter 构造的唯一入口；
- Dagster 是作业依赖和调度的唯一权威源；
- PipelineRun 与 raw/core/analytics 表是持久化运行事实；
- Event Dispatcher 仅传递已发生的批次结果，不参与重放和事实恢复。

## 4. 核心设计决策

### D1：建设深模块，不新增平行层

新增的 `ProviderRuntimeRegistry` 对调用方只暴露小接口：

```python
resolve(dataset, policy, settings) -> ResolvedProvider
describe(provider_key) -> ProviderDeclaration
```

其实现内部复用 catalog、routing 和既有 adapter 构造逻辑。调用方不再自己组合
“查能力 → 选 provider → 检查启用 → 构造 adapter”。首版不提供动态插件扫描、
运行时卸载、全局 singleton 或自动 fallback。

### D2：Application Engine 以用例为粒度

不设计万能 `MainEngine`。首个 Engine 只服务一个垂直切片：
`stock_daily_bars_by_trade_date`。

建议接口：

```python
execute(command: StockDailyBarsCommand) -> StockDailyBarsOutcome
```

Engine 负责：preflight、运行冲突检查、Provider 解析、主备执行、结果归类和
PipelineRun 终态；既有 ETL 服务继续负责 request/attempt/batch 与 Core facts。
Dagster Asset 只完成参数映射和 `Outcome → MaterializeResult` 转换。

### D3：事件必须通过“两消费者门禁”

只有同一批次结果已经存在至少两个独立消费者时才实现 Event Dispatcher，例如：

- PipelineRun/运行审计；
- Provider quality/可观测性聚合。

事件模型首版限定为：

- `ProviderBatchCompleted`；
- `ProviderBatchFailed`；
- `CoreFactsPublished`；
- `AnalyticsObservationPublished`；
- `PipelineRunCompleted`。

事件携带 ID、状态、数量、时间和安全错误摘要，不携带完整 payload、凭据或大型
领域对象。Dispatcher 同步执行、保持注册顺序、限定单次 Engine 执行范围；不使用
线程、异步队列、Redis、Kafka、RabbitMQ 或 outbox。

### D4：健康状态是派生视图，不是连接状态

我们的 Provider 多数是请求式 API 或离线文件源，不能照搬 vn.py 的
connected/disconnected。健康状态必须从最近 attempt、freshness、coverage、
consistency 派生，且标注 `as_of`；首版只返回查询值，不新增数据库表。

## 5. 分阶段实施

### Phase 0：4C 门禁与基线冻结

**依赖：** Stage 4C-MVP。

- 完成 4C 的 Repository/UoW、PostgreSQL round-trip、跨源一致性、replay 和
  Checkpoint B；
- 记录基线测试命令、关键 Asset metadata、CLI JSON 和 `ops.pipeline_runs` 行为；
- 新增 ADR，冻结本文第 3、4 节的权威关系和非目标。

**验收：** 4C 已由用户确认关闭；工作树中不存在未归属的 4C 实现改动；ADR 已通过评审。

### Phase 1：Provider Runtime Registry

- 先用 characterization tests 固定 catalog、routing、factory 的现有行为；
- 实现 Registry，但内部仍调用既有选择和构造函数；
- 迁移一个调用点：`stock_daily_bars_by_trade_date`；
- 保留旧 factory 入口作为兼容适配器，不一次性迁移所有 Asset/CLI。

**验收：**

- provider key、能力、显式启用、凭据错误和 TDX fallback 行为不变；
- fixture/Tushare/TDX 测试证明选择结果与迁移前一致；
- 未声明能力、禁用 provider、缺失凭据均 fail-closed；
- 无 migration、无外部网络测试依赖。

**回滚：** 恢复单个调用点直接使用 factory；删除无调用方的 Registry。

### Phase 2：Stock Daily Application Engine

- 从现有 Asset/CLI 中抽取 command、outcome 和 Engine；
- 使用现有 PipelineRun 状态与 Repository，不新增状态枚举；
- 外部 Provider 调用不得包在长期数据库事务中；
- 首先迁移 Dagster stock daily Asset，稳定后再迁移对应手工入口；
- 对重复运行、主源失败、fallback、partial、stale、未知规则建立合同测试。

**验收：**

- 同一输入下 raw/core/analytics 内容哈希及 Asset metadata 与基线一致；
- duplicate、failed、partial、succeeded 的 PipelineRun 行为可重复验证；
- 主源失败且 fallback 禁用时不伪造成功；
- Engine 单测不启动 Dagster，不连接真实 Provider。

**回滚：** Asset 切回原服务调用；新 Engine 无持久化结构，可整体删除。

### Phase 3：Provider Health 派生查询

- 基于既有 attempts、quality、freshness 和 consistency 能力构建只读快照；
- 先供 Engine preflight 与日志/metadata 使用，不立即增加 API/UI；
- 明确 `unknown`、`disabled`、`stale`、`degraded`、`healthy` 的派生规则和
  `as_of` 语义。

**验收：** 固定 fixture 可确定性重算；空历史返回 unknown；单次失败不覆盖历史证据；
不新增表、不改变 provider selection。

**回滚：** 移除 preflight 查询，恢复原门禁；无数据回滚。

### Phase 4：批次事件（条件实施）

**进入条件：** 同一事件至少存在两个已批准、可测试的消费者；否则本阶段取消。

- 实现最小同步 Dispatcher 与冻结事件合同；
- 从 Stock Daily Engine 一个垂直切片发出事件；
- 订阅者失败策略固定为：关键订阅者使运行失败，非关键订阅者只记录安全告警；
- 明确事件发生在 commit 前还是 commit 后，测试不得允许“回滚数据却发布成功事件”。

**验收：** 顺序、重复订阅、订阅者异常、事务回滚、敏感信息脱敏测试通过；关闭
Dispatcher 后业务结果与基线一致。

**回滚：** 通过配置/构造注入 No-op Dispatcher，再删除事件接线；数据库不变。

### Phase 5：逐用例扩展与旧接线清理

- 只有 Stock Daily Engine 达到稳定门槛后，才评审是否迁移 ETF daily、
  Market Breadth、Limit Sentiment 或 Research；
- 每次只迁移一个垂直切片，保留相同行为基线和独立回滚提交；
- 当所有既有调用方迁移完成后，才删除旧 factory 分支或重复 lifecycle helper。

**验收：** 每个切片独立提交、独立测试、独立回滚；禁止“大爆炸”式重构。

## 6. 项目级 Definition of Done

- Stage 4C 验收没有被本计划修改或阻塞；
- catalog/routing/registry 不存在第二份 provider/capability 权威清单；
- Dagster 仍是唯一作业图与调度器；
- Engine 不直接包含 SQLAlchemy、Dagster 或 Provider SDK 细节；
- raw request/attempt/batch、provenance、revision 和 fail-closed 语义保持不变；
- 不引入 vn.py、消息队列、线程事件循环或交易模型；
- focused tests、全量测试、Ruff、架构检查、`git diff --check` 通过；
- PostgreSQL 相关切片完成 upgrade/downgrade/round-trip/replay；
- 用户在每个 Checkpoint 后审核，未审核不得进入下一阶段。

## 7. 风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| 把 Engine 做成万能上帝对象 | 高 | 首版仅 Stock Daily 用例；接口只有 `execute` |
| catalog/registry/factory 三份权威 | 高 | Registry 只能消费 catalog/routing；characterization tests 防漂移 |
| Event 与数据库事实不一致 | 高 | 明确 commit 时序；事件只引用持久化 ID；回滚测试 |
| 事件总线被演化成隐藏调度器 | 高 | 同步、run-scoped、无线程/队列；Dagster 仍是唯一调度器 |
| 健康状态误导为实时连接状态 | 中 | 使用 as_of 和派生证据；无证据返回 unknown |
| 4C 收口被架构重构打断 | 高 | Phase 0 硬门禁；4C 关闭前禁止实现 Phase 1 |
| 一次迁移全部入口导致回归面过大 | 高 | 单垂直切片、兼容入口、每阶段独立回滚 |

## 8. 明确非目标

- 不实现订单、成交、持仓、账户、风控、撮合、策略执行或交易 Gateway；
- 不复制 vn.py 的类名、代码结构或线程事件循环；
- 不新增 Provider、ProviderCapability 或数据源 SDK；
- 不引入 Redis、Kafka、RabbitMQ、NATS、Celery、微服务或 outbox；
- 不替换 Dagster、不另建 scheduler；
- 不新增 Dashboard/UI、回测、分钟线、Tick、Level-2；
- 不在本计划内扩展 ResearchEvidenceBundle；
- 不以架构优化名义修改 4C 的数据规则或分析指标。

## 9. 评审决策点

实施前需要用户逐项确认：

1. 是否接受“4C 关闭后再实施”的硬门禁；
2. 是否同意首个垂直切片仅选择 Stock Daily；
3. 是否同意 Event Phase 采用“两消费者门禁”，条件不满足则取消；
4. Phase 1 详细设计和 ADR 通过后，是否授权进入代码实现。
