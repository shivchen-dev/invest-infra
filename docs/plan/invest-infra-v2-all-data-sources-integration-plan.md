# invest-infra V2 全数据源接入实施计划

> 版本：v1.0
> 日期：2026-08-03
> 状态：Approved for incremental implementation

## 1. 目标

在不复制 V1 旧数据库、旧 cron 和旧业务表的前提下，将 V1 已验证的数据源
能力按 V2 Provider Contract 接入：

```text
AkShare       → ETF 主数据 / OHLCV / NAV / 交易日历
CifangQuant   → ETF 主数据 / 近期 OHLCV
RssCast       → 股票 / 指数 / 资讯研究
QuickTiny     → ETF / 指数市场快照、排行、研究
fixture_dev   → 离线开发测试
```

真实源均保持显式启用、默认关闭；研究源不得未经契约转换直接写入
`core.daily_bars`。

## 2. 已冻结的事实

- CifangQuant 当前 V2 Adapter 已实现并通过令牌 Smoke；2016 年抽查无数据。
- QuickTiny 当前令牌已配置到 OpenClaw，`tools/list` 返回 63 个工具，包含
  `etf_market` 和 `index_market`；V2 暂时仍是 `research_only`。
- RssCast 当前令牌可用，MCP 返回 17 个工具，能力集中在股票/指数/资讯。
- AkShare 的 V1 ETF OHLCV、NAV 和交易日历能力已有代码记录，但 V2 尚未有
  Adapter；应优先验证 2016 年历史覆盖。
- 任何 Provider 都必须保留 request、attempt、batch、字段完整度和原始响应哈希。

## 3. 实施任务

### Task 1：Provider Contract 与能力目录扩展

- 补齐 AkShare、CifangQuant、RssCast、QuickTiny、fixture_dev 的声明。
- 区分 `ETF_DAILY_BARS`、`ETF_MASTER_DATA`、`INDEX_DAILY_BARS`、`RESEARCH`
  和 `MARKET_SNAPSHOT`。
- 为真实源保留 `enabled_by_default=false`。

验收：目录、Factory、未知 Provider 和默认安全开关测试通过。

### Task 2：AkShare Adapter 与覆盖探测

- 实现 ETF 主数据、OHLCV、NAV、交易日历 Adapter。
- 增加分层探测命令，只读生成 source coverage matrix。
- 明确 NAV 不映射为 OHLCV，不填充成交额。

验收：至少完成代表性 ETF 的 2016、2018、2020、近期覆盖报告。

### Task 3：QuickTiny ETF/指数 Adapter

- 接入官方 `/api/mcp` 的 `etf_market`、`index_market`。
- 先支持 search/snapshot/rank/daily/minute 的只读调用和响应脱敏。
- 研究/快照结果进入独立 evidence，不直接覆盖 Cifang 日线。

验收：真实令牌调用成功；ETF 日线字段映射和上游 503 可重试可观测。

### Task 4：RssCast Research Adapter

- 接入 MCP 初始化、工具发现、股票/指数/资讯工具调用。
- 不实现 ETF `DailyBar` 适配。
- 统一记录工具名、参数哈希、响应哈希、错误和限流状态。

验收：真实令牌工具发现成功；研究结果不进入行情表。

### Task 5：Provider Routing、覆盖报告与回填

- 按 dataset/capability 选择 Provider。
- 生成 active ETF 的 source × symbol × date-range × field coverage 矩阵。
- 确认历史起点和字段质量后，执行幂等回填。

验收：重复运行不产生重复记录；失败源不静默替换；所有来源可追溯。

## 4. PR 顺序

```text
PR-01 Provider Contract / Catalog
  ↓
PR-02 AkShare Adapter + Coverage Probe
  ├─→ PR-03 QuickTiny Adapter
  └─→ PR-04 RssCast Research Adapter
        ↓
PR-05 Routing / Coverage Matrix / Historical Backfill
```

每个 PR 都必须独立通过聚焦测试、编译检查和 ARC 代码审查；真实网络验收
只在显式命令中执行，不进入普通 CI。

## 5. 明确不做

- 不复制 V1 旧数据库、旧 cron、旧 Redis/MinIO 数据模型。
- 不把机构/QuickTiny/RssCast 研究观点伪装成确定性行情事实。
- 不将 NAV、指数或股票数据强行写成 ETF OHLCV。
- 不在没有覆盖报告前直接执行全量 2016 回填。
- 不把任何 Provider 的人工权重或历史表现解释为参数寻优结果。
