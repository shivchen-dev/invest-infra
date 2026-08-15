# invest-infra 任务治理索引

> 生效日期：2026-08-15
> 上位权威：`docs/plan/README.md`
> 规则：本索引决定任务包能否派工；原 Todo 保留细节和历史勾选状态。

## 当前可执行

| 工作包 | 状态 | 可执行范围 |
|---|---|---|
| `stage4d-mvp-phased-execution-*` | `ACTIVE_CLOSEOUT` | 3.5–3.9 的真实联调、Research Workspace/Timeline、E2E 与 Gate 3 收口；执行前按代码事实校准清单 |
| `central-research-visualization-mvp-*` | `ACTIVE_PLAN` | 当前仅计划审核；代码开发须再次获得用户显性授权 |

## 已完成，不再派工

| 工作包 | 状态 | 证据口径 |
|---|---|---|
| `stage4b-market-intelligence-foundation-*` | `COMPLETED` | Todo 28/28 完成 |
| `strategy-artifact-ingestion-archive-mvp-*` | `COMPLETED` | Todo 34/34 完成；测试、正式重放和验收记录已完成 |
| `plan-tdx-production-fallback.md` + `todo-tdx-production-fallback.md` | `COMPLETED` | Todo 6/6 完成 |

## 合并到当前主线

| 工作包 | 状态 | 承接关系 |
|---|---|---|
| `stage4d-workbuddy-research-delivery-*` | `MERGED_REFERENCE` | 合同、摄取和真实研究剩余项并入 `stage4d-mvp-phased-execution-*`；不得双重派工 |
| `workbuddy-daily-report-governance-mvp-*` | `MERGED_RESIDUAL` | 剩余真实样本/接入项由 Stage 4D 收口判定是否仍需执行 |

## 延期或待合同冻结

| 工作包 | 状态 | 重新启动条件 |
|---|---|---|
| `stage4d-strategy-library-workflow-*` | `DEFERRED_CONTRACT` | 先冻结轻量策略迭代合同；旧 S0–S7 不整体启动 |
| `candidate-pool-strategy-rebuild-*` | `DEFERRED_CONTRACT` | 候选策略身份、版本和交付合同经用户审核 |
| `stage4c-core-data-layer-integration-*` | `COMPLETED_WITH_DEFERRED_ITEMS` | MVP 已验收；6 个延期项按真实研究需求独立授权 |
| `data-source-integration-todo.md` | `DEFERRED_SLICE` | 最后 1 项不阻塞当前投研主线 |
| `hithink-reserved-provider-*` | `DEFERRED_SLICE` | 真实数据缺口要求启用 HiThink 时再授权 |
| `stage4c-block-strength-screening-branch.md` | `REFERENCE_BRANCH` | 不作为独立派工入口 |

## 清单校准规则

- `[ ]` 只表示原清单未勾选，不自动表示“当前待办”；
- `ACTIVE_CLOSEOUT` 工作开始前，必须用代码、测试、git 历史和真实验收逐项校准；
- 被标记为 `MERGED_*` 的任务只能在承接清单中更新；
- `DEFERRED_*` 不参与当前进度统计；
- 完成任务必须同时记录验证命令和验收结果；
- 不通过修改历史 Todo 来伪造当时进度。

## 当前统计口径

```text
执行主线：2
  ACTIVE_CLOSEOUT：1
  ACTIVE_PLAN：1

已完成工作包：3
合并参考工作包：2
延期/待合同工作包：6
```
