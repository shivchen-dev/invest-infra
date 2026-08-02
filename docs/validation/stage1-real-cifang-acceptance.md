# Stage 1 — 真实 CifangQuant 验收记录（脱敏模板）

> 文档版本：v0.1（待真实运行后逐项填写）
> 适用范围：Stage 1 Closure → Stage 2 自动运行前的真实 CifangQuant 冒烟验收。
> 参考：ADR-0011 §2 / §3 / §4、ADR-0010 §5 / §6、
> `docs/plan/invest-infra-v2-stage2-automation-stability-plan-no-matrix.md` §5.4。
> ADR-0011 状态：**保持 Proposed**。本记录**不构成**对 §4 阻塞项的解除；
> 仅记录一次真实网络冒烟的可核验事实摘要。

---

## 0. 验收授权与待办（明确未完成项）

下列项目是 Stage 2 启用真实 CifangQuant 自动 Schedule 的前置条件。**任何一项
未勾选，本表不得填入真实数字**；仅允许以 `PENDING` 形式留空，Stage 2 影子
运行不得因此自动开启。

- [ ] 个人使用授权已获取（CifangQuant 控制台账户有效）。
- [ ] API 访问方式已确认（端点 `https://www.cifangquant.com/api` 可达）。
- [ ] 基本限频与 5xx 重试预算的官方数值已记录在 ADR-0011 §4 表中。
- [ ] `adjustment=none` 的官方语义证据已归档（与 M0 ADR-0005 一致）。
- [ ] 凭据通过 **环境变量** 注入（`INVEST_PIPELINE_CIFANG_API_KEY`），
      仓库、CI、`uv.lock`、fixture、commit 中**均无明文 Key**。
- [ ] 自动运行频率不超过官方限频配额。
- [ ] ADR-0011 状态已通过新 ADR 升级为 `Accepted for personal deployment`
      （未完成前保持 `Proposed`）。

---

## 1. 运行环境与提交

| 项 | 值 | 备注 |
|---|---|---|
| 验收提交 SHA | `PENDING — 待真实运行后填写` | `git rev-parse HEAD` 输出 |
| 执行时间（Asia/Shanghai） | `PENDING` | ISO `YYYY-MM-DDTHH:MM:SS+08:00` |
| 业务交易日 | `PENDING` | ISO `YYYY-MM-DD`，需为周一至周五 |
| Provider Key | `cifangquant` | 与 ADR-0011 §1 一致 |
| 注入方式 | 环境变量 `INVEST_PIPELINE_CIFANG_API_KEY` | 不打印明文 |
| 复权参数 | `none` | 锁死，不允许 `qfq` / `hfq` |
| 真实 CifangQuant API Key | `***` | 仅在本表以 `***` 表示，禁止明文 |
| 执行命令 | `make personal-daily-run TRADE_DATE=<YYYY-MM-DD> CONFIRM_NETWORK=1` | 来自 `Makefile:134` |

> 不得记录：API Key 明文、`x-api-key` 请求头、原始响应体、敏感 URL 参数
> （token / signature / 完整 query string）。

---

## 2. Provider 抓取摘要

| 项 | 值 | 备注 |
|---|---|---|
| 主数据 ETF 数量 | `PENDING` | `/api/fund/list` 返回并通过 mapper 落库的 `Instrument` 行数 |
| 个人 ETF 池数量（Universe） | `PENDING` | 与 `INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH` 行数一致 |
| 日行情数量 | `PENDING` | `core.daily_bars` 当日新增行数 |
| `raw.provider_requests` 行数 | `PENDING` | 主数据 + 日行情请求 |
| `raw.provider_attempts` 成功行数 | `PENDING` | 含 `request_key` / `attempt_no` |
| `raw.provider_batches` 成功行数 | `PENDING` | 不写 `request_id`（供应商未给时） |
| `ProviderBatch.request_id` 是否回写 | `PENDING` | 仅当供应商响应中给出 |

---

## 3. 业务结果摘要

| 项 | 值 | 备注 |
|---|---|---|
| `analytics.input_snapshots` Snapshot ID | `PENDING` | 当日 `binding_hash` 校验通过 |
| Snapshot `row_count` | `PENDING` | 与 Universe 行数一致 |
| Candidate Pool Run ID | `PENDING` | 当日 `published` Run |
| Candidate Pool `status` | `published` | 仅当真实 CifangQuant 验收通过 |
| Included 数量 | `PENDING` | `candidate_pool_items.status=included` |
| Excluded 数量 | `PENDING` | `candidate_pool_items.status=excluded` |
| `included + excluded` 是否等于 `universe_count` | `PENDING` | 必须相等 |

---

## 4. 同日第二次运行（幂等校验）

| 项 | 值 | 备注 |
|---|---|---|
| 第二次执行命令 | `make reprocess-date TRADE_DATE=<YYYY-MM-DD> CONFIRM_NETWORK=1` | 来自 `Makefile:143` |
| `core.daily_bars` 新增 revision 数 | `PENDING — 预期 0` | 幂等，不增加新 revision |
| Candidate Pool Run 新增数 | `PENDING — 预期 0` | 相同自然键不重复创建 |
| `pipeline_runs` 当日记录数 | `PENDING` | 不应增长 |
| `GET /api/v1/pipeline-runs/latest` `run_id` | `PENDING` | 应仍指向首次 Run |

---

## 5. API 摘要（脱敏后）

| 端点 | 关键字段 | 值 |
|---|---|---|
| `GET /api/v1/pipeline-runs/latest` | `partition_key` / `status` / `error_code` / `error_summary` | `PENDING` |
| `GET /api/v1/data-freshness` | `latest_published_trade_date` / `universe_count` / `daily_bar_count` / `missing_count` / `status` | `PENDING` |
| `GET /api/v1/candidate-pool/latest` | `run_id` / `included_count` / `excluded_count` | `PENDING` |

> 任何 `error_code` / `error_summary` 字段不得回显 API Key、请求头、原始响应体。

---

## 6. 验收结论

| 项 | 结论 |
|---|---|
| 主数据链与日行情落库 | `PENDING` |
| Snapshot / Candidate Pool 发布 | `PENDING` |
| 同日重跑幂等 | `PENDING` |
| 凭据脱敏（Key 仅以 `***` 出现） | `PENDING` |
| ADR-0011 §4 阻塞项解除 | `PENDING — 本次记录不解除任何阻塞项` |
| ADR-0011 状态变更 | `不变。仍为 Proposed，待外部证据齐备后另起 ADR` |

---

## 7. 禁止记录项（再次声明）

- 任何形式的 API Key 明文 / 哈希 / 前缀。
- 任何 `x-api-key` 请求头原文。
- 任何 `/api/fund/list` / `/api/fund/hist_em` 原始响应体或可还原片段。
- 任何含 `token=` / `signature=` 的 URL 完整 query string。
- 任何个人 / 第三方账户标识符（控制台账户 ID 除外且需脱敏）。

---

## 8. 关联

- ADR-0011：`docs/adr/0011-cifangquant-primary-etf-provider.md`，**Status: Proposed**。
- 数据迁移矩阵：`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`。
- 真实冒烟脚本：`make provider-smoke`（`Makefile:107`，三重 opt-in）。
- Stage 2 影子日志：`docs/validation/stage2-shadow-run-log.md`。