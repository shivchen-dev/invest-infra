# 候选策略 MVP Slice 0 / Gate A 验收记录

> 验收时间：2026-08-26T22:31:18+08:00
> 权威计划：`docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md`
> 结论：`PASS`

## 1. 源文与既有交付核验

| 策略 | 当前正文 SHA-256 | 归档 SHA-256 | 结果 |
|---|---|---|---|
| 板块强度 | `96de35b1ad1a2de8f10894694cdf831d192ac765bf6dd6206ba178e071f18a7f` | 同左 | 一致 |
| 通达信个股筛选 | `9bfc0693419f56450c64c66a051d5c0687f0e961d79fb551db85ff6efc0fb52c` | 同左 | 一致 |

两套工程化归档各 14 个 manifest entry 均重新计算 size 与 SHA-256，结果全部一致。没有覆盖旧源文身份，也不需要 CIA 处理网页内容漂移。

## 2. 正式 Draft 登记

数据库已由 Alembic `20260814_0020` 升级至 `20260826_0021`。CLI 对 manifest、源文精确字节、strategy/validation/capability 绑定及 artifact hash 校验通过后，将不可变文件固化到受控 artifact 根目录并登记 Draft。

| strategy_key | proposed_version | draft_id | artifact_hash |
|---|---|---|---|
| `sector-strength-ranking` | `1.0.0` | `f184c306-220c-41f9-8ae8-8f7b540d619c` | `7d732bd4ca93bbde23704d14fc6f36952dfb8e9baffb433f1bb8597bada6fd97` |
| `tdx-native-tools-stock-screening` | `1.0.0` | `7afa3bc7-0d20-43cb-9a3d-5bda2c571623` | `dd043c5457073eaca0f9eed716af60e247a73376a03eaa8a6c399a614942fce9` |

## 3. 真实 API 读回

通过一次性本地验收实例调用 `GET /api/v1/strategy-drafts/{draft_id}`，两条 Draft 均返回 HTTP 200，并满足：

- `strategy.status=needs_review`；
- `validation_result.validation.status=passed`；
- `validation_result.manifest.verified=true`；
- 每条返回 3 个带 hash 的 source ref；
- artifact hash 与登记值一致；
- 不返回 `artifact_ref`、`task_source`、POSIX/Windows/UNC/file URI 宿主机路径；
- 当前 `audit_summaries=[]`，符合尚未进入 Slice 1 的状态。

验收实例使用端口 8001，完成读回后已停止；未重启或影响端口 8000 的既有服务。

## 4. 自动化验证

- StrategyDraft API、查询服务、受控 artifact reader：`38 passed`；
- StrategyDraft 登记 CLI：`8 passed`；
- Ruff：通过；
- 架构边界检查：通过；
- `git diff --check`：通过。

## 5. Gate A 决定

Slice 0 验收条件全部满足。下一步只能进入 Slice 1：分别通过 AgentOA 向 RAA 派发两条只读审计任务；在有效 `pass` 审计被摄取且 CIA 明确批准前，不得发布或激活 `StrategyVersion`。
