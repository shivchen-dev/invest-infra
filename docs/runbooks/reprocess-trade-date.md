# Runbook — 补跑单个交易日

> 适用范围：`personal_etf_daily_job` 漏跑、失败、或需重放幂等的业务交易日。
> 触发命令：`make reprocess-date TRADE_DATE=YYYY-MM-DD`
> （`Makefile:143`，内部委托 `personal-daily-run`，并校验 `TRADE_DATE` 必填）。
> 多日连续补跑请改走 `make personal-backfill`（跨度 ≤ 90 自然日，仅周一至周五，
> 任一工作日失败立即中止）。

## 症状

- `GET /api/v1/pipeline-runs/latest` 返回 `partition_key` ≠ 预期业务交易日，或
  `status ∈ {failed, running}`。
- `GET /api/v1/data-freshness` 返回 `status ∈ {stale, missing, failed}`，
  且 `latest_published_trade_date` 早于预期。
- Dagster UI / Dagit 中当日 `personal_etf_daily_job` Run 标红或缺失。
- 个别 ETF 行情缺失：`missing_count > 0` 且 `daily_bar_count < universe_count`。

## 检查（先确认日期合法且当日确需补跑）

1. 确认 `TRADE_DATE` 为 ISO `YYYY-MM-DD` 且为预期业务交易日（Asia/Shanghai，
   ADR-0004 §1）。`Makefile:144` 会在缺失时拒绝执行；脚本自带合法性校验，
   但仍建议先用交易所日历交叉核对。
2. 确认当日无活跃 Run（避免同日并发重复发布，PR-02 §6.6）：

   ```bash
   curl -sS http://localhost:8000/api/v1/pipeline-runs/latest | python -m json.tool
   ```

   若 `status=running` 或 `partition_key=TRADE_DATE`，先停止 / 等待当前 Run。
3. 确认 Provider 已就绪：
   - 默认 `fixture_dev`：`INVEST_PIPELINE_PROVIDER_KEY=fixture_dev`，无需
     `--confirm-network`，直接补跑即可。
   - 真实 `cifangquant`：必须 `INVEST_PIPELINE_CIFANG_ENABLED=true` 且
     `INVEST_PIPELINE_CIFANG_API_KEY` 已注入。若鉴权报错，先按
     `docs/runbooks/cifang-auth-failure.md` 修复。
4. 确认 Universe / Policy 文件存在且可读：

   ```bash
   ls -1 "${INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH:-<default>}" \
         "${INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH:-<default>}"
   ```

## 修复（仅为补跑准备，不改动业务规则）

1. 如 Universe 缺失：补齐个人 ETF 列表文件，不要修改 `personal_daily_cli` /
   `personal_universe` 任何代码。
2. 如 Policy 缺失：补齐阈值文件，不要修改 `candidate_pool_service`。
3. 如 Provider Key 错配：在运行环境校正
   `INVEST_PIPELINE_PROVIDER_KEY` / `INVEST_PIPELINE_CIFANG_ENABLED`，
   不要改 `Makefile` / `provider_factory.py`。
4. 自动 Schedule 在 Stage 2 期间默认关闭（`INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false`）；
   补跑期间保持关闭，补跑结束后再评估是否需要恢复。

## 重跑

1. fixture / 开发模式补跑：

   ```bash
   make reprocess-date TRADE_DATE=YYYY-MM-DD
   ```

2. 真实 CifangQuant 补跑（三重 opt-in）：

   ```bash
   export INVEST_PIPELINE_PROVIDER_KEY=cifangquant
   export INVEST_PIPELINE_CIFANG_ENABLED=true
   export INVEST_PIPELINE_CIFANG_API_KEY=***        # 由密钥管理工具注入
   make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1
   ```

3. 多日补跑（仅在 PR-04 之后启用，且跨度 ≤ 90 自然日）：

   ```bash
   make personal-backfill START_DATE=YYYY-MM-DD END_DATE=YYYY-MM-DD
   ```

   周六 / 周日自动跳过；任一工作日运行失败立即中止并保留非零退出码。

## 成功验证

1. 命令退出码为 `0`；输出仅含日期 / 状态摘要（不回显密钥或路径，ADR-0010 §6）。
2. `GET /api/v1/pipeline-runs/latest`：

   ```json
   {
     "partition_key": "YYYY-MM-DD",
     "status": "succeeded",
     "error_code": null,
     "error_summary": null
   }
   ```

   且 `started_at <= finished_at`、`trigger_type ∈ {manual, schedule}` 与执行方式一致。
3. `GET /api/v1/data-freshness` 返回 `status ∈ {fresh, partial}`，
   `latest_published_trade_date=YYYY-MM-DD`、`pipeline_status=succeeded`。
4. `GET /api/v1/candidate-pool/latest/diff` 返回新一日 `published` Run
   与上一 `published` Run 的差异；当日 `included + excluded == universe_count`。
5. 重跑幂等：当日**第二次**执行 `make reprocess-date TRADE_DATE=YYYY-MM-DD`
   （fixture 模式即可）后：
   - `core.daily_bars` 不增加新 revision；
   - 相同自然键不重复创建 Candidate Pool Run；
   - `pipeline_runs` 中当日记录数不增长。
6. 若补跑后 `status=failed`，按错误类别回到对应 runbook（鉴权类走
   `cifang-auth-failure.md`；其它 Provider / 日历 / 域错误按当日
   `error_code` 排查，不要在失败时反复重跑同一条命令而不修正根因）。