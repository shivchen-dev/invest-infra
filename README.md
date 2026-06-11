# 智能投研体系 — 目录索引

> 项目根目录说明文档。投研系统 Phase 0 基础设施。

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
│   └── 方案需求/             ← 需求/方案设计文档
│
├── planning/                 ← 项目工作区（用完归档）
│   └──2026-06-05_critical_fix/  ← 已归档：Critical Issues修复
│
├── data-pipeline/           ← 核心代码 + cron脚本
│   ├── src/
│   │   ├── signals/         ← 信号计算（ETF评分/FQIR）
│   │   ├── factors/         ← 因子计算（I/F/Q/L/R维度）
│   │   ├── pipeline/        ← 数据管道
│   │   ├── collector/       ← 数据采集
│   │   ├── backtest/       ← 回测
│   │   ├── loader/         ← 数据加载
│   │   └── ...
│   ├── scripts/            ← cron脚本（18个定时任务）
│   │   ├── cron_*.py       ← 各任务调度脚本
│   │   ├── woa_tasks/      ← WOA Morning Briefing任务
│   │   └── notes/          ← 临时调试备注（用完即删）
│   ├── tests/              ← 单元测试
│   ├── logs/ ← 运行日志
│   ├── .venv/             ← Python虚拟环境
│   └── progress.md         ← FQIR-ETF评分体系实施日志
│
├── init-db/                 ← 数据库DDL初始化脚本
│
├── reports/                 ← 审计/评估报告归档
│   ├── signals_module_audit_report.md
│   ├── factors_module_audit_report.md
│   ├── data_collection_layer_audit_report.md
│   └── ...
│
├── logs/                    ← 根目录日志（软链或杂项）
│
├── .secrets/               ← 密钥（.gitignore，不提交）
│
├── docker-compose.yml
├── setup_cron_timers.sh
├── setup_systemd_timers.py
├── start.sh / stop.sh
└── redis.conf
```

---

## 📌 根目录残留文件（待清理）

以下文件是旧 `planning/` 结构遗留，应移入 `planning/` 或删除：

| 文件 | 说明 |
|------|------|
| `findings.md` | → 应移入 `planning/2026-06-05_critical_fix/` |
| `progress.md` | → 应移入 `planning/2026-06-05_critical_fix/` |
| `task_plan.md` | → 应移入 `planning/2026-06-05_critical_fix/` |

---

## 🔑 密钥路径

- `.secrets/tokens.env` — GitHub/Gitee/投研项目 API Token
- `.env`（data-pipeline/）— PostgreSQL / MinIO / Redis 密码

---

## 📊 数据库（PostgreSQL investdb）

| 表 | 用途 |
|----|------|
| `etfs` | ETF基本信息（1576只） |
| `etf_quotes` | ETF行情快照 |
| `etf_alpha_signals` | ETF FQIR综合评分 |
| `etf_factor_values` | 各维度因子值 |
| `news_articles` | 新闻/快讯（I维度） |
| `investment_memos` | 投研备忘录 |
| `lhb_records` | 龙虎榜（⚠️数据截止2023-04） |
| `industry_info_scores` | 行业快讯密度 |
| `companies` | A股公司信息（5525家） |
| `data_source_log` | 数据源采集日志 |

完整表列表：`SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;`

---

## ⏰ 定时任务（Cron）

共 **18个**定时任务，详见 `docs/cron_cia.md`。

| 时段 | 任务数 | 代表任务 |
|------|--------|---------|
| 早盘 05:50-09:35 | 5 | Morning Briefing / ETF盘前 |
| 午盘/盘后 10:00-17:35 | 12 | 行业/因子/Alpha/套利信号 |
| 夜盘 18:30-20:30 | 3 | 财务数据采集 |

---

## 📖 文档索引

| 文档 | 内容 |
|------|------|
| `docs/cron_cia.md` | CIA定时任务完整手册 |
| `docs/workflow-batch-fix.md` | 批量代码修复工作流 |
| `data-pipeline/progress.md` | FQIR-ETF评分体系实施日志 |
| `planning/2026-06-05_critical_fix/findings.md` | Critical Issues审计报告 |
| `reports/` | 各模块评估/审计报告归档 |
---

*文档作者：CIA（Chief Investment Agent）*
*最后更新：2026-06-07*
