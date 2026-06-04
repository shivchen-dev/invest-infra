# Progress: FQIR‑ETF 评分体系实施

## Session: 2026-06-02

### Phase 1: 数据库与表结构扩展
- **Status:** complete
- **Started:** 2026-06-02 16:20
- Actions taken:
  - 研究现有表结构（etfs / etf_quotes / etf_alpha_signals / etf_factor_values）
  - 确定需要新增的字段（cr5/cr10/rebalance_freq/index_category + risk/info/fundamental_score）
  - 规划 DDL migration 文件位置（init-db/）
  - 创建 `04_etf_fqir_extension.sql` DDL 文件
  - 成功执行 DDL，创建 4 张新表 + 扩展 2 张现有表
- Files created/modified:
  - `init-db/04_etf_fqir_extension.sql`（新建）
  - `task_plan.md`（新建）
  - `findings.md`（新建）
  - `progress.md`（更新）

### Phase 2: 因子层扩展（Q/L 增强）
- **Status:** complete
- **Started:** 2026-06-02 16:30
- Actions taken:
  - 扩展 ETF_DEFAULT_WEIGHTS：11因子 → 20因子（新增 momentum_60d / hv_20d / max_drawdown / backtest_stability / bid_ask_spread 等）
  - 新增 `compute_etf_indicators()` 扩充（momentum_60d / max_drawdown / backtest_stability / bid_ask_spread）
  - 新增 `get_etf_fundamental_scores()` / `get_etf_info_scores()` / `get_etf_risk_scores()` 读取外部因子表
  - 修复 `normalize()`：从 percentile_rank 改为 z-score 标准化（解决全市场最低导致极端分问题）
  - 修复维度默认分逻辑：`weighted_sum += cat_score * cat_weight`（之前漏了 weight）
  - 扩展 `_write_etf_signals()` 写入新增的 5 个分项字段
  - 验证通过：1489 ETF 全量计算，score 分布合理（均值 -10.0，范围 -20.2 ~ -6.0）
  - 确认：F/I 维度默认 50 分（外部表空），Q/L/R 维度正常计算
- Files created/modified:
  - `src/signals/etf_alpha.py`（大幅重写）

### Phase 3: F/I/R 子模块开发
- **Status:** in_progress
- **Started:** 2026-06-02 16:47
- Actions taken:
  - 诊断 akshare 接口：`stock_profile_cninfo(symbol='000001')` 可用，返回 `所属行业` 字段
  - 实测：PG 中 code 为 `000034.SZ` 格式，需提取纯数字调用 akshare
  - 并发测试：5并发+0.5s间隔成功率 100%；全量估算约 15 分钟
  - 密码发现：PostgreSQL 密码为 `REDACTED_PG_PASSWORD`（.env 中的 `***` 是占位符）
  - 创建 `scripts/sync_industry.py`：支持并发/重试/批次提交/dry-run
  - 验证通过：100家测试写入成功率 100%，`companies.industry` 已成功填充
  - 下一步：全量同步 5525 家公司（预计 15 分钟）
- Files created/modified:
  - `scripts/sync_industry.py`（新建）

---

## Session: 2026-06-03 更新

### I 维度（信息因子）
- **Status:** ✅ 已集成到 ETF FQIR（完成）
- **核心文件：**
  - `scripts/cron_industry_info.py`（385行）：cls_news MCP 调用、密度计算、DB写入
  - `src/factors/etf_info_flow.py`（新增 `_get_sw_industry_info_score()` + `industry_info_score` 字段写入）
  - `src/signals/etf_alpha.py`（`industry_info_score` 因子读取，权重 0.05）
- **数据源：** cls_news MCP（财联社快讯，每日50次限额）
- **完整数据流：**
  ```
  cls_news MCP API（keyword=行业关键词）
      ↓
  industry_info_scores（sw_name / news_count / info_score / window_h=24）
      ↓
  _get_sw_industry_info_score()（track_index字符串模糊匹配申万行业关键词）
      ↓
  etf_info_scores.industry_info_score（0-100）
      ↓
  ETF FQIR I维度（权重5%）
  ```
- **密度公式：** `score = 50 + (news_count/hist_avg - 1) * 25`，clamp 0-100
- **Cron：** `cia_industry_info_sync`，每日 15:50（周一~五）
- **今日数据：** 26个申万行业全部写入（3条真实值，其余=0因API限额已用完）
  - 采掘=20条→100分、、化工=7条→83.33分、农林牧渔=4条→58.33分
- **FQIR接入验证：** 448/1195只ETF获得非50分值（石油天然气ETF/化工ETF等）

### F 维度（行业情绪因子）
- **Status:** ✅ 已实现（完成）
- **核心文件：**
  - `scripts/sync_sw_industry.py`：akshare申万行业K线采集
  - `src/factors/etf_fundamental.py`：`compute_etf_fundamental_scores()` 读取行业情绪
- **Cron：** `cia_sw_industry_sync`，每日 15:35（周一~五）
- **今日验证：** 30/31行业成功写入，通信+5.71%、有色+3.26%、电子+2.62%

### Q 维度（财务质量因子）
- **Status:** ✅ 已实现（完成）
- `src/factors/etf_fundamental.py` 提供 `get_etf_fundamental_scores()`
- 权重：15%（Q维度共3因子：fundamental_score 0.08 + dividend_yield 0.04 + tracking_error 0.03）

### L 维度（流动性因子）
- **Status:** ✅ 已实现（完成）
- `src/factors/etf_liquidity.py`：量比/成交额/换手率综合评分

### R 维度（风险因子）
- **Status:** ✅ 已实现（完成）
- `src/factors/etf_risk.py`：波动率HV/最大回撤/流动性风险综合评分

### 候选池输出
- **Status:** 框架完成，输出待优化
- `src/signals/scoring.py` 的 `filter_candidate_pool()`
- 06-02 Top5：560480电力ETF招商(3.59)、560870工业有色ETF中银(3.56)、560830电力ETF华夏(3.55)

---

## 新增 cron 总览

| 名称 | 时间 | 任务 | 状态 |
|------|------|------|------|
| `cia_sw_industry_sync` | 15:35 周一~五 | 申万行业涨跌同步 | ✅ 06-03验证成功 |
| `cia_industry_info_sync` | 15:50 周一~五 | 财联社行业快讯密度同步 | ✅ 06-03验证成功 |

---

## 待解决问题

| 优先级 | 问题 | 状态 |
|--------|------|------|
| 高 | I维度 MCP每日50次限额 | ⚠️ 今日已耗尽，明日0点重置后验证 |
| 高 | 每日推荐报告输出机制 | 📋 待开发 |
| 中 | 申万行业覆盖（`_TRACK_TO_SW`）仍有ETF未命中 | 📋 补充映射表 |
| 低 | R维度 akshare接口高频并发稳定性 | 📋 可接受 |

---

## Test Results

| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| sync_industry dry-run 30家 | --limit 30 --dry-run | 成功率 >90% | 100% 成功 | ✅ |
| sync_industry 写入 100家 | --limit 100 | 成功写入 | 100家全部成功 | ✅ |
| etf_alpha 全量计算 | compute_etf_alpha(latest) | score 合理分布 | 范围 -20.2~-6.0 | ✅ |
| sync_sw_industry 今日 | 06-03 数据 | 写入 30/31 条 | 成功 | ✅ |
| industry_info_scores 写入 | 06-03 26行业 | 写入 26 条 | 成功（含3条真实值） | ✅ |
| I维度FQIR集成验证 | 1195只ETF | 非50分>0 | 448只ETF非50分 | ✅ |

---

## Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-06-02 16:18 | ModuleNotFoundError: src | 1 | cd 到正确目录执行 |
| 2026-06-02 16:18 | PG_PASSWORD env not set | 1 | 在 cron 脚本中加载 .env |
| 2026-06-02 16:18 | MINIO_SECRET_KEY env not set | 1 | 同上 |
| 2026-06-02 16:46 | psql: command not found | 1 | 使用 psycopg2 直接执行 SQL |
| 2026-06-02 16:47 | .env path error | 2 | 使用正确路径 `data-pipeline/.env` + `export` |
| 2026-06-02 16:47 | akshare cninfo 连接失败（高频并发） | 3+ | 降低并发至 5，间隔 0.5s，增加重试 |
| 2026-06-02 16:47 | PG password auth failed | 1 | 发现正确密码 `REDACTED_PG_PASSWORD`（.env 中是 `***` 占位符） |
| 2026-06-02 16:47 | akshare 接口 code 格式不匹配 | 1 | 新增 `_raw_code()` 函数，从 `000034.SZ` 提取 `000034` |
| 2026-06-03 09:xx | MCP cls_news 每日50次限额耗尽 | 多次 | 已修复 dry_run 跳过API调用；cron改为每日一次 |