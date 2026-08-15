# invest-infra 计划治理索引

> 索引版本：v1.0
> 生效日期：2026-08-15
> 适用范围：`docs/plan/` 与 `tasks/`
> 状态权威：当旧文档页首状态、正文顺序或 Todo 与本索引冲突时，以本索引为准。

## 1. 当前执行权威

同时只保留两条实施主线，未经用户明确授权不得从其他蓝图恢复派工：

| 优先级 | 主线 | 状态 | 计划 | 执行清单 |
|---|---|---|---|---|
| P0 | Stage 4D 研究交付收口 | `ACTIVE_CLOSEOUT` | `invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` | `tasks/stage4d-mvp-phased-execution-todo.md` |
| P1 | 中心投研可视化平台 MVP | `ACTIVE_PLAN` | `invest-infra-central-research-visualization-mvp-plan-v1.0.md` | `tasks/central-research-visualization-mvp-todo.md` |

状态解释：

- `ACTIVE_CLOSEOUT`：只完成已定义链路的剩余联调、验收和文档收口，不扩张范围；
- `ACTIVE_PLAN`：计划已形成，代码开发仍须用户显性授权；
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

- 复杂回测平台和参数寻优；
- 自动策略批准、激活或淘汰；
- 自动交易、下单和仓位调整；
- 通用 BI、通用流程设计器；
- 在业务合同冻结前为页面制造临时权威数据。

## 3. 计划文档状态

| 文档 | 治理状态 | 处理结论 |
|---|---|---|
| `invest-infra-central-research-visualization-mvp-plan-v1.0.md` | `ACTIVE_PLAN` | 当前可视化执行方案；Slice 0–3 为 MVP，Slice 4–5 独立冻结合同和授权 |
| `invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` | `ACTIVE_CLOSEOUT` | 当前 Stage 4D 收口权威；只处理真实联调、剩余 Research Workspace 和最终验收 |
| `invest-infra-strategy-source-to-automation-workflow.md` | `CONTRACT_AUTHORITY` | 策略交付物和来源追溯的合同权威，不作为当前开发排期 |
| `invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | Stage 4D–4G 长期蓝图；不得直接从正文派工 |
| `invest-infra-data-collection-enhancement-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | 数据采集架构参考；不作为当前全量建设承诺 |
| `invest-infra-investment-context-provider-integration-plan.md` | `REFERENCE_BLUEPRINT` | Provider/Evidence 参考；新数据源按独立授权切片实施 |
| `invest-infra-stage4a-final-closure-sprint-plan-v1.1.md` | `REFERENCE_HISTORY` | Stage 4A 历史收口依据，不再派工 |
| `invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md` | `DEFERRED` | 候选策略合同重新冻结前不实施 |
| `invest-infra-stage4b-market-intelligence-foundation-plan.md` | `COMPLETED` | Todo 已全部完成；保留为实现依据 |
| `invest-infra-stage4c-core-data-layer-integration-plan.md` | `COMPLETED_WITH_DEFERRED_ITEMS` | MVP 已验收；延期项不自动进入当前主线 |
| `invest-infra-v2-all-data-sources-integration-plan.md` | `DEFERRED` | 不执行“大而全”数据源接入；按真实研究问题单独授权 |
| `invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md` | `MERGED_REFERENCE` | 已完成合同和实现事实保留；剩余接入并入 Stage 4D 收口 |

## 4. 任务包状态

所有任务包的具体状态以 `tasks/README.md` 为准。旧 Todo 中未勾选项目不自动代表当前待办；必须同时满足：

1. 所属计划状态允许派工；
2. 未被更高层计划合并、延期或替代；
3. 有当前用户授权；
4. 代码、测试、提交和真实环境验收尚未证明完成。

## 5. 文档变更规则

### 5.1 新计划准入

新增实施计划前必须确认：

- 不能作为现有两条主线的垂直切片；
- 有清晰输入、输出、非目标和验收 Gate；
- 同时建立一份 Todo；
- 在本索引登记治理状态；
- 明确它替代、合并或依赖哪些旧计划。

### 5.2 状态迁移

```text
DRAFT
→ ACTIVE_PLAN
→ ACTIVE / ACTIVE_CLOSEOUT
→ COMPLETED

ACTIVE_PLAN / ACTIVE
→ DEFERRED
→ ACTIVE（重新授权后）

任意状态
→ MERGED_REFERENCE / REFERENCE_HISTORY
```

`COMPLETED` 必须有测试、构建、真实验收或明确关闭记录；不能只因 Todo 被勾选而完成。

### 5.3 归档规则

- 本轮不移动已有计划：当前工作树存在未提交的 Stage 4D 文档和实现，移动会破坏引用和审计链；
- `REFERENCE_HISTORY`、`COMPLETED`、`MERGED_REFERENCE` 在工作树干净后可进行独立归档批次；
- 归档必须保留本索引中的原文件名、最终状态、替代文档和 commit；
- 不删除历史设计，不把历史蓝图重新解释为当前承诺。

## 6. 当前开放合同

以下内容是待冻结合同，不是已排期功能：

| 合同 | 当前状态 | 触发条件 |
|---|---|---|
| `strategy-iteration` | `OPEN_CONTRACT` | 中心平台 Slice 0–3 验收后，用户独立授权 |
| `position-discipline` | `OPEN_CONTRACT` | 确认实际持仓事实权威源后，用户独立授权 |

## 7. 维护检查

每次计划变化必须同步检查：

- 本索引与 `tasks/README.md`；
- 当前执行计划页首状态；
- 被合并/延期计划是否仍被其他文档称为执行权威；
- Todo 是否把历史未勾选项误报为当前任务；
- README 是否仍指向有效计划索引。
