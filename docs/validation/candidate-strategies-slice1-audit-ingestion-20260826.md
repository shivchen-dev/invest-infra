# 候选策略 MVP Slice 1 / StrategyAudit 摄取记录

> 验收日期：2026-08-26
> 权威计划：`docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md`
> 阶段结论：两份审计已正式摄取；两条策略均需修订，Gate B 未通过

## 1. AgentOA 交付

- 项目：`prj_eef526e12a12b6f4`
- 工作流：`ses_2ffc955ae9d8c187`
- RAA：`agt_da9c59be9add6176`
- 两条任务均完成一次执行并交付 JSON/Markdown；AgentOA 完成仅代表交付完成。

## 2. 投研系统正式摄取

数据库已迁移至 `20260826_0022`。受控 CLI 分别校验 Draft、策略 artifact hash、AgentOA task、RAA 身份、JSON artifact hash、Markdown artifact hash、报告引用与审计时间后登记：

| 策略 | task_id | audit_id | verdict |
|---|---|---|---|
| 板块强度 | `tsk_75cab57292fb4e66` | `02176a14-2340-40fb-92f9-47f5caa9cc47` | `changes_required` |
| 通达信个股筛选 | `tsk_827b191a0f94c390` | `9c8c262f-1e9c-4e32-b8b9-495a156af51a` | `changes_required` |

重复摄取两条记录均返回原 `audit_id` 且 `idempotent=true`。

## 3. API 读回

一次性本地 API 实例通过 `GET /api/v1/strategy-drafts/{draft_id}` 读回：

- 每条 Draft 恰有一条 `audit_summaries`；
- `audit_id`、`artifact_hash`、`verdict`、`audited_at` 与正式摄取记录一致；
- 两条 verdict 均为 `changes_required`；
- 验收实例完成后已停止。

## 4. 验证

- StrategyAudit domain：`57 passed`；
- StrategyAudit storage/migration：`42 passed`；
- StrategyAudit ingestion CLI：`14 passed`；
- StrategyDraft audit-summary API：`39 passed`；
- Ruff、架构检查、`git diff --check`：通过。

## 5. 当前决定

Gate B 未通过。`changes_required` 审计不能用于发布或激活 `StrategyVersion`。下一步必须由 CIA 对 RAA findings 作业务决定，并形成新的不可变策略 artifact 与新 Draft；ARC 不得直接修改当前 Draft 或代替 CIA 调整策略语义。

## 6. 回测范围修正

用户于 2026-08-27 明确决定：当前策略不做回测，系统也不建设回测模块。CIA 整改 artifact 中标记为 `needs_human_decision` 的回测区间、样本量、收益指标和回测通过阈值不再构成整改项或发布门禁。

后续 RAA 复审只验证规则可执行性、数据字段与口径、无未来数据、可复算性、失败条件和证据边界。StrategyVersion 的发布或激活只代表允许按已批准规则受控执行，不代表策略收益经过验证。
