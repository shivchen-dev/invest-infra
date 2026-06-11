# CIA 定时任务系统 — 故障处理手册 (SYSTEM PLAYBOOK)

> **版本**: v1.0 | **更新日期**: 2026-06-07  
> **维护者**: tech-expert | **适用范围**: 所有定时任务运维人员

---

## 目录

1. [常见问题速查表](#1-常见问题速查表)
2. [故障处理流程](#2-故障处理流程)
3. [监控与告警机制](#3-监控与告警机制)
4. [回滚策略](#4-回滚策略)
5. [系统全景图](#5-系统全景图) ← 新增
6. [核心智能体档案](#6-核心智能体档案) ← 新增
7. [模块职责矩阵](#7-模块职责矩阵) ← 新增
8. [关键决策日志](#8-关键决策日志) ← 新增

---

## 1. 常见问题速查表

### 1.1 任务执行失败

| 症状 | 可能原因 | 快速诊断命令 | 处理步骤 |
|------|----------|--------------|----------|
| 任务状态为 `error` | 脚本异常退出、依赖缺失、API 超时 | `cat /tmp/cron_exec_status.json \| jq '.<task>.error'` | 1. 查看日志 `tail -50 logs/cron_dispatcher.log`<br>2. 手动执行 `python3 cron_dispatcher.py <task>`<br>3. 检查依赖 `.venv/bin/pip list` |
| 任务状态为 `timeout` | 执行时间超过阈值（默认 120s-1800s） | `cat /tmp/cron_exec_status.json \| jq '.<task>'` | 1. 手动执行计时<br>2. 检查数据源是否响应慢<br>3. 考虑增加 timeout 或拆分任务 |
| 任务状态为 `exception` | Python 异常（ImportError、KeyError 等） | `grep "💥" logs/cron_dispatcher.log \| tail -5` | 1. 查看完整 traceback<br>2. 修复代码或数据格式<br>3. 重新执行 |
| 任务被跳过 (exit code 99) | 锁文件冲突（前次未释放） | `ls /tmp/cron_lock/*.lock` | 1. 检查进程 `ps aux \| grep <task>`<br>2. 清理死锁 `rm /tmp/cron_lock/<task>.lock`<br>3. 重新执行 |

### 1.2 看门狗告警异常

| 症状 | 可能原因 | 快速诊断命令 | 处理步骤 |
|------|----------|--------------|----------|
| 频繁收到 QQ 告警 | 任务持续超时、数据源故障 | `cat /tmp/cron_alert.json` | 1. 检查告警内容<br>2. 定位根因（见上表）<br>3. 处理后删除 `/tmp/cron_alert.json` |
| 看门狗未触发告警 | 静音窗口 (23:00-08:00)、非交易日 | `python3 -c "from datetime import datetime; h=datetime.now().hour; print('静音' if h>=23 or h<8 else '正常')"` | 1. 确认当前时间是否在静音窗口<br>2. 确认是否为交易日<br>3. 手动触发巡检 `python3 cron_watchdog.py` |
| 补发失败 | 锁冲突、依赖缺失、API 不可用 | `grep "补发" logs/cron_watchdog.log \| tail -10` | 1. 检查补发日志<br>2. 手动执行任务<br>3. 修复后重新触发看门狗 |
| systemd timer 缺失 | 系统重启后 transient timer 丢失 | `systemctl --user list-timers --all \| grep cia_` | 1. 运行 `python3 setup_systemd_timers.py`<br>2. 验证 `systemctl --user list-timers --all` |

### 1.3 数据源问题

| 症状 | 可能原因 | 快速诊断命令 | 处理步骤 |
|------|----------|--------------|----------|
| akshare API 超时/失败 | 新浪/东方财富接口限流或维护 | `python3 -c "import akshare; print(akshare.tool_trade_date_hist_sina().shape)"` | 1. 等待 5 分钟后重试<br>2. 检查 akshare 版本 `pip show akshare`<br>3. 考虑切换到备用数据源 |
| PostgreSQL 连接失败 | 数据库服务宕机、连接池耗尽 | `psql -h <host> -U <user> -c "SELECT 1"` | 1. 检查 PG 状态 `systemctl status postgresql`<br>2. 检查连接数 `SELECT count(*) FROM pg_stat_activity`<br>3. 重启 PG 或清理空闲连接 |
| Redis Stream 积压 | 消费者处理慢、内存不足 | `redis-cli info stream` / `redis-cli xlen <stream>` | 1. 检查消费者组 `XINFO CONSUMERS <stream> <group>`<br>2. 清理过期消息 `XTRIM <stream> MAXLEN ~ <threshold>`<br>3. 扩容 Redis 内存 |

### 1.4 系统资源问题

| 症状 | 可能原因 | 快速诊断命令 | 处理步骤 |
|------|----------|--------------|----------|
| CPU 使用率 > 90% | 财务采集批量任务、因子计算密集 | `top -bn1 \| head -20` | 1. 检查是否在执行 financial_p1-p4<br>2. 考虑错峰执行或增加服务器资源<br>3. 优化 SQL 查询或增加索引 |
| 内存不足 (OOM) | WOA 多 Agent 并发、数据缓存过大 | `free -h` / `dmesg \| grep -i oom` | 1. 检查 WOA 进程内存 `ps aux \| grep woa`<br>2. 限制并发数或增加 swap<br>3. 清理 Redis 缓存 |
| 磁盘空间不足 | 日志文件过大、数据备份未清理 | `df -h` / `du -sh logs/*` | 1. 清理旧日志 `find logs/ -name "*.log" -mtime +7 -delete`<br>2. 压缩归档 `gzip logs/*.log`<br>3. 设置日志轮转 (logrotate) |

---

## 2. 故障处理流程

### 2.1 标准处理流程 (SOP)

```
┌─────────────────────────────────────────────────────────────┐
│                    故障发生                                   │
│                      ↓                                      │
│              QQ 告警 / 人工发现                               │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ P0: 关键任务超时？      │──是──→ 立即处理           │
│         │ (woa_audit, etf_spot)  │                          │
│         └────────────────────────┘                          │
│                      ↓否                                    │
│              P1: 普通任务超时                                 │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 1. 查看告警文件         │                          │
│         │    cat /tmp/cron_alert.json                       │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 2. 查看执行状态         │                          │
│         │    jq '.<task>' /tmp/                               │
│         │       cron_exec_status.json                       │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 3. 查看日志             │                          │
│         │    tail -100 logs/                                    │
│         │       cron_dispatcher.log                           │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 4. 手动执行测试         │                          │
│         │    python3 cron_                                    │
│         │       dispatcher.py <task>                          │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 5. 定位根因             │                          │
│         │    - 代码 bug?          │                          │
│         │    - 数据源故障？        │                          │
│         │    - 资源不足？          │                          │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 6. 修复并验证           │                          │
│         │    - 代码修复 → 重新部署 │                          │
│         │    - 数据源恢复 → 重试   │                          │
│         │    - 资源扩容 → 监控     │                          │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 7. 删除告警文件         │                          │
│         │    rm /tmp/cron_alert.json                        │
│         └────────────────────────┘                          │
│                      ↓                                      │
│              故障关闭                                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 优先级定义

| 级别 | 定义 | 响应时间 | 示例任务 |
|------|------|----------|----------|
| **P0** | 影响大盘分析的关键数据缺失 | < 15 分钟 | `woa_audit`, `etf_spot_morning` |
| **P1** | 普通任务超时，可自动补发 | < 30 分钟 | `etf_factor`, `index_eod` |
| **P2** | 非关键任务失败，不影响决策 | < 2 小时 | `financial_p3`, `financial_p4` |
| **P3** | 系统优化建议，无紧急性 | 下一个工作日 | 日志轮转、索引优化 |

### 2.3 手动执行命令参考

```bash
# 查看任务状态
cat /tmp/cron_exec_status.json | jq '.'

# 手动执行单个任务
cd /home/claw/invest-infra/data-pipeline
.venv/bin/python scripts/cron_dispatcher.py <task_name>

# 查看特定任务日志
tail -100 logs/cron_dispatcher.log | grep "<task_name>"

# 清理残留锁文件（谨慎使用）
rm /tmp/cron_lock/<task_name>.lock

# 手动触发看门狗巡检
.venv/bin/python scripts/cron_watchdog.py

# 重新注册 systemd timers
cd /home/claw/invest-infra
python3 setup_systemd_timers.py

# 检查 systemd timer 状态
systemctl --user list-timers --all | grep cia_
```

---

## 3. 监控与告警机制

### 3.1 监控架构

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ systemd      │────→│ cron_dispatcher  │────→│ /tmp/        │
│ timers       │     │ (任务执行)        │     │ cron_exec_   │
│ (触发器)      │     │                  │     │ status.json  │
└──────────────┘     └──────────────────┘     └──────┬───────┘
                                                      │
                                                      ↓
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ OpenClaw     │←────│ cron_watchdog    │←────│ 看门狗巡检    │
│ QQ 推送      │     │ (每小时)          │     │              │
└──────────────┘     └──────────────────┘     └──────────────┘
```

### 3.2 告警阈值配置

| 任务类型 | 期望间隔 | 告警阈值 | 补发阈值 | 最大补发次数 |
|----------|----------|----------|----------|--------------|
| **关键任务** (woa_audit, etf_spot_morning) | 24h | 1.5h | 95min | 2 次 |
| **日内高频** (etf_spot_intraday) | 15min | 20min | 25min | 3 次 |
| **盘后任务** (etf_factor, index_eod 等) | 24h | 45min | 50min | 1 次 |
| **财务采集** (financial_p1-p4) | 24h | 1.5h | 95min | 1 次 |

### 3.3 告警通道

| 通道 | 触发条件 | 内容 | 处理方式 |
|------|----------|------|----------|
| **QQ c2c** | 关键任务超时、systemd timer 缺失 | JSON 格式告警摘要 | 处理后删除 `/tmp/cron_alert.json` |
| **日志文件** | 所有任务执行结果 | 详细 traceback + 退出码 | `tail -f logs/cron_dispatcher.log` |
| **巡检结果** | 每小时看门狗巡检 | `/tmp/cron_watchdog_result.json` | 供心跳读取，不主动推送 |

### 3.4 静音窗口

- **时间**: 23:00 - 08:00（避免夜间打扰）
- **行为**: 仅记录状态到日志和巡检结果文件，不发送 QQ 告警
- **例外**: systemd timer 缺失仍会告警（影响次日执行）

### 3.5 告警去重机制

看门狗使用模块级变量 `_LAST_ALERT_MSG` + `threading.Lock` 实现告警去重：
- 相同内容的告警在单次巡检中只发送一次
- 避免数据源持续故障时频繁骚扰用户

---

## 4. 回滚策略

### 4.1 代码回滚

```bash
# 查看 git 历史
cd /home/claw/invest-infra/data-pipeline
git log --oneline -10

# 回滚到上一个稳定版本
git checkout HEAD~1 -- scripts/cron_dispatcher.py
git checkout HEAD~1 -- scripts/cron_watchdog.py

# 验证回滚结果
python3 scripts/cron_dispatcher.py --help
python3 scripts/cron_watchdog.py --dry-run  # 如果支持
```

### 4.2 配置回滚

| 配置项 | 位置 | 回滚方式 |
|--------|------|----------|
| TASK_MAP | `cron_dispatcher.py` L79-166 | 编辑文件恢复旧映射 |
| 阈值配置 | `cron_watchdog.py` L61-187 | 编辑文件恢复旧阈值 |
| systemd timer | `/home/claw/.config/systemd/user/` | 重新运行 `setup_systemd_timers.py` |

### 4.3 数据回滚

```bash
# PostgreSQL 表数据回滚（需提前准备备份）
psql -h <host> -U <user> -d <db> -c "
  TRUNCATE market_reports RESTART IDENTITY;
  -- 或从备份恢复
  COPY market_reports FROM '/backup/market_reports_20260607.csv' WITH CSV HEADER;
"

# Redis Stream 消息清理（积压严重时）
redis-cli XTRIM <stream_name> MAXLEN ~ 10000

# 日志文件归档（磁盘空间不足时）
cd /home/claw/invest-infra/data-pipeline/logs
find . -name "*.log" -mtime +7 -exec gzip {} \;
```

### 4.4 紧急停机流程

当系统出现严重故障（如数据污染、无限重试）时：

```bash
# 1. 禁用所有 systemd timers
systemctl --user stop cia_*.timer
systemctl --user disable cia_*.timer

# 2. 清理残留锁文件
rm -f /tmp/cron_lock/*.lock

# 3. 清空告警状态（避免重复推送）
rm -f /tmp/cron_alert.json

# 4. 排查问题后重新启用
systemctl --user enable cia_*.timer
systemctl --user start cia_*.timer
```

### 4.5 回滚验证清单

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| systemd timer 状态 | `systemctl --user list-timers --all` | 所有 timer 显示 "active" |
| 任务锁文件 | `ls /tmp/cron_lock/` | 无残留锁（除正在执行的任务） |
| 告警文件 | `cat /tmp/cron_alert.json` | 文件不存在或为空 |
| 日志正常 | `tail -20 logs/cron_dispatcher.log` | 无 error/exception 级别日志 |
| 看门狗巡检 | `.venv/bin/python scripts/cron_watchdog.py` | 返回码 0，无 critical alert |

---

## 附录：关键文件索引

| 文件 | 路径 | 用途 |
|------|------|------|
| 任务调度入口 | `data-pipeline/scripts/cron_dispatcher.py` | 读取 TASK_MAP，执行对应脚本 |
| 看门狗巡检 | `data-pipeline/scripts/cron_watchdog.py` | 每小时巡检，超时补发，写告警 |
| systemd 注册 | `setup_systemd_timers.py` | 注册/重新注册 systemd timers |
| 任务配置文档 | `docs/cron_cia.md` | 任务清单、cron 表达式、架构说明 |
| 执行状态文件 | `/tmp/cron_exec_status.json` | 各任务最新执行状态（JSON） |
| 告警状态文件 | `/tmp/cron_alert.json` | 待处理的告警信息（推送后保留） |
| 巡检结果文件 | `/tmp/cron_watchdog_result.json` | 每小时看门狗巡检结果（供心跳读取） |
| 统一日志 | `data-pipeline/logs/cron_dispatcher.log` | 所有任务执行日志 |
| 看门狗日志 | `data-pipeline/logs/cron_watchdog.log` | 看门狗巡检日志 |
| 锁文件目录 | `/tmp/cron_lock/` | 任务互斥锁（.lock 文件） |

---

> **文档维护**: 每次系统变更（新增任务、修改阈值、调整告警通道）后，需同步更新本手册。  
> **联系支持**: 遇到无法处理的故障，升级至 CIA 或 tech-expert。

---

## 5. 系统全景图

### 5.1 整体架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                    消费层 (Consumption)                      │
│  QQ 推送 ← Morning Briefing ← 盘前/午盘/盘后报 ← 盘中轮询    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    应用层 (Application)                      │
│  Report Engine | WOA Multi-Agent | Signal Calculator        │
│  ETF FQIR Scoring | Sector Filter | Alpha Generation        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    服务层 (Services)                         │
│  PostgreSQL (5432) │ Redis (6379) │ MinIO (9000/9001)       │
│  Silver/Gold 层   │ Cache/MQ    │ Bronze 原始层             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    数据源层 (Data Sources)                   │
│  MCP Tools (wudao_aStock/cls_news)                          │
│  akshare | RSS Feeds | Local Historical DB                  │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 核心服务矩阵

| 服务 | 端口 | 用途 | 持久化 | 关键表/键 |
|:----|:----|:-----|:------|:---------|
| **PostgreSQL** | 5432 | 数据仓库（Silver + Gold 层） | pgdata volume | etfs, etf_quotes, etf_alpha_signals, etf_factor_values, news_articles, investment_memos, lhb_records, industry_info_scores, companies, data_source_log |
| **Redis** | 6379 | 缓存 + 消息队列 (Redis Stream) | redis-data volume | task_queue, cia_task_queue, trading_status cache |
| **MinIO** | 9000/9001 | 对象存储（Bronze 原始层） | minio-data volume | 原始行情数据、生成图表/PDF |

### 5.3 数据流架构 (Lakehouse)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Bronze Layer │────▶│ Silver Layer │────▶│ Gold Layer  │
│ (Raw Data)   │     │ (Cleaned)    │     │ (Aggregated)│
│ MinIO/PG     │     │ PG Tables    │     │ Signals     │
└─────────────┘     └──────────────┘     └─────────────┘
      ▲                    ▲                    │
      │                    │                    ▼
  MCP Tools           Factor Calculators   FQIR Score
  akshare             Signal Pipeline      Candidate Pool
```

**数据流说明**:
1. **Bronze → Silver**: MCP/akshare 采集原始数据 → PG 清洗入库
2. **Silver → Gold**: 因子计算 (F/I/Q/L/R) → ETF FQIR 综合评分
3. **Gold → Consumption**: WOA 多 Agent 协作分析 → CIA 生成洞察 → QQ 推送

### 5.4 核心数据库表 (PostgreSQL investdb)

| 表名 | 用途 | 数据量 | 关键字段 |
|------|------|--------|---------|
| `etfs` | ETF 基本信息 | 1576 只 | code, name, index_code, nav, volume |
| `etf_quotes` | ETF 行情快照 | 每日增量 | code, open, high, low, close, volume, amount |
| `etf_alpha_signals` | ETF FQIR 综合评分 | 1576 行/日 | code, score, I/F/Q/L/R 分项分 |
| `etf_factor_values` | 各维度因子值 | 1576×20 行/日 | code, factor_name, factor_value |
| `news_articles` | 新闻/快讯 (I 维度) | 每日增量 | source, content, publish_time, sentiment |
| `investment_memos` | 投研备忘录 | 人工录入 | author, title, content, tags |
| `lhb_records` | 龙虎榜 | ⚠️ 截止 2023-04 | code, buy_amount, sell_amount |
| `industry_info_scores` | 行业快讯密度 (I 维度) | 30 行/日 | sw_name, news_count, info_score |
| `companies` | A 股公司信息 | 5525 家 | code, name, industry |
| `data_source_log` | 数据源采集日志 | 每日增量 | source, status, record_count, error_msg |

### 5.5 定时任务分布 (18 个 Cron)

| 时段 | 任务数 | 代表任务 | 触发时间 |
|------|--------|---------|---------|
| **早盘** | 5 | Morning Briefing / ETF 盘前报 | 05:50 - 09:35 |
| **午盘/盘后** | 12 | 行业同步 / 因子计算 / Alpha 信号 / 套利信号 | 10:00 - 17:35 |
| **夜盘** | 3 | 财务数据采集 | 18:30 - 20:30 |

---

## 6. 核心智能体档案

### 6.1 Agent 拓扑图

```
┌─────────────────────────────────────────────────────────────┐
│                        CIA (首席投资官)                      │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│   │ WOA      │    │ system-  │    │ data-    │             │
│   │ Multi-   │◀──▶│ architect│◀──▶│ architect│             │
│   │ Agent    │    │ (架构评审)│    │ (数据架构)│             │
│   └──────────┘    └──────────┘    └──────────┘             │
│         ▲                  │                │                │
│         │                  ▼                ▼                │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐             │
│   │ tech-    │    │ 其他     │    │ 外部     │             │
│   │ expert   │    │ 成员     │    │ 数据源   │             │
│   │ (技术实施)│    │          │    │ (MCP/    │             │
│   └──────────┘    └──────────┘    │ akshare) │             │
│                                   └──────────┘             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 核心智能体详细档案

#### 🎯 CIA (Chief Investment Agent) — 首席投资官

| 属性 | 说明 |
|------|------|
| **角色** | 策略综合研判、最终裁量决策 |
| **不负责** | 代码实现、回测执行、风控具体计算 |
| **核心专长** | 投资逻辑分析、市场研判、策略评估、产业链研究 |
| **熟悉领域** | A 股/ETF 市场各类策略优缺点、适用场景和局限性 |
| **工作流** | 接收 WOA 多 Agent 分析结果 → 综合研判 → 生成盘前洞察 → QQ 推送 |
| **触发时间** | 05:50 (Morning Briefing) |
| **输出** | 盘前洞察报告 (QQ 消息) |

#### 🤖 WOA (Workflow Orchestration Agent) — 工作流编排智能体

| 属性 | 说明 |
|------|------|
| **角色** | 多 Agent 协作编排、任务分发与聚合 |
| **核心专长** | A2A 通信、Redis Stream 消息队列、并行子任务调度 |
| **工作模式** | 5 个并行子任务 → 结果聚合 → 通知 CIA |
| **数据流** | task_queue (Redis) → WOA 分发 → cia_task_queue → CIA |
| **关键文件** | `cron_morning_briefing.py` |

#### 🏗️ system-architect — 系统架构分析师 (我)

| 属性 | 说明 |
|------|------|
| **角色** | 系统架构评估、模块设计评审、技术债务分析 |
| **核心专长** | 架构模式识别、模块解耦评估、扩展性分析、可维护性评审 |
| **不负责** | 具体代码实现、数据采集 |
| **当前任务** | SYSTEM_PLAYBOOK.md 维护、架构评审报告输出 |

#### 📊 data-architect — 数据架构师

| 属性 | 说明 |
|------|------|
| **角色** | 数据流分析、数据源整合、数据模型设计 |
| **核心专长** | 数据建模、ETL 设计、数据质量管理、多数据源融合策略 |
| **不负责** | 业务策略制定 |
| **当前任务** | 现有 Morning Briefing 数据流分析、数据库架构评审 |

#### ⚙️ tech-expert — 技术实施专家

| 属性 | 说明 |
|------|------|
| **角色** | 技术方案可行性评估、实施难度和风险判断 |
| **核心专长** | Python 技术栈、数据管道设计、定时任务调度、API 集成、数据库设计 |
| **不负责** | 投资决策、策略分析 |
| **当前任务** | 新汇报模块技术分析、实施路径规划、故障处理手册 |

### 6.3 Agent 协作模式

| 场景 | 参与 Agent | 通信方式 | 输出 |
|------|-----------|---------|------|
| **Morning Briefing** | WOA → CIA | Redis Stream + A2A | QQ 盘前洞察 |
| **架构评审** | system-architect + data-architect + tech-expert → CIA | send_message (多播/广播) | 架构评审报告 |
| **技术实施** | tech-expert → WOA/CIA | send_message + 代码提交 | 功能模块 |

---

## 7. 模块职责矩阵

### 7.1 业务模块 (5 个)

| 模块 | 负责人 | 核心职责 | 输入 | 输出 |
|------|--------|---------|------|------|
| **Morning Briefing** | WOA + CIA | 盘前洞察生成 | PG 数据 + MCP | QQ 推送 |
| **ETF FQIR 评分** | tech-expert | 五维因子计算 + 综合评分 | etf_quotes + industry_info_scores | etf_alpha_signals |
| **行业快讯密度** | data-architect | I 维度信息因子 | cls_news MCP | industry_info_scores |
| **套利信号** | tech-expert | 跨市场套利机会识别 | ETF + 成分股行情 | 套利信号表 |
| **新汇报模块** | tech-expert (实施) | 盘前/午盘/盘后/盘中报 | MCP + PG | QQ 推送 + DB 存储 |

### 7.2 技术模块 (12 个)

| 模块 | 路径 | 职责 | 依赖 |
|------|------|------|------|
| **信号计算** | `src/signals/` | ETF FQIR 综合评分、候选池过滤 | etf_alpha.py, scoring.py |
| **因子计算 - F** | `src/factors/etf_fundamental.py` | 行业情绪因子 (F 维度) | sync_sw_industry.py |
| **因子计算 - I** | `src/factors/etf_info_flow.py` | 信息因子 (I 维度) | industry_info_scores |
| **因子计算 - Q** | `src/factors/etf_fundamental.py` | 财务质量因子 (Q 维度) | companies.industry |
| **因子计算 - L** | `src/factors/etf_liquidity.py` | 流动性因子 (L 维度) | etf_quotes |
| **因子计算 - R** | `src/factors/etf_risk.py` | 风险因子 (R 维度) | etf_quotes (HV/回撤) |
| **数据采集** | `src/collector/` | akshare/MCP 数据抓取 | akshare, MCP client |
| **数据管道** | `src/pipeline/` | ETL 流程编排 | PostgreSQL psycopg2 |
| **回测引擎** | `src/backtest/` | 策略历史回测 | etf_factor_values |
| **数据加载** | `src/loader/` | 批量数据导入导出 | CSV/JSON/PG |
| **WOA 任务** | `scripts/woa_tasks/` | Morning Briefing 子任务定义 | Redis Stream |
| **报告引擎** | `scripts/report_engine.py` | (新模块) 统一报告生成 | MCP + PG |

### 7.3 Cron 定时任务详细职责表 (18 个)

| 任务名 | 时间 | 频率 | 数据源 | 输出 | 负责人 |
|--------|------|------|--------|------|--------|
| `cia_morning_briefing` | 05:50 | 周一~五 | PG + MCP | QQ 盘前洞察 | WOA + CIA |
| `cia_etf_pre_market` | 08:30 | 周一~五 | PG | ETF 盘前报 | tech-expert |
| `cia_sw_industry_sync` | 15:35 | 周一~五 | akshare | industry_info_scores | data-architect |
| `cia_industry_info_sync` | 15:50 | 周一~五 | cls_news MCP | industry_info_scores | data-architect |
| `cia_etf_alpha_signal` | 16:00 | 周一~五 | PG (全量因子) | etf_alpha_signals | tech-expert |
| `cia_arbitrage_signal` | 16:30 | 周一~五 | ETF + 成分股 | 套利信号表 | tech-expert |
| `cia_sector_filter` | 17:00 | 周一~五 | etf_alpha_signals | 候选池 Top5 | CIA |
| `cia_financial_data_sync` | 18:30 | 周一~五 | akshare | companies (财务数据) | data-architect |
| `cia_news_collection` | 19:00 | 每日 | RSS/News API | news_articles | data-architect |
| `cia_etf_quote_sync` | 20:00 | 每日 | akshare | etf_quotes (日终) | tech-expert |
| `cia_lhb_sync` | 20:30 | 每日 | akshare | lhb_records | data-architect |
| `cia_data_quality_check` | 21:00 | 每日 | PG 全表 | data_source_log | system-architect |
| `cia_backup_pg` | 22:00 | 每日 | PostgreSQL | pg_dump 文件 | tech-expert |
| `cia_cleanup_temp` | 03:00 | 每日 | 临时目录 | 清理日志/缓存 | tech-expert |
| `cia_report_generation` | 08:30/11:30/15:30 | 交易日 | MCP + PG | 统一报告 | tech-expert (新) |
| `cia_intraday_alert` | 每小时 (交易时段) | 交易时段 | MCP 实时数据 | intraday_alerts | tech-expert (新) |
| `cia_weekly_summary` | 周五 17:00 | 每周 | PG 聚合 | 周报 | CIA |
| `cia_monthly_review` | 月末最后一个交易日 | 每月 | PG 聚合 | 月报 | CIA |

---

## 8. 关键决策日志

### 8.1 架构决策记录 (ADR)

#### ADR-001: 采用 PostgreSQL + Redis + MinIO 三服务架构

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-02 |
| **背景** | Phase 0 基础设施选型，需要持久化、缓存、对象存储 |
| **决策** | PostgreSQL (关系型数据) + Redis (缓存/消息队列) + MinIO (原始数据) |
| **理由** | 1. PG 成熟稳定，支持复杂查询；2. Redis 低延迟，适合实时数据；3. MinIO S3 兼容，成本低 |
| **后果** | ✅ 运维简单，社区支持好；⚠️ 需要维护 3 个服务实例 |

#### ADR-002: WOA 多 Agent 协作模式用于 Morning Briefing

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-03 |
| **背景** | 盘前洞察需要多维度分析 (技术面/基本面/消息面) |
| **决策** | WOA 编排 5 个并行子任务 → 结果聚合 → CIA 综合研判 |
| **理由** | 1. 并行处理提升效率；2. 多视角分析更全面；3. CIA 最终裁量保证质量 |
| **后果** | ✅ 分析质量高；⚠️ Redis Stream 消息队列需要监控，避免堆积 |

#### ADR-003: ETF FQIR 五维评分体系 (F/I/Q/L/R)

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-02 |
| **背景** | 需要量化评估 ETF 投资价值 |
| **决策** | F(行业情绪) + I(信息因子) + Q(财务质量) + L(流动性) + R(风险) |
| **理由** | 1. 覆盖投资核心维度；2. 权重可配置 (F:20%, I:5%, Q:15%, L:15%, R:15%)；3. 支持扩展 |
| **后果** | ✅ 评分体系完整；⚠️ I 维度依赖 MCP 每日 50 次限额，需优化 |

#### ADR-004: 新汇报模块采用统一报告引擎 (v2.0)

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-07 |
| **背景** | 盘前/午盘/盘后/盘中报需要整合，避免重复开发 |
| **决策** | 统一 report_engine.py + modular reporters，三阶段演进路径 (22h) |
| **理由** | 1. 代码复用率高；2. 数据源优先级规则清晰；3. 与 Morning Briefing 可整合 |
| **后果** | ✅ 架构简洁；⚠️ MCP 单点故障风险，需加熔断机制 |

#### ADR-005: 数据融合仲裁规则 — MCP 值优先，Morning Briefing 摘要兜底

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-07 |
| **背景** | 新汇报模块与 Morning Briefing 数据源可能冲突 |
| **决策** | 数值型数据用 MCP (wudao_aStock)，摘要/观点用 Morning Briefing 分析结果 |
| **理由** | 1. MCP 实时性更好；2. Morning Briefing 有深度分析；3. 分工明确避免重复 |
| **后果** | ✅ 数据一致性高；⚠️ 需要 adapter 层处理格式转换 |

### 8.2 技术债务清单 (P0-P4)

| 优先级 | 债务项 | 影响 | 建议解决时间 | 负责人 |
|--------|--------|------|-------------|--------|
| **P0** | I 维度 MCP 每日 50 次限额 | 行业快讯密度计算可能中断 | 2026-06-10 | data-architect |
| **P0** | 新汇报模块 MCP 单点故障 | 报告生成失败无降级方案 | 2026-06-15 | tech-expert |
| **P1** | intraday_alerts 去重约束 (v2.0 已修复) | 重复告警 | 已完成 | tech-expert |
| **P1** | JSON 字段缺少 GIN 索引 | 查询性能下降 | 2026-06-20 | tech-expert |
| **P1** | 缺少审计字段 (created_by/updated_at) | 数据追溯困难 | 2026-07-01 | tech-expert |
| **P2** | QQ 消息长度限制 (2000 字符) | 长报告被截断 | 2026-07-15 | tech-expert |
| **P2** | lhb_records 数据截止 2023-04 | 龙虎榜分析失效 | 2026-08-01 | data-architect |
| **P3** | Redis Stream 无持久化配置 | 重启后消息丢失 | 2026-07-01 | tech-expert |
| **P4** | docs/cron_cia.md 未更新 | 文档与实现不一致 | 2026-08-01 | system-architect |

### 8.3 实施里程碑

| 里程碑 | 目标 | 预计完成 | 状态 |
|--------|------|---------|------|
| **M1: Phase 0 基础设施** | PG/Redis/MinIO 部署 + 基础表结构 | 2026-06-03 | ✅ 已完成 |
| **M2: FQIR 评分体系** | 五维因子计算 + 综合评分 | 2026-06-05 | ✅ 已完成 |
| **M3: Morning Briefing** | WOA 多 Agent 协作 + QQ 推送 | 2026-06-06 | ✅ 已完成 |
| **M4: 架构评审 v1.0** | 现有系统分析 + 新模块分析 | 2026-06-07 | ✅ 已完成 |
| **M5: 架构评审 v2.0** | 整合方案 + 实施路径 (22h) | 2026-06-07 | ✅ 已完成 |
| **M6: SYSTEM_PLAYBOOK** | 运维手册 + Agent 档案 + 决策日志 | 2026-06-07 | 🔄 进行中 |
| **M7: 新汇报模块 Phase 1** | 独立试运行 (9h) | 2026-06-15 | ⏳ 待启动 |
| **M8: 新汇报模块 Phase 2** | 双轨运行 (6h) | 2026-06-22 | ⏳ 待启动 |
| **M9: 统一报告引擎上线** | 终态架构 (7h) | 2026-06-30 | ⏳ 待启动 |

### 8.4 风险登记册

| 风险 ID | 风险描述 | 概率 | 影响 | 缓解措施 | 负责人 |
|---------|---------|------|------|---------|--------|
| **R01** | MCP API 限额耗尽导致 I 维度计算失败 | 高 | 中 | 1. 优化调用策略；2. 缓存结果；3. 降级为默认分 | data-architect |
| **R02** | MCP 服务不可用导致新汇报模块全部失败 | 中 | 高 | 1. 熔断机制；2. Redis 缓存兜底；3. 告警通知 | tech-expert |
| **R03** | Redis Stream 消息堆积导致 Morning Briefing 延迟 | 低 | 高 | 1. 监控队列长度；2. 自动扩容 WOA 实例；3. 降级为单 Agent | CIA |
| **R04** | PostgreSQL 磁盘空间不足 | 中 | 高 | 1. 定期清理历史数据；2. 表分区；3. 监控告警 | tech-expert |
| **R05** | QQ 推送失败 (网络/账号问题) | 低 | 中 | 1. 重试机制；2. 备用推送渠道；3. 日志记录 | CIA |

---

## 附录：快速启动命令

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 进入 PostgreSQL
docker exec -it <pg_container> psql -U invest_user -d investdb

# 查看 Cron 任务状态
systemctl list-timers | grep cia_

# 查看 Redis 队列长度
redis-cli llen task_queue
```

## 附录：关键文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| README.md | `/home/claw/invest-infra/README.md` | 系统架构总览 |
| progress.md | `/home/claw/invest-infra/data-pipeline/progress.md` | FQIR 实施日志 |
| cron_cia.md | `/home/claw/invest-infra/docs/cron_cia.md` | CIA 定时任务手册 |
| SYSTEM_PLAYBOOK.md | `/home/claw/invest-infra/SYSTEM_PLAYBOOK.md` | 本文件 (运维手册) |
| architecture_review_report_v2.md | `/home/claw/invest-infra/evaluation_reports/` | v2.0 架构评审报告 |

## 附录：联系方式

| 角色 | Agent | 职责范围 |
|------|-------|---------|
| 首席投资官 | CIA | 策略决策、最终裁量 |
| 技术实施专家 | tech-expert | 代码实现、技术风险 |
| 数据架构师 | data-architect | 数据流、数据模型 |
| 系统架构分析师 | system-architect | 架构评审、模块设计 |

---

*文档维护: system-architect (架构评审团队)*  
*最后更新: 2026-06-07*  
*版本: v1.0*
