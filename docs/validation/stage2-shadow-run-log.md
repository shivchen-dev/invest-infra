# Stage 2 — 影子运行日志（10 个交易日模板）

> 文档版本：v0.1（待真实运行后逐日填写）
> 适用范围：Stage 2 关闭期，`personal_etf_daily_schedule` 默认关闭
> （`INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false`），仅由运维手工按日触发
> `make personal-daily-run TRADE_DATE=YYYY-MM-DD` 或 `make reprocess-date`，
> 不发送通知，不接入 Matrix。
> 通过条件：连续 ≥ 10 个交易日，自动运行成功率 ≥ 90%、失败日期全部可补跑、
> 无同日并发重复发布、无相同内容 revision 增长、无凭据泄漏
> （`docs/plan/invest-infra-v2-stage2-automation-stability-plan-no-matrix.md` §9.7）。
> ADR-0011 状态：**保持 Proposed**。本日志**不构成**对 ADR-0011 §4 阻塞项
> 的解除；状态变更必须另起 ADR。

---

## 0. 允许记录的字段（白名单）

仅允许从下列字段取值填入下方表格；任何字段取值不得回显凭据、个人身份、
请求头、原始响应或可还原 URL 参数。

- `日期`（Asia/Shanghai，ISO `YYYY-MM-DD`，交易日，周一至周五）。
- `Run 状态`（`succeeded` / `failed` / `skipped` / `running`，与
  `pipeline_runs.status` 一致）。
- `标的数`（`universe_count`，来自 `GET /api/v1/data-freshness`）。
- `行情数`（`daily_bar_count`，来自 `GET /api/v1/data-freshness`）。
- `候选数`（`candidate_pool_items.included_count`，
  来自 `GET /api/v1/candidate-pool/latest`）。
- `缺失`（`missing_count`，来自 `GET /api/v1/data-freshness`）。
- `是否补跑`（`是 / 否 / N/A`，对应当日是否触发
  `make reprocess-date TRADE_DATE=<date>`）。
- `备注`（≤ 1 行；只引用 `error_code` / `pipeline_run_id` 等已知 ID，
  不贴日志原文）。

## 0.1 禁止记录的字段（黑名单）

下列内容**任何形式**不得进入本文件、相关 commit、附属 fixture、附件：

- `INVEST_PIPELINE_CIFANG_API_KEY` 任何形式的明文 / 哈希 / 前缀。
- `x-api-key` 请求头原文。
- `/api/fund/list` / `/api/fund/hist_em` 原始响应体或可还原片段。
- 任何 `token=` / `signature=` URL 完整 query string。
- 任何个人 / 第三方账户标识符（控制台账户 ID 除外且需脱敏）。
- 含个人投资偏好、金额、持仓的明细字段。

---

## 1. 10 个交易日影子运行记录

> 填写约定：交易日按发生顺序由运维每日追加一行；每行不得修改历史日期
> 的取值，仅允许追加 `补跑后` 行（同样 10 个交易日窗口内）。
> `PENDING` 表示当日尚未运行，禁止用历史 / 推测数字预填。

| # | 日期 | Run 状态 | 标的数 | 行情数 | 候选数 | 缺失 | 是否补跑 | 备注 |
|---:|---|---|---:|---:|---:|---:|---|---|
| 1 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 2 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 3 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 4 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 5 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 6 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 7 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 8 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 9 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |
| 10 | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `PENDING` | `否` | `PENDING` |

> 若任一日进入“补跑”流程，请在原日下方追加一行 `补跑后`，保留原行不变，
> 并在 `备注` 中记录 `pipeline_run_id` 与 `error_code`（仅 ID，不贴原文）。

---

## 2. 每日抽检命令（仅引用白名单输出，不打印 Key）

```bash
curl -sS http://localhost:8000/api/v1/pipeline-runs/latest | python -m json.tool
curl -sS http://localhost:8000/api/v1/data-freshness            | python -m json.tool
curl -sS http://localhost:8000/api/v1/candidate-pool/latest    | python -m json.tool
```

每条命令的输出都不得含明文 `api_key` / `x-api-key` / 完整 query string；
若出现，立即按 ADR-0010 §5 / §6 走轮换流程并清空本行。

---

## 3. 阶段指标（10 日窗口）

| 指标 | 目标 | 当前 | 状态 |
|---|---|---|---|
| 自动运行成功率 | ≥ 90% | `PENDING` | `PENDING` |
| 失败日期全部可补跑 | 100% | `PENDING` | `PENDING` |
| 同日并发重复发布 | 0 | `PENDING` | `PENDING` |
| 相同内容 revision 增长 | 0 | `PENDING` | `PENDING` |
| 凭据泄漏事件 | 0 | `PENDING` | `PENDING` |
| 数据新鲜度状态与实际一致 | 100% | `PENDING` | `PENDING` |
| API 可查询每次 Run | 100% | `PENDING` | `PENDING` |
| 10 日内 `published` 日数 | ≥ 9 | `PENDING` | `PENDING` |

---

## 4. 关联与未变更状态

- ADR-0011：`docs/adr/0011-cifangquant-primary-etf-provider.md`，**Status: Proposed**，
  本文件**不改变**其状态；解除阻塞须另起 ADR。
- Stage 1 验收脱敏模板：`docs/validation/stage1-real-cifang-acceptance.md`。
- 鉴权失败 Runbook：`docs/runbooks/cifang-auth-failure.md`。
- 交易日补跑 Runbook：`docs/runbooks/reprocess-trade-date.md`。
- 阶段通过条件：
  `docs/plan/invest-infra-v2-stage2-automation-stability-plan-no-matrix.md` §9.7。