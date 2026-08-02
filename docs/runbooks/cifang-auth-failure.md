# Runbook — CifangQuant 鉴权失败（401 / 403）

> 适用范围：`INVEST_PIPELINE_PROVIDER_KEY=cifangquant` 真实网络模式。
> 参考：ADR-0010 §5 / §6、ADR-0011 §3 / §4。
> 触达面：`make provider-smoke`、`make personal-daily-run`、`make reprocess-date`、
> `make personal-backfill`，以及 Dagster `personal_etf_daily_schedule` 自动运行。
> 默认不会泄漏 API Key：`CifangSettings.api_key` 为 `SecretStr`，`__repr__` 渲染为 `***`
> （`apps/pipeline/src/invest_pipeline/adapters/cifang/config.py:51`）。本 runbook 不打印真实 Key。

## 症状

- 日志 / API 出现 `ProviderAuthenticationError` 或
  `HTTP 401 (authentication rejected)` / `HTTP 403 (authentication rejected)`
  （`apps/pipeline/src/invest_pipeline/adapters/cifang/client.py:382`）。
- `apps/pipeline/src/invest_pipeline/personal_daily_cli.py` 的 exit code 非零，
  `error_summary` 含 `authentication rejected` / `auth`。
- 自动 Schedule：`GET /api/v1/pipeline-runs/latest` 返回
  `status=failed`、`error_code` 非空、`error_summary` 含上述字样。
- `GET /api/v1/data-freshness` 返回 `status=failed`，
  `pipeline_status=failed`、`pipeline_run_id` 指向当日失败 Run。

## 检查（按顺序，先无副作用）

1. 确认环境变量被加载且 **未在日志中回显 Key**：

   ```bash
   env | grep -E '^INVEST_PIPELINE_(CIFANG_|PROVIDER_KEY)' | sed 's/=.*/=***/'
   ```

   预期：看到 `INVEST_PIPELINE_PROVIDER_KEY=cifangquant`、
   `INVEST_PIPELINE_CIFANG_ENABLED=true`、`INVEST_PIPELINE_CIFANG_API_KEY=***`
   （Key 永远不应以明文出现）。

2. 确认调度 / 上游未把 Provider 切回 `fixture_dev`：

   ```bash
   grep -n 'INVEST_PIPELINE_PROVIDER_KEY' apps/pipeline/src/invest_pipeline/*.py | head -5
   ```

3. 通过 API 查询最新失败 Run 的 `error_summary`（不打印 Key）：

   ```bash
   curl -sS http://localhost:8000/api/v1/pipeline-runs/latest | python -m json.tool
   ```

   若 `status=failed`，记录 `run_id` 与 `error_summary` 摘要，再继续。

4. 在本地用受限 smoke 复现鉴权路径（不消费业务数据）：

   ```bash
   make provider-smoke \
       SMOKE_SYMBOLS=510300,510500 \
       SMOKE_TRADE_DATE=2026-07-30 \
       SMOKE_CONFIRM_NETWORK=1
   ```

   预期：`SMOKE_CONFIRM_NETWORK=1` + `INVEST_PIPELINE_CIFANG_ENABLED=true`
   + `INVEST_PIPELINE_CIFANG_API_KEY` 已注入。若仍然 401 / 403，进入修复。

## 修复

> 任何“把 Key 粘进命令行 / 配置文件 / 仓库”的做法一律禁止。本仓库 Key 必须
> 仅通过环境变量注入，并由 ADR-0010 §5 / §6 描述的 Secret 注入路径管理。

1. 在 CifangQuant 控制台重新签发 / 轮换 `x-api-key`；核对控制台账户对该
   `/api/fund/list` / `/api/fund/hist_em` 端点的可见性（ADR-0011 §2）。
2. 通过 **环境变量** 注入新 Key（不会回显）：

   ```bash
   export INVEST_PIPELINE_PROVIDER_KEY=cifangquant
   export INVEST_PIPELINE_CIFANG_ENABLED=true
   export INVEST_PIPELINE_CIFANG_API_KEY=***        # 由密钥管理工具注入，绝不粘到 shell history
   ```

3. 不要修改任何 `.env`、`apps/*/.env`、`pyproject.toml`、`uv.lock`、CI 配置。
   若发现任何提交中含 Key，立即按 ADR-0010 §5 走轮换 + 撤销流程。
4. 自动 Schedule 环境同步：确认 `INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false`
   （`Makefile:415` 暗示默认关闭），手工修复后再按 §重跑 单独重放一次。

## 重跑

1. 受限 smoke 验证鉴权恢复：

   ```bash
   make provider-smoke \
       SMOKE_SYMBOLS=510300,510500 \
       SMOKE_TRADE_DATE=2026-07-30 \
       SMOKE_CONFIRM_NETWORK=1
   ```

2. 重放失败日（一次性单日，不进入回填）：

   ```bash
   make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1
   ```

   `YYYY-MM-DD` 取自失败 Run 的 `partition_key`（亦即业务交易日）。

3. 若当日自动 Schedule 仍处于关闭态，不要在本 runbook 内手动启用自动运行；
   自动化开关在 PR-02 之后的运维变更中独立处理。

## 成功验证

1. `make provider-smoke` 退出码为 `0`，输出仅含日期 / 标的 / 状态摘要。
2. `make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1` 退出码为 `0`。
3. `GET /api/v1/pipeline-runs/latest`：

   ```json
   {
     "partition_key": "YYYY-MM-DD",
     "trigger_type": "manual",
     "status": "succeeded",
     "error_code": null,
     "error_summary": null
   }
   ```

4. `GET /api/v1/data-freshness` 返回 `status ∈ {fresh, partial}` 且
   `pipeline_status=succeeded`，`missing_count` 与已发布 Run 对齐。
5. 全程日志 / API 响应中 `api_key` 渲染为 `***`；未在控制台、终端输出、
   fixture、commit、API 响应体出现明文 Key。