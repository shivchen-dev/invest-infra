# 智能投研体系 — 目录索引

> 项目根目录说明文档。投研系统 Phase 0 基础设施。
>
> **v1.1 · 2026-06-12**（RAA 系统说明审计触发，详见 `../CHANGELOG.md`）

---

## 🏗️ 系统架构

| 服务 | 端口 | 用途 | 持久化 |
|:----|:----|:-----|:------|
| PostgreSQL | 5432 | 数据仓库（Silver + Gold 层） | pgdata volume |
| Redis | 6379 | 缓存 + 消息队列 | redis-data volume |
| MinIO | 9000 (API) / 9001 (Console) | 对象存储（Bronze 原始层） | minio-data volume |

**快速启动：** `docker compose up -d`

---

## 📂 目录结构

```
invest-infra/
├── docs/ ← 永久文档（运营用）
│   ├── README.md
│   ├── cron_cia.md          ← CIA定时任务系统手册
│   ├── workflow-batch-fix.md ← 批量修复工作流规范
│   ├── reports-arch.svg     ← 报告体系架构图
│   ├── system-arch.svg      ← 系统架构图
│   └── 需求方案/             ← 需求/方案设计文档
│       ├── README.md
│       ├── 2026-06-07_行业ETF持仓采集与价格位置筛选.md
│       ├── 2026-06-08_投研汇报模块模板设计.md
│       ├── 2026-06-08_集思录插件思路_ETF智能筛选方案.md
│       ├── MCP采集-报告DB化改造方案.md
│       ├── Phase4-mock矩阵设计.md
│       └── 状态快照-2026-06-11.md
│
├── planning/                 ← 项目工作区（用完归档）
│   ├── 2026-06-05_critical_fix/  ← 已归档：Critical Issues修复
│   ├── 2026-06-07_data_collection_layer/
│   ├── 2026-06-07_formatters_revision/
│   ├── 2026-06-07_market_report_system/
│   ├── 2026-06-07_sector_filter_design/
│   ├── stage1-p0-password/        ← PG 密码硬编码修复
│   ├── task_plan.md
│   ├── claude-cmd-fix-analysis.md
│   └── README.md
│
├── data-pipeline/           ← 核心代码 + cron脚本
│   ├── src/
│   │   ├── signals/         ← 信号计算（etf_alpha / etf_arbitrage / scoring）
│   │   ├── factors/         ← 因子计算
│   │   │   ├── etf.py              ← ETF 溢价/IOPV/流动性
│   │   │   ├── etf_fundamental.py  ← F 维度（行业情绪）
│   │   │   ├── etf_info_flow.py    ← I 维度（信息因子）
│   │   │   ├── etf_risk.py         ← R 维度（风险/HV/回撤）
│   │   │   ├── fundamental.py / technical.py / advanced.py / alternative.py
│   │   │   └── engine.py / registry.py / base.py
│   │   ├── pipeline/        ← ETL 编排（error_isolation / scheduler_jobs）
│   │   ├── collector/       ← 数据采集（cifang / companies / etf / financial / news / quotes / research_report / rsscast / retry / etf_health_monitor）
│   │   ├── backtest/        ← 回测（engine / analyzers / feeds / strategies / report）
│   │   ├── loader/          ← 数据加载（pg / minio）
│   │   ├── reports/         ← 报告引擎（report_engine / formatters / modules / qq_push / db / mcp_client / market_data_*）
│   │   └── ...
│   ├── scripts/            ← cron脚本
│   │   ├── cron_dispatcher.py   ← 任务调度入口（TASK_MAP = 20 个任务）
│   │   ├── cron_*.py            ← 各任务调度脚本（19 个）
│   │   ├── woa_tasks/           ← WOA Morning Briefing 子任务
│   │   ├── notes/               ← 临时调试备注（用完即删）
│   │   └── run_*.py / sync_*.py ← 手动运行/数据同步脚本
│   ├── tests/              ← 单元测试
│   ├── logs/                ← 运行日志
│   ├── sql/                 ← SQL 脚本
│   ├── .venv/               ← Python虚拟环境
│   └── pyproject.toml / uv.lock
│
├── init-db/                 ← 数据库DDL初始化脚本（00~06）
│
├── reports/                 ← 审计/评估报告归档
│   ├── signals_module_audit_report.md
│   ├── factors_module_audit_report.md
│   ├── data_collection_layer_audit_report.md
│   ├── raa-fix-P0-RAA-1-20260611.md     ← RAA 审计修复报告
│   ├── audit_merged_report.md
│   └── archive/                         ← 历史报告
│
├── evaluation_reports/      ← 架构评审/工作流追踪报告
│   ├── FINAL_INTEGRATION_REPORT.md
│   ├── morning_briefing_workflow_trace_report.md
│   └── archive/
│
├── logs/                    ← 根目录日志（cron_cia.log / report_engine.log）
│
├── .secrets/                ← 密钥（.gitignore，不提交）
│
├── docker-compose.yml
├── setup_cron_timers.sh     ← 旧版（基于 crontab）
├── setup_systemd_timers.py  ← 当前方案（systemd user timers，47 个）
├── start.sh / stop.sh
├── redis.conf
├── .raa-fix-status.json     ← RAA 修复状态文件（修复 Agent 写入，RAA 只读）
├── raa-audit-readonly       → 软链接 → /home/claw/.openclaw/workspace-audit/memory/audits/
└── raa-handoff-readonly     → 软链接 → /home/claw/.openclaw/workspace-audit/memory/handoff/
```

