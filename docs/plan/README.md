# invest-infra 计划目录与轻量治理规则

> 生效日期：2026-08-18
> 适用范围：`docs/plan/`

本目录是计划入口，不是动态进度表。每条活动主线只保留一份权威实施计划；计划定义目标、边界、依赖和验收标准，Git、CI 与真实验收记录定义实际完成事实。

`tasks/` 下的历史任务包和执行拆分文件不再作为派工、进度或完成状态权威，也不再要求维护。

## 1. 当前执行权威

同时只保留两条实施主线，未经用户明确授权不得从其他蓝图恢复派工：

| 优先级 | 主线 | 状态 | 唯一权威实施计划 |
|---|---|---|---|---|
| P0 | ETF 数据覆盖与 Provider 韧性 | `ACTIVE` | `invest-infra-etf-data-coverage-resilience-plan-v1.0.md` |
| P1 | Stage 4D 研究交付收口 | `ACTIVE` | `invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`；Gate 3 前置切片：`invest-infra-candidate-strategies-mvp-plan-v1.0.md` |

状态解释：

- `ACTIVE`：计划是当前有效实施边界；是否已授权、已实现或已验收，以对应证据为准；
- 两条主线共享现有只读查询能力，但不得在同一任务中混合开发。

## 2. 业务定位冻结

当前系统定位为证据驱动的投研辅助系统，重点是：

```text
真实市场数据
→ 市场观察
→ 研究判断
→ 策略迭代
→ 长期观察
→ 持仓纪律检查与复盘
```

当前明确不做：

- 任何回测模块、收益验证平台和参数寻优；
- 自动策略批准、激活或淘汰；
- 自动交易、下单和仓位调整；
- 通用 BI、通用流程设计器；
- 在业务合同冻结前为页面制造临时权威数据。

外部研究平台决策：

- JiuwenSwarm 因成熟度不足且更新缓慢，已停止采用；
- 当前活动计划不得再以 JiuwenSwarm 联调、升级或真实验收作为依赖或 Gate；
- 仓库中既有 JiuwenSwarm Adapter、测试和历史文档仅作为历史兼容事实保留，不代表继续建设承诺；
- Research Case、Evidence、Research Run/Result 等投研领域合同继续独立有效，后续研究执行能力必须另行评估和授权。

## 3. 计划文档状态

| 文档 | 治理状态 | 处理结论 |
|---|---|---|
| `invest-infra-etf-data-coverage-resilience-plan-v1.0.md` | `ACTIVE` | 当前 P0 数据层垂直切片；按“真实探针 → 准入决策 → 最小 Adapter”三阶段执行，不预建字段路由或覆盖平台 |
| `invest-infra-central-research-visualization-mvp-plan-v1.0.md` | `DEFERRED` | 数据覆盖与 Provider 韧性 P0 收口前暂停；不得与数据层切片混合实施 |
| `invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` | `ACTIVE` | 当前 Stage 4D 收口权威；只处理真实联调、剩余 Research Workspace 和最终验收 |
| `invest-infra-strategy-source-to-automation-workflow.md` | `CONTRACT_AUTHORITY` | 策略交付物和来源追溯的合同权威，不作为当前开发排期 |
| `invest-infra-candidate-strategies-mvp-plan-v1.0.md` | `ACTIVE` | Stage 4D Gate 3 前置切片；原文恢复、两条Draft审计发布、固定两阶段人工执行 |
| `archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | Stage 4D–4G 长期蓝图；保留原文件名和完整内容，不得直接从正文派工 |
| `invest-infra-data-collection-enhancement-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | 数据采集架构参考；不作为当前全量建设承诺 |
| `invest-infra-investment-context-provider-integration-plan.md` | `REFERENCE_BLUEPRINT` | Provider/Evidence 参考；新数据源按独立授权切片实施 |
| `invest-infra-stage4a-final-closure-sprint-plan-v1.1.md` | `REFERENCE_HISTORY` | Stage 4A 历史收口依据，不再派工 |
| `invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md` | `DEFERRED` | 候选策略合同重新冻结前不实施 |
| `invest-infra-stage4b-market-intelligence-foundation-plan.md` | `COMPLETED` | 既有实现和验收记录已完成；保留为实现依据 |
| `invest-infra-stage4c-core-data-layer-integration-plan.md` | `COMPLETED_WITH_DEFERRED_ITEMS` | MVP 已验收；延期项不自动进入当前主线 |
| `invest-infra-v2-all-data-sources-integration-plan.md` | `DEFERRED` | 不执行“大而全”数据源接入；按真实研究问题单独授权 |
| `invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md` | `MERGED_REFERENCE` | 已完成合同和实现事实保留；剩余接入并入 Stage 4D 收口 |

## 4. 动态事实来源

本索引不维护开发进度。动态事实按以下来源判断：

- 代码实现：Git commit 和工作树；
- 自动验证：CI、测试、构建、类型和架构检查结果；
- 真实验收：独立验收记录；
- 授权与范围变化：用户明确决定或治理决策记录。

提交代码或测试通过，不自动等于阶段验收完成；计划状态也不由历史任务清单决定。

## 5. 文档变更规则

### 5.1 新计划准入

新增实施计划前必须确认：

- 不能作为现有两条主线的垂直切片；
- 有清晰输入、输出、非目标和验收 Gate；
- 在本索引登记治理状态；
- 明确它替代、合并或依赖哪些旧计划。

### 5.2 状态迁移

```text
DRAFT
→ ACTIVE
→ CLOSED

ACTIVE
→ DEFERRED
→ ACTIVE（重新授权后）

任意状态
→ MERGED_REFERENCE / REFERENCE_HISTORY
```

活动计划完成必须有测试、构建、真实验收或明确关闭记录；不能只因历史执行记录存在而完成。

### 5.3 归档规则

- 活动计划留在 `docs/plan/`，历史和长期参考按状态移入 `docs/plan/archive/`；
- `REFERENCE_HISTORY`、`COMPLETED`、`MERGED_REFERENCE` 在工作树干净后可进行独立归档批次；
- 归档必须保留本索引中的原文件名、最终状态、替代文档和 commit；
- 不删除历史设计，不把历史蓝图重新解释为当前承诺。

## 6. 当前开放合同

以下内容是待冻结合同，不是已排期功能：

| 合同 | 当前状态 | 触发条件 |
|---|---|---|
| `strategy-iteration` | `OPEN_CONTRACT` | 中心平台 Slice 0–3 验收后，用户独立授权 |
| `position-discipline` | `OPEN_CONTRACT` | 确认实际持仓事实权威源后，用户独立授权 |

## 7. OpenWiki 与计划治理

OpenWiki 是展示层，不是计划或派工权威。它可以展示计划、代码、测试和验收事实，但不自行决定计划状态，也不产生第二份执行计划。

## 8. 维护检查

每次计划变化必须同步检查：

- 当前执行计划页首状态；
- 被合并/延期计划是否仍被其他文档称为执行权威；
- README 是否仍指向有效计划索引。
