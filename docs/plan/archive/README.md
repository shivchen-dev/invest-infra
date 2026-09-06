# 计划归档索引

本目录保存已退出当前执行面的历史计划和长期参考蓝图。归档表示“不得直接派工”，不表示内容被删除或全部实施。

## 目录

- `completed/`：已经完成、关闭或合并进现行计划的历史实施计划；不得从延期项恢复派工。
- `deferred/`：尚未激活或已暂停的未来计划；恢复前必须重新核对依赖并取得用户授权。
- `reference-blueprints/`：长期架构、未来阶段和历史设计基线；当前实施必须由 `docs/plan/README.md` 中登记的活动计划承接。

## 归档记录

| 原文件名 | 归档状态 | 当前承接文档 |
|---|---|---|
| `invest-infra-etf-data-coverage-resilience-plan-v1.0.md` | `CLOSED` | `docs/validation/etf-data-coverage-resilience-closure-20260902.md`；新缺陷另立目标 Dataset 切片 |
| `invest-infra-stage4a-final-closure-sprint-plan-v1.1.md` | `REFERENCE_HISTORY` | `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` |
| `invest-infra-stage4b-market-intelligence-foundation-plan.md` | `COMPLETED` | `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` |
| `invest-infra-stage4c-core-data-layer-integration-plan.md` | `COMPLETED_WITH_DEFERRED_ITEMS` | 延期项无当前承接，不自动恢复 |
| `invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md` | `MERGED_REFERENCE` | `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` |
| `invest-infra-central-research-visualization-mvp-plan-v1.0.md` | `DEFERRED` | 等待 Stage 4D Gate 3 与 Candidate lineage 验收后重新授权 |
| `invest-infra-decision-feedback-loop-mvp-plan-v1.0.md` | `DEFERRED_DRAFT` | 等待 Stage 4D Gate 3、Candidate lineage 与数据运行验收后重新授权 |
| `invest-infra-data-collection-enhancement-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | 新数据能力由目标 Dataset 计划按需承接 |
| `invest-infra-investment-context-provider-integration-plan.md` | `REFERENCE_BLUEPRINT` | 新 Provider/Evidence 能力由目标 Dataset 计划按需承接 |
| `invest-infra-stage4a0-multi-channel-dynamic-candidate-routing-plan.md` | `DEFERRED_REFERENCE` | `docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md` |
| `invest-infra-v2-all-data-sources-integration-plan.md` | `DEFERRED_REFERENCE` | 不执行全量接入；按目标 Dataset 独立授权 |
| `invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md` | `REFERENCE_BLUEPRINT` | `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`、`docs/plan/archive/deferred/invest-infra-central-research-visualization-mvp-plan-v1.0.md` |

## 使用规则

- 当前状态、优先级和派工入口以 `docs/plan/README.md` 为唯一权威；
- 归档文档可用于追溯架构理由，不得依据其中未完成章节直接恢复开发；
- 恢复归档计划必须重新形成活动计划、边界和用户授权；
- 移动或替代归档文档时，必须同步本索引和仓库内引用。