---

## 📌 根目录清理状态（v1.1 复核）

| 状态 | 文件 / 位置 |
|------|------|
| ✅ 已清理 | 根目录 `findings.md`（不存在） |
| ✅ 已清理 | 根目录 `progress.md`（已不存在；旧版 README 误指 `data-pipeline/progress.md` 实际也不存在） |
| ✅ 已移动 | `task_plan.md` → `planning/task_plan.md` |
| ⚠️ 待评估 | `data-pipeline/_fetch_memo_method.txt / _new_parsers.py / _parser_methods.txt / _patch_premarket.py / _step0.txt`（下划线前缀文件，疑似调试残留，建议归档或删除） |

---

## 🔑 密钥路径

| 文件 | 用途 |
|------|------|
| `.secrets/pg.env` | PostgreSQL 凭据（root/.env 改造后独立） |
| `.secrets/minio.env` | MinIO 凭据 |
| `.secrets/redis.conf`（根目录） | Redis 配置（**非密钥**，明文） |
| `.secrets/cifang.env` | 集思录 API 凭据 |
| `.secrets/mcp.env` | MCP 服务凭据 |
| `.secrets/tokens.env` | GitHub/Gitee/投研项目 API Token |
| `.secrets/tokens.env.bak-pre-rotate-20260611` | Token 轮换前备份（保留 30 天后清理） |
| `data-pipeline/.env` | PostgreSQL / MinIO / Redis 密码（**权限 600**，RAA-2 修复） |

---

## 📊 数据库（PostgreSQL investdb）— v1.1 实际盘点

**总表数：43 张**（v1.0 误为 10 张；实际含 FQIR 子分表、回测、报告缓存、用户组合等）

### 核心业务表（ETF / 行情）

| 表 | 用途 | 行数级别 |
|----|------|---------|
| `etfs` | ETF 基本信息 | **1843** 只（v1.0 标 1576 已过时）|
| `etf_quotes` | ETF 行情快照 | 每日增量 |
| `etf_alpha_signals` | ETF FQIR 综合评分 | 累计 15617+ |
| `etf_factor_values` | 因子原始值（premium_rate/iopv/liquidity_score）| 累计 12297+ |
| `etf_fundamental_scores` | F 维度（行业情绪）子分 | 累计 1829+ |
| `etf_info_scores` | I 维度（信息因子）子分 | 累计 2684+ |
| `etf_risk_scores` | R 维度（风险）子分 | 累计 1489+ |
| `etf_quant_scores` | Q 维度（财务质量）子分 | 0 行（表已建但未投入使用，⚠️ 待确认）|
| `etf_arbitrage_signals` | 套利信号 | 每日增量 |
| `etf_health_alerts` | ETF 健康检查告警 | 每日增量 |
| `etf_sw_industry_sentiment` | 申万行业情绪（F 维度源数据）| 每日增量 |
| `daily_quotes` | 个股日线 | 每日增量 |
| `daily_market_snapshot` | 全市场快照 | 每日 |
| `index_quotes` / `indices` | 指数行情 / 指数基本信息 | 每日增量 |
| `companies` | A 股公司信息 | **5525** 家 |

### 数据采集 / 新闻

| 表 | 用途 |
|----|------|
| `news_articles` | 新闻/快讯（I 维度源）|
| `industry_info_scores` | 申万行业快讯密度（I 维度产物）|
| `financial_reports` | 财报数据（p1-p4 采集）|
| `fund_flow_big_deal` | 大单资金流 |
| `stock_daily_fund_flow` | 个股日资金流 |
| `cov_bond_link` | 可转债联动数据 |
| `north_turnover_hist` / `south_flow_hist` | 沪深港通历史成交 |

### 龙虎榜

| 表 | 用途 | 数据状态 |
|----|------|---------|
| `lhb_records` | 龙虎榜 | ⚠️ **数据截止 2023-04-17**（待恢复采集）|

### 因子体系（DB 化，v2.0 引入）

| 表 | 用途 |
|----|------|
| `factor_definitions` | 因子定义字典（factor_key / category / formula_desc）|
| `factor_weights` | 因子权重 + norm_direction |
| `factor_values` | 因子计算结果（按 company_id / etf_id 关联）|

### 回测

| 表 | 用途 |
|----|------|
| `backtest_runs` | 回测运行记录 |
| `backtest_results` | 回测明细 |
| `backtest_summary` | 回测汇总指标 |

### 报告 / 报告引擎缓存

| 表 | 用途 |
|----|------|
| `market_reports` | 报告存档（盘前/午盘/盘后/盘中）|
| `report_subscriptions` | 报告订阅关系 |
| `sector_filter_candidates` | 板块筛选候选池 |
| `sector_filter_reports` | 板块筛选报告 |
| `intraday_alerts` | 日内告警（dedup 约束 v2.0 已修复）|

### 投资 / 用户

| 表 | 用途 |
|----|------|
| `investment_memos` | 投研备忘录（人工录入）|
| `user_portfolios` | 用户自选/持仓 |

### 历史 / 元数据

| 表 | 用途 |
|----|------|
| `alpha_signals` / `analysis_signals` | 旧版信号表（建议评估后归档）|
| `data_source_log` | 数据源采集日志 |
| `scheduler_jobs` | 任务执行追踪（每条 pipeline 函数一行）|
| `task_queue` | 任务队列（Redis 持久化镜像）|

完整表列表：
```sql
SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
```

---

## ⏰ 定时任务（Cron / systemd）

**v1.1 实际状态：47 个 systemd user timers**（v1.0 误为 18 / 22 个）

### 业务调度任务（46 个 timer）

| 来源 | 任务 | 数 | 说明 |
|------|------|---|------|
| `setup_systemd_timers.py` SINGLE_TASKS | 早盘 briefing + 收盘因子 + 财务分批 | **16** | 静态 unit，重启后持久 |
| 同一脚本 ETF 日内派生 | `etf_intra_1000 ~ etf_intra_1545` | **24** | 每 15 分钟调一次 `etf_spot_intraday` |
| 独立 timer | `pre_market / midday / post_market / market_collect / market_collect_midday` | **5** | 由 `setup_cron_timers.sh` 或手动注册，**未在 setup_systemd_timers.py 中**（建议统一） |
| 系统守护 | `watchdog`（每小时） | **1** | 任务超时监控 + 补发 |

### 业务时段分布（v1.1 复核）

| 时段 | 任务数 | 代表任务 | 触发时间 |
|------|--------|---------|----------|
| **早盘** | **5** | morning_briefing / woa_audit / etf_spot_morning / etf_spot_intraday（09:35）/ pre_market | 05:50 - 09:35 |
| **盘中（ETF 日内）** | 24 | etf_intra_1000 ~ etf_intra_1545 | 10:00 - 15:45 每 15min |
| **午盘** | 1 | midday | 12:00 |
| **午盘/盘后** | 11 | market_collect / sw_industry / etf_kline / industry_info / index_eod / etf_factor / etf_alpha / etf_health / etf_arbitrage / market_collect_midday / post_market | 10:00 - 17:35 |
| **夜盘** | 4 | financial_p1 / p2 / p3 / p4 | 14:00 - 20:30 |
| **守护** | 1 | watchdog | 每整点 |

**v1.0 错误**：早盘 5 / 午盘 12 / 夜盘 3 算术与总数 18 对不上；已重算。

详见：`docs/cron_cia.md` + `SYSTEM_PLAYBOOK.md §5.5`

---

## 📖 文档索引

| 文档 | 内容 |
|------|------|
| `README.md` | 系统架构总览（本文件，v1.1）|
| `docs/cron_cia.md` | CIA 定时任务完整手册 |
| `docs/workflow-batch-fix.md` | 批量代码修复工作流 |
| `docs/需求方案/MCP采集-报告DB化改造方案.md` | ADR-005 详细方案 |
| `SYSTEM_PLAYBOOK.md` | 故障处理手册（v1.1，含 Agent 档案 / 模块矩阵 / 决策日志）|
| `evaluation_reports/FINAL_INTEGRATION_REPORT.md` | 系统集成总评 |
| `reports/raa-fix-P0-RAA-1-20260611.md` | RAA 审计 P0 修复报告 |
| `reports/audit_*.md / evaluation_*.md` | 各模块历史审计/评估报告 |
| `memory/2026-06-12.md`（RAA 工作区）| RAA 审计日志 |

---

*文档作者：CIA（Chief Investment Agent） + system-architect（维护）*
*最后更新：**2026-06-12**（v1.1，RAA 系统说明审计触发）*
*审计报告：`/home/claw/.openclaw/workspace-audit/memory/audits/raa-audit-system-docs-20260612.md`*
