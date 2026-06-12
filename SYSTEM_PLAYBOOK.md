# CIA 定时任务系统 — 故障处理手册 (SYSTEM PLAYBOOK)

> **版本**: v1.1 | **更新日期**: 2026-06-12  
> **维护者**: system-architect（文档） + tech-expert（实现） + Arc（修复执行） + RAA（独立审计）  
> **审计触发**: 2026-06-12 08:37 RAA 系统说明审计  
> **适用范围**: 所有定时任务运维人员

> **v1.1 变更**：详见 `../CHANGELOG.md`（RAA 审计 + 修复触发）
> - 头元信息刷新（版本/日期/维护者）
> - §5 系统全景图：数据库表 10 → 43；任务数 22 → 47；删除已合并的 `briefing_dispatch`
> - §6 Agent 拓扑：补 RAA + Arc
> - §7 模块矩阵：修正 L 维度路径（`etf_liquidity.py` → `etf.py`）、报告引擎路径（`scripts/` → `src/reports/`）
> - §8.2 技术债务：补 RAA 6 个 fix
> - §8.3 里程碑：M6 标 ✅ 完成；M7 标 ✅ 已实质完成

---

## 目录

1. [常见问题速查表](#1-常见问题速查表)
2. [故障处理流程](#2-故障处理流程)
3. [监控与告警机制](#3-监控与告警机制)
4. [回滚策略](#4-回滚策略)
5. [系统全景图](#5-系统全景图) ← v1.1 大幅修订
6. [核心智能体档案](#6-核心智能体档案) ← v1.1 补 RAA + Arc
7. [模块职责矩阵](#7-模块职责矩阵) ← v1.1 路径修订
8. [关键决策日志](#8-关键决策日志) ← v1.1 补 RAA fix + 里程碑刷新

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
| MCP 服务不可用 | wudao_aStock/cls_news MCP 接口故障 | 检查 MCP 路由 + 调用方日志 | 1. 降级到本地缓存<br>2. 触发熔断<br>3. RAA 通知修复 Agent 排查 |

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
│         │ 7. 严重问题 → RAA 审计 │  ← v1.1 新增              │
│         │    - 写 raa-audit-*.md  │                          │
│         │    - Arc 修复           │                          │
│         │    - RAA Re-Audit       │                          │
│         └────────────────────────┘                          │
│                      ↓                                      │
│         ┌────────────────────────┐                          │
│         │ 8. 删除告警文件         │                          │
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

# 重新注册 systemd timers（47 个，含 ETF 日内 24 个）
cd /home/claw/invest-infra
python3 setup_systemd_timers.py

# 检查 systemd timer 状态
systemctl --user list-timers --all | grep cia_

# RAA 触发审计（用户显式调用后）
# 写 raa-audit-*.md 到 raa-audit-readonly 软链接
```

---

## 3. 监控与告警机制

### 3.1 监控架构

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│ systemd      │────→│ cron_dispatcher  │────→│ /tmp/        │
│ timers       │     │ (任务执行)        │     │ cron_exec_   │
│ (47 个)      │     │                  │     │ status.json  │
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
| **日内高频** (etf_spot_intraday, 24 个 etf_intra_*) | 15min | 20min | 25min | 3 次 |
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

### 3.6 RAA Re-Audit 触发链路（v1.1 新增）

```
RAA 审计发现 P0/P1 finding
    ↓
RAA 写 raa-audit-<scope>-<YYYYMMDD>.md
    ↓
RAA 写 handoff/raa-handoff-<scope>-<YYYYMMDD>.md（含修复建议 + 责任分配）
    ↓
用户调度 Arc（修复 Agent）执行修复
    ↓
Arc 修复完成 → 写 .raa-fix-status.json（status: fixed-pending-verify）
    ↓
用户调度 RAA Re-Audit
    ↓
RAA 验证 → 更新 status（verified / partial / not-fixed）
```

详见 `AGENTS.md §6.2`（RAA 同步协议）+ `memory/audits/` 历史报告。

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
| TASK_MAP | `cron_dispatcher.py` L94-200 | 编辑文件恢复旧映射 |
| 阈值配置 | `cron_watchdog.py` L61-187 | 编辑文件恢复旧阈值 |
| systemd timer | `/home/claw/.config/systemd/user/` | 重新运行 `setup_systemd_timers.py` |
| RAA 修复状态 | `/home/claw/invest-infra/.raa-fix-status.json` | 谨慎修改，破坏协议 |

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
# 1. 禁用所有 systemd timers（47 个）
systemctl --user stop cia_*.timer
systemctl --user disable cia_*.timer

# 2. 清理残留锁文件
rm -f /tmp/cron_lock/*.lock

# 3. 清空告警状态（避免重复推送）
rm -f /tmp/cron_alert.json

# 4. 排查问题后重新启用
systemctl --user enable cia_*.timer
systemctl --user start cia_*.timer

# 5. 严重问题 → 触发 RAA 审计
# 写 raa-handoff-*.md 到 /home/claw/.openclaw/workspace-audit/memory/handoff/
```

### 4.5 回滚验证清单

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| systemd timer 状态 | `systemctl --user list-timers --all` | 所有 47 个 cia_*.timer 显示 "active" |
| 任务锁文件 | `ls /tmp/cron_lock/` | 无残留锁（除正在执行的任务） |
| 告警文件 | `cat /tmp/cron_alert.json` | 文件不存在或为空 |
| 日志正常 | `tail -20 logs/cron_dispatcher.log` | 无 error/exception 级别日志 |
| 看门狗巡检 | `.venv/bin/python scripts/cron_watchdog.py` | 返回码 0，无 critical alert |

---

## 附录：关键文件索引

| 文件 | 路径 | 用途 | v1.1 状态 |
|------|------|------|-----------|
| 任务调度入口 | `data-pipeline/scripts/cron_dispatcher.py` | 读取 TASK_MAP（L94-200），执行对应脚本 | ✅ |
| 看门狗巡检 | `data-pipeline/scripts/cron_watchdog.py` | 每小时巡检，超时补发，写告警 | ✅ |
| systemd 注册 | `setup_systemd_timers.py` | 注册 16 SINGLE + 24 etf_intra + 1 watchdog = 41 timer | ✅ |
| 独立 timer | `setup_cron_timers.sh` | 旧版 5 个独立 timer（pre_market/midday/post_market/market_collect*）| ⚠️ 建议合并到 setup_systemd_timers.py |
| 任务配置文档 | `docs/cron_cia.md` | 任务清单、cron 表达式、架构说明 | ✅ |
| 执行状态文件 | `/tmp/cron_exec_status.json` | 各任务最新执行状态（JSON） | ✅ |
| 告警状态文件 | `/tmp/cron_alert.json` | 待处理的告警信息（推送后保留） | ✅ |
| 巡检结果文件 | `/tmp/cron_watchdog_result.json` | 每小时看门狗巡检结果（供心跳读取） | ✅ |
| 统一日志 | `data-pipeline/logs/cron_dispatcher.log` | 所有任务执行日志 | ✅ |
| 看门狗日志 | `data-pipeline/logs/cron_watchdog.log` | 看门狗巡检日志 | ✅ |
| 锁文件目录 | `/tmp/cron_lock/` | 任务互斥锁（.lock 文件） | ✅ |
| **RAA 修复状态** | `/home/claw/invest-infra/.raa-fix-status.json` | Arc 写入，RAA 只读 | ✅ v1.1 新增引用 |
| **RAA 审计目录** | `raa-audit-readonly` 软链接 | → `/home/claw/.openclaw/workspace-audit/memory/audits/` | ✅ v1.1 新增 |
| **RAA 移交目录** | `raa-handoff-readonly` 软链接 | → `/home/claw/.openclaw/workspace-audit/memory/handoff/` | ✅ v1.1 新增 |

---

> **文档维护**: 每次系统变更（新增任务、修改阈值、调整告警通道）后，**必须**同步更新本手册并刷版本号。  
> **联系支持**: 遇到无法处理的故障，先升级至 CIA / tech-expert；涉及代码/数据 bug 由 Arc 修复，由 RAA 独立审计。

---

## 5. 系统全景图

### 5.1 整体架构分层

```
┌─────────────────────────────────────────────────────────────┐
│                    消费层 (Consumption)                      │
│  QQ 推送 ← Morning Briefing ← 盘前/午盘/盘后报 ← 盘中轮询    │
│  ↓                                                            │
│  RAA 审计报告 ← handoff ← 修复移交 ← Arc 修复执行            │ ← v1.1
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
| **PostgreSQL** | 5432 | 数据仓库（Silver + Gold 层） | pgdata volume | 43 张公关表（详见 §5.4） |
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
4. **Gold → RAA → Arc**（v1.1 新增）: 信号异常/计算偏差 → RAA 审计 → Arc 修复 → Re-Audit

### 5.4 核心数据库表 (PostgreSQL investdb) — v1.1 实际盘点

**总表数：43 张**（v1.0 误为 10 张；详见 README.md §数据库）

| 表名 | 用途 | 数据量/状态 | 关键字段 |
|------|------|---------|---------|
| `etfs` | ETF 基本信息 | **1843 只** | code, name, index_code, nav, volume |
| `etf_quotes` | ETF 行情快照 | 每日增量 | code, open, high, low, close, volume, amount |
| `etf_alpha_signals` | ETF FQIR 综合评分 | 累计 15617+ | code, composite_score, I/F/Q/L/R 分项, signal |
| `etf_factor_values` | 因子原始值 | 累计 12297+ | code, premium_rate, iopv_diff, liquidity_score |
| `etf_fundamental_scores` | F 维度子分 | 累计 1829+ | etf_id, calc_date, factor_value |
| `etf_info_scores` | I 维度子分 | 累计 2684+ | etf_id, news_sentiment, news_count, policy_support |
| `etf_risk_scores` | R 维度子分 | 累计 1489+ | etf_id, calc_date, factor_value |
| `etf_quant_scores` | Q 维度子分 | **0 行（未投入使用）** | etf_id, calc_date, factor_value |
| `etf_arbitrage_signals` | 套利信号 | 每日增量 | code, signal_type, premium, expected_return |
| `etf_health_alerts` | ETF 健康检查告警 | 每日增量 | code, alert_type, severity, message |
| `etf_sw_industry_sentiment` | 申万行业情绪 | 每日增量 | sw_code, sw_name, sentiment_score |
| `daily_quotes` | 个股日线 | 每日增量 | code, open, close, volume, amount |
| `daily_market_snapshot` | 全市场快照 | 每日 | snapshot_date, market_breadth, etc. |
| `index_quotes` / `indices` | 指数行情 / 基本信息 | 每日增量 | code, close, change_pct |
| `companies` | A 股公司信息 | **5525 家** | code, name, industry, area |
| `news_articles` | 新闻/快讯 (I 维度源) | 累计 6027 / 最新 2026-06-01 ⚠️ | source, title, content, sentiment |
| `industry_info_scores` | 申万行业快讯密度 | 156 行 / 最新 2026-06-11 | sw_name, news_count, info_score |
| `financial_reports` | 财报数据 (p1-p4 采集) | 每日增量 | code, report_period, revenue, profit |
| `fund_flow_big_deal` | 大单资金流 | 每日增量 | code, big_deal_amount, direction |
| `stock_daily_fund_flow` | 个股日资金流 | 每日增量 | code, main_net, retail_net |
| `lhb_records` | 龙虎榜 | ⚠️ **截止 2023-04-17** | code, listing_date, buy_amount, sell_amount |
| `cov_bond_link` | 可转债联动 | 每日增量 | bond_code, stock_code, conversion_rate |
| `north_turnover_hist` / `south_flow_hist` | 沪深港通历史 | 每日增量 | trade_date, north_buy, north_sell |
| `factor_definitions` | 因子定义字典 | 静态 | factor_key, name, category, formula_desc |
| `factor_weights` | 因子权重 | 静态 | factor_key, category, weight, norm_direction |
| `factor_values` | 因子计算结果（DB 化）| 累计 38962 / 最新 2026-06-01 ⚠️ | company_id, factor_id, calc_date, value |
| `backtest_runs` | 回测运行 | 历史 | run_id, strategy_name, params |
| `backtest_results` | 回测明细 | 历史 | run_id, trade_date, pnl |
| `backtest_summary` | 回测汇总 | 历史 | run_id, sharpe, max_drawdown, total_return |
| `market_reports` | 报告存档 | 每日 | report_type, content, push_status |
| `report_subscriptions` | 报告订阅 | 静态 | user_id, report_type, channel |
| `sector_filter_candidates` | 板块筛选候选 | 每日增量 | sector, code, score |
| `sector_filter_reports` | 板块筛选报告 | 每日 | report_date, sector, recommendations |
| `intraday_alerts` | 日内告警 | 每日增量 | code, alert_type, message, dedup_key |
| `investment_memos` | 投研备忘录 | 累计 111 | author, title, content, tags |
| `user_portfolios` | 用户自选/持仓 | 静态 | user_id, code, shares, cost |
| `alpha_signals` / `analysis_signals` | 旧版信号表 | 历史 | ⚠️ 建议评估后归档 |
| `data_source_log` | 数据源采集日志 | 每日增量 | source, status, record_count, error_msg |
| `scheduler_jobs` | 任务执行追踪 | 每日 | job_name, status, started_at, finished_at |
| `task_queue` | 任务队列（Redis 镜像）| 实时 | task_id, payload, status |

### 5.5 定时任务分布 — v1.1 实际盘点

> v1.0 误为 22 个；v1.1 实际：**47 个 systemd user timers**（其中 5 个由 `setup_cron_timers.sh` 注册，不在 `setup_systemd_timers.py` 中）

| 类别 | 任务数 | 来源 | 说明 |
|------|--------|------|------|
| **业务 SINGLE** | 16 | `setup_systemd_timers.py` SINGLE_TASKS | 早盘 briefing + 收盘因子 + 财务分批 |
| **业务 ETF 日内** | 24 | `setup_systemd_timers.py` 派生 | `etf_intra_1000 ~ etf_intra_1545`，每 15min 调 `etf_spot_intraday` |
| **业务 独立 timer** | 5 | `setup_cron_timers.sh` / 手动 | `pre_market / midday / post_market / market_collect / market_collect_midday` |
| **系统守护** | 1 | `setup_systemd_timers.py` WATCHDOG | `watchdog`（每小时） |
| **其他** | 1 | 手动注册 | `memory_audit`（待核实用途） |
| **合计** | **47** | | |

**业务任务时段分布：**

| 时段 | 任务数 | 代表任务 | 触发时间 |
|------|--------|---------|----------|
| **早盘** | **5**（v1.0 误为 4）| Morning Briefing / WOA Audit / ETF 盘前 / ETF 日内 09:35 / Pre-market | 05:50 - 09:35 |
| **盘中（ETF 日内）** | 24 | etf_intra_1000 ~ etf_intra_1545 | 10:00 - 15:45 每 15min |
| **午盘** | 1 | midday | 12:00 |
| **午盘/盘后** | 11 | market_collect / sw_industry / etf_kline / industry_info / index_eod / etf_factor / etf_alpha / etf_health / etf_arbitrage / market_collect_midday / post_market | 10:00 - 17:35 |
| **夜盘** | 4 | financial_p1 / p2 / p3 / p4 | 14:00 - 20:30 |
| **守护** | 1 | watchdog | 每整点 |

> **v1.0 错误说明**：早盘 4 / 午盘 12 / 夜盘 4 = 20 算术不闭合（漏算独立 5 个 timer）；v1.1 已重算并以 47 个 timer 为准。

---

## 6. 核心智能体档案

### 6.1 Agent 拓扑图（v1.1 补全）

```
┌─────────────────────────────────────────────────────────────────┐
│                        CIA (首席投资官)                          │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│   │ WOA      │    │ system-  │    │ data-    │                  │
│   │ Multi-   │◀──▶│ architect│◀──▶│ architect│                  │
│   │ Agent    │    │ (架构评审)│    │ (数据架构)│                  │
│   └──────────┘    └──────────┘    └──────────┘                  │
│         ▲                  │                │                     │
│         │                  ▼                ▼                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│   │ tech-    │    │ 其他     │    │ 外部     │                  │
│   │ expert   │    │ 成员     │    │ 数据源   │                  │
│   │ (技术实施)│    │          │    │ (MCP/    │                  │
│   └──────────┘    └──────────┘    │ akshare) │                  │
│                                   └──────────┘                  │
└─────────────────────────────────────────────────────────────────┘
         ▲                ▲                    ▲
         │                │                    │
         │  审计/移交/修复链路（v1.1 新增）        │
         │                │                    │
┌────────┴─────┐  ┌──────┴───────┐  ┌──────────┴─────┐
│ RAA          │  │ Arc          │  │ RAA            │
│ (Research    │◀─│ (修复 Agent) │─▶│ Re-Audit       │
│  Audit Agent)│  │ 写 fix-status│  │ (循环)         │
└──────────────┘  └──────────────┘  └────────────────┘
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
| **关键文件** | `data-pipeline/scripts/cron_morning_briefing.py` |
| **v1.0 → v1.1 修正** | 路径补全为 `data-pipeline/scripts/cron_morning_briefing.py`（v1.0 漏 `data-pipeline/` 前缀） |

#### 🏗️ system-architect — 系统架构分析师

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

#### 🔧 Arc — 修复执行 Agent（v1.1 新增）

| 属性 | 说明 |
|------|------|
| **角色** | 根据 RAA 审计发现执行代码/配置修复 |
| **核心专长** | 快速 patch、权限修复、依赖修复、回归验证 |
| **输入** | RAA handoff 文档（含 finding_id + 修复建议 + 责任分配）|
| **输出** | Git commit + `.raa-fix-status.json` 状态写入（status: fixed-pending-verify）|
| **不负责** | 投资决策、策略分析、独立审计（避免自审自修）|
| **当前任务** | P0-RAA-1（PG 密码硬编码）/ P0-RAA-2（pre_market re 模块未导入）/ P0-RAA-3（financial_p1-p4 超时）/ RAA-2（.env 权限）/ RAA-5（report_engine 强校验 env）/ TRACE-P2->P0（WOA→CIA 明文密码）|

#### 🛡️ RAA (Research Audit Agent) — 独立审计 Agent（v1.1 新增）

| 属性 | 说明 |
|------|------|
| **角色** | 投研系统所有关键输出的独立第三方审计 |
| **核心专长** | 数据完整性、因子复算、回测一致性、可复现性、模型稳定性 |
| **不负责** | 投研决策、代码修复、修复执行（保持独立性）|
| **工作流** | 读取 invest-infra 产物 → 写 `memory/audits/raa-audit-*.md` → 写 `memory/handoff/raa-handoff-*.md` → 等用户调度 Arc 修复 → Re-Audit |
| **触发** | 用户显式指令（**RAA 不主动巡检**）|
| **位置** | `/home/claw/.openclaw/workspace-audit/`（命名空间隔离）|
| **核心协议** | 边界铁律 §6.3 / 模糊指令澄清 §6.5 / 同步协议 §6.2 / 调度协议 §6.4 |
| **当前位置** | `AGENTS.md §7`（投研系统锚点）|

### 6.3 Agent 协作模式（v1.1 补全）

| 场景 | 参与 Agent | 通信方式 | 输出 |
|------|-----------|---------|------|
| **Morning Briefing** | WOA → CIA | Redis Stream + A2A | QQ 盘前洞察 |
| **架构评审** | system-architect + data-architect + tech-expert → CIA | send_message (多播/广播) | 架构评审报告 |
| **技术实施** | tech-expert → WOA/CIA | send_message + 代码提交 | 功能模块 |
| **RAA 审计 → 修复移交**（v1.1 新增）| RAA → user → Arc | `memory/handoff/raa-handoff-*.md` + `.raa-fix-status.json` | 修复完成 + Re-Audit 通过 |
| **修复 Re-Audit**（v1.1 新增）| user → RAA | `memory/audits/raa-reaudit-*.md` | 验证通过 / 部分通过 / 未通过 |

---

## 7. 模块职责矩阵

### 7.1 业务模块 (5 个)

| 模块 | 负责人 | 核心职责 | 输入 | 输出 |
|------|--------|---------|------|------|
| **Morning Briefing** | WOA + CIA | 盘前洞察生成 | PG 数据 + MCP | QQ 推送 |
| **ETF FQIR 评分** | tech-expert | 五维因子计算 + 综合评分 | etf_quotes + industry_info_scores | etf_alpha_signals |
| **行业快讯密度** | data-architect | I 维度信息因子 | cls_news MCP | industry_info_scores |
| **套利信号** | tech-expert | 跨市场套利机会识别 | ETF + 成分股行情 | etf_arbitrage_signals |
| **新汇报模块** | tech-expert (实施) | 盘前/午盘/盘后/盘中报 | MCP + PG | QQ 推送 + DB 存储（market_reports） |

### 7.2 技术模块 (12 个) — v1.1 路径修订

| 模块 | 路径（v1.1 修正） | 职责 | 依赖 |
|------|------|------|------|
| **信号计算** | `data-pipeline/src/signals/` | ETF FQIR 综合评分、套利信号、候选池过滤 | `etf_alpha.py` / `etf_arbitrage.py` / `scoring.py` / `alpha.py` |
| **因子计算 - F** | `data-pipeline/src/factors/etf_fundamental.py` | 行业情绪因子 (F 维度) | `sync_sw_industry.py` |
| **因子计算 - I** | `data-pipeline/src/factors/etf_info_flow.py` | 信息因子 (I 维度) | `industry_info_scores` |
| **因子计算 - Q** | `data-pipeline/src/factors/etf_fundamental.py`（Q 分支）| 财务质量因子 (Q 维度) | `companies.industry` |
| **因子计算 - L** | `data-pipeline/src/factors/etf.py` ← **v1.1 修正** | 流动性因子（L 维度，含 premium_rate/iopv/liquidity_score）| `etf_quotes` |
| ~~因子计算 - L~~ | ~~`src/factors/etf_liquidity.py`~~ | **v1.0 错误路径，文件不存在** | — |
| **因子计算 - R** | `data-pipeline/src/factors/etf_risk.py` | 风险因子 (R 维度) | `etf_quotes` (HV/回撤) |
| **数据采集** | `data-pipeline/src/collector/` | akshare/MCP/cifang/companies/etf/financial/news/quotes/research_report/rsscast/retry/etf_health_monitor 数据抓取 | akshare, MCP client, cifang API |
| **数据管道** | `data-pipeline/src/pipeline/` | 任务调度追踪 + 错误隔离（`scheduler_jobs.py` + `error_isolation.py`）| PostgreSQL `psycopg2` |
| **回测引擎** | `data-pipeline/src/backtest/` | 策略历史回测（engine/analyzers/feeds/strategies/report）| `etf_factor_values` |
| **数据加载** | `data-pipeline/src/loader/` | 批量数据导入导出 | `pg.py` / `minio.py` |
| **WOA 任务** | `data-pipeline/scripts/woa_tasks/` ← **v1.1 路径补全** | Morning Briefing 子任务定义 | Redis Stream |
| **报告引擎** | `data-pipeline/src/reports/` ← **v1.1 路径修正** | 统一报告生成（report_engine + formatters + modules + qq_push + db + mcp_client + market_data_*）| MCP + PG |

### 7.3 Cron 定时任务详细职责表（v1.1 修正）

> **v1.1 实际状态：47 个 systemd user timers**（v1.0 误为 22 个）

**业务调度任务（20 个 · 经 TASK_MAP）：**

| 任务名 | 触发时间 | 触发方式 | 说明 |
|--------|----------|---------|------|
| `morning_briefing` | 06:30 | systemd timer | Morning Briefing 任务派发 |
| `woa_audit` | 07:30 | systemd timer | WOA 输出审计 |
| `pre_market` | 07:50 | systemd timer | 盘前报 |
| `etf_spot_morning` | 09:25 | systemd timer | ETF 盘前同步 |
| `etf_spot_intraday` | 09:35 + 每 15min（24 个 timer）| systemd timer | ETF 日内刷新 |
| `etf_factor` | 17:05 | systemd timer | ETF 因子计算（溢价率/IOPV/流动性）|
| `etf_alpha` | 17:15 | systemd timer | ETF Alpha 信号（动量/风控/综合得分）|
| `etf_health` | 17:25 | systemd timer | ETF 健康检查（折溢价/波动率/资金流）|
| `etf_arbitrage` | 17:35 | systemd timer | ETF 套利信号 |
| `market_data_collect` | 15:05 | systemd timer | 市场快照采集 |
| `sw_industry` | 15:35 | systemd timer | 申万行业涨跌同步 |
| `etf_kline` | 15:40 | systemd timer | ETF 历史K线采集 |
| `index_eod` | 16:00 | systemd timer | 指数收盘数据 |
| `midday` | 12:00 | systemd timer | 午盘报 |
| `post_market` | 15:30 | systemd timer | 盘后报 |
| `industry_info` | 15:50 | systemd timer | 申万行业快讯密度 |
| `financial_p1` | 14:00 | systemd timer | 财务采集第1批 |
| `financial_p2` | 18:30 | systemd timer | 财务采集第2批 |
| `financial_p3` | 19:30 | systemd timer | 财务采集第3批 |
| `financial_p4` | 20:30 | systemd timer | 财务采集第4批 |

**独立业务 timer（5 个 · 由 setup_cron_timers.sh 或手动注册）：**

| 任务名 | 触发时间 | 触发方式 | 说明 |
|--------|----------|---------|------|
| `market_collect_midday` | 11:30 | systemd timer（独立）| 午盘市场快照 |
| `midday`（独立副本）| 12:00 | systemd timer | 与 TASK_MAP midday 重复，⚠️ 建议去重 |
| `pre_market`（独立）| 09:00 | systemd timer | 与 systemd SINGLE 重叠 |
| `post_market`（独立）| 15:30 | systemd timer | 与 systemd SINGLE 重叠 |
| `market_collect` | 15:05 | systemd timer | 同 TASK_MAP market_data_collect，⚠️ 建议去重 |

> **v1.1 建议**：将 5 个独立 timer 合并到 `setup_systemd_timers.py` 统一管理，避免双注册导致任务重复执行。

**系统守护任务（1 个 · 独立 systemd timer）：**

| 任务名 | 触发节奏 | 说明 |
|--------|----------|------|
| `watchdog` | 每小时 | 任务超时监控，超时则补发 |
| ~~`briefing_dispatch`~~ | ~~实时~~ | **v1.1 删除**：2026-06-12 已合并到 `morning_briefing`（06:30 派发），TASK_MAP 中不存在 |

**ETF 日内派生 timer（24 个 · 共享 etf_spot_intraday）：**

| Timer 名 | 触发时间 | 实际任务 |
|----------|----------|----------|
| `cia_etf_intra_1000` ~ `cia_etf_intra_1545` | 每 15min（10:00 - 15:45）| `etf_spot_intraday` |

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
| **决策** | 统一 `src/reports/report_engine.py` + modular reporters，三阶段演进路径 (22h) |
| **理由** | 1. 代码复用率高；2. 数据源优先级规则清晰；3. 与 Morning Briefing 可整合 |
| **后果** | ✅ 架构简洁；⚠️ MCP 单点故障风险，需加熔断机制 |
| **v1.1 修正** | 路径由 `scripts/report_engine.py` → `src/reports/report_engine.py`（实际已落地） |

#### ADR-005: 数据融合仲裁规则 — MCP 值优先，Morning Briefing 摘要兜底

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-07 |
| **背景** | 新汇报模块与 Morning Briefing 数据源可能冲突 |
| **决策** | 数值型数据用 MCP (wudao_aStock)，摘要/观点用 Morning Briefing 分析结果 |
| **理由** | 1. MCP 实时性更好；2. Morning Briefing 有深度分析；3. 分工明确避免重复 |
| **后果** | ✅ 数据一致性高；⚠️ 需要 adapter 层处理格式转换 |
| **v1.1 详细方案** | `docs/需求方案/MCP采集-报告DB化改造方案.md` |

#### ADR-006: 引入 RAA 独立审计 + Arc 修复分离架构（v1.1 新增）

| 属性 | 说明 |
|------|------|
| **日期** | 2026-06-11 |
| **背景** | 系统复杂度上升，需要独立审计层避免自审自修 |
| **决策** | RAA（只读审计） + Arc（修复执行）分离，状态通过 `.raa-fix-status.json` 协调 |
| **理由** | 1. 审计独立性（避免既当运动员又当裁判）；2. 修复责任清晰；3. Re-Audit 闭环可追溯 |
| **后果** | ✅ 审计可信度提升；⚠️ 调度链路增长（user → RAA → user → Arc → user → RAA）|
| **详细协议** | `workspace-audit/AGENTS.md §6.3 / §6.4 / §6.5` + `memory/audits/` |

### 8.2 技术债务清单 (P0-P4) — v1.1 补 RAA 修复

| 优先级 | 债务项 | 影响 | 修复状态 | 建议解决时间 | 负责人 | finding_id |
|--------|--------|------|---------|-------------|--------|------------|
| ~~P0~~ | ~~I 维度 MCP 每日 50 次限额~~ | ~~行业快讯密度计算可能中断~~ | ✅ **已修复** | 2026-06-10 | data-architect | (隐含在 MCP 适配中) |
| **P0** | **PG password 硬编码在源码** | **源码泄露即数据库失陷** | ✅ **fixed-pending-verify** (Arc) | 2026-06-11 | Arc | **P0-RAA-1** |
| **P0** | **pre_market `re` 模块未导入** | **盘前报直接 crash** | ✅ **fixed-pending-verify** (Arc) | 2026-06-11 | Arc | **P0-RAA-2** |
| **P0** | **financial_p1-p4 全部 1800s 超时** | **财务采集彻底失败** | ✅ **fixed-pending-verify** (Arc) | 2026-06-11 | Arc | **P0-RAA-3** |
| **P0** | **WOA→CIA 链明文密码传输** | **Redis 流量可解出凭据** | ✅ **fixed-pending-verify** (Arc) | 2026-06-11 | Arc | **TRACE-P2->P0** |
| P0 | 新汇报模块 MCP 单点故障 | 报告生成失败无降级方案 | ⏳ 进行中 | 2026-06-15 | tech-expert | — |
| P1 | **data-pipeline/.env 权限 664 → 600** | **组内用户可读密码** | ✅ **fixed** (Arc) | 2026-06-11 | Arc | **RAA-2** |
| P1 | **report_engine 强校验 3 个 env（PG/MINIO/CIFANG）** | **2 个 cron 用 'dummy' 绕过，运行时炸** | ✅ **fixed-pending-verify** (Arc) | 2026-06-11 | Arc | **RAA-5** |
| P1 | intraday_alerts 去重约束 (v2.0 已修复) | 重复告警 | ✅ 已完成 | — | tech-expert | — |
| P1 | JSON 字段缺少 GIN 索引 | 查询性能下降 | ⏳ 未开始 | 2026-06-20 | tech-expert | — |
| P1 | 缺少审计字段 (created_by/updated_at) | 数据追溯困难 | ⏳ 未开始 | 2026-07-01 | tech-expert | — |
| P2 | QQ 消息长度限制 (2000 字符) | 长报告被截断 | ⏳ 未开始 | 2026-07-15 | tech-expert | — |
| P2 | **lhb_records 数据截止 2023-04-17** | **龙虎榜分析失效** | ⏳ 未开始 | 2026-08-01 | data-architect | — |
| P2 | **news_articles 数据停止 11 天（最新 2026-06-01）** | **I 维度计算可能漂移** | ⚠️ **待排查** | 2026-06-12 | data-architect | — |
| P2 | **factor_values 数据停止 11 天（最新 2026-06-01）** | **因子复算失效** | ⚠️ **待排查** | 2026-06-12 | tech-expert | — |
| P2 | **etf_quant_scores 表存在但 0 行** | **Q 维度可能未投入使用** | ⚠️ **待确认** | 2026-06-12 | data-architect | — |
| P3 | Redis Stream 无持久化配置 | 重启后消息丢失 | ⏳ 未开始 | 2026-07-01 | tech-expert | — |
| P4 | docs/cron_cia.md 未更新 | 文档与实现不一致 | ✅ **本次 RAA 审计已覆盖 SYSTEM_PLAYBOOK** | 2026-08-01 | system-architect | — |
| P4 | **setup_cron_timers.sh 与 setup_systemd_timers.py 重复注册** | **5 个 timer 重复触发** | ⏳ 未合并 | 2026-06-30 | tech-expert | — |

**RAA 修复状态总览**（来源：`.raa-fix-status.json`）：

| finding_id | title | status | agent |
|------------|-------|--------|-------|
| P0-RAA-1 | PG password hardcoded in source | fixed-pending-verify | Arc |
| P0-RAA-2 | pre_market report 're' module not imported | fixed-pending-verify | Arc |
| P0-RAA-3 | financial_p1-p4 all 1800s timeout | fixed-pending-verify | Arc |
| TRACE-P2->P0 | Plaintext password in Redis payload (WOA→CIA chain) | fixed-pending-verify | Arc |
| RAA-2 | data-pipeline/.env permissions (664 → 600) | **fixed** ✅ | Arc |
| RAA-5 | report_engine.py import chain strong-validates 3 env vars | fixed-pending-verify | Arc |

### 8.3 实施里程碑（v1.1 状态刷新）

| 里程碑 | 目标 | 预计完成 | 状态（v1.1）|
|--------|------|---------|-------------|
| **M1: Phase 0 基础设施** | PG/Redis/MinIO 部署 + 基础表结构 | 2026-06-03 | ✅ 已完成 |
| **M2: FQIR 评分体系** | 五维因子计算 + 综合评分 | 2026-06-05 | ✅ 已完成 |
| **M3: Morning Briefing** | WOA 多 Agent 协作 + QQ 推送 | 2026-06-06 | ✅ 已完成 |
| **M4: 架构评审 v1.0** | 现有系统分析 + 新模块分析 | 2026-06-07 | ✅ 已完成 |
| **M5: 架构评审 v2.0** | 整合方案 + 实施路径 (22h) | 2026-06-07 | ✅ 已完成 |
| **M6: SYSTEM_PLAYBOOK** | 运维手册 + Agent 档案 + 决策日志 | 2026-06-07 | ✅ **已完成 v1.0** → **v1.1 已更新**（RAA 审计触发）|
| **M7: 新汇报模块 Phase 1** | 独立试运行 (9h) | 2026-06-15 | ✅ **v1.1 标已实质完成**（`src/reports/modules/` 已实现 pre_market/midday/post_market/intraday_alert 4 模块）；待 tech-expert 正式 verify |
| **M8: 新汇报模块 Phase 2** | 双轨运行 (6h) | 2026-06-22 | ⏳ 待启动 |
| **M9: 统一报告引擎上线** | 终态架构 (7h) | 2026-06-30 | ⏳ 待启动 |
| **M10: RAA 审计体系建立**（v1.1 新增）| 审计 SOP + 边界协议 + handoff 流程 | 2026-06-11 | ✅ 已完成 |
| **M11: 系统说明审计 v1.1**（v1.1 新增）| 修正 README + SYSTEM_PLAYBOOK 偏差 | 2026-06-12 | ✅ **本次完成**（handoff 已交付 system-architect）|

### 8.4 风险登记册（v1.1 补 RAA 相关）

| 风险 ID | 风险描述 | 概率 | 影响 | 缓解措施 | 负责人 |
|---------|---------|------|------|---------|--------|
| **R01** | MCP API 限额耗尽导致 I 维度计算失败 | 高 | 中 | 1. 优化调用策略；2. 缓存结果；3. 降级为默认分 | data-architect |
| **R02** | MCP 服务不可用导致新汇报模块全部失败 | 中 | 高 | 1. 熔断机制；2. Redis 缓存兜底；3. 告警通知 | tech-expert |
| **R03** | Redis Stream 消息堆积导致 Morning Briefing 延迟 | 低 | 高 | 1. 监控队列长度；2. 自动扩容 WOA 实例；3. 降级为单 Agent | CIA |
| **R04** | PostgreSQL 磁盘空间不足 | 中 | 高 | 1. 定期清理历史数据；2. 表分区；3. 监控告警 | tech-expert |
| **R05** | QQ 推送失败 (网络/账号问题) | 低 | 中 | 1. 重试机制；2. 备用推送渠道；3. 日志记录 | CIA |
| **R06**（v1.1 新增）| RAA 自审自修偏见（未来 RAA 审计自己工作区）| 低 | 中 | 1. 边界铁律 §6.3 强制；2. 用户承担 BOUNDARY OVERRIDE 风险；3. 修复移交由其他 agent 接手 | RAA + user |
| **R07**（v1.1 新增）| 5 个独立 timer 重复触发导致资源浪费 | 中 | 低 | 1. 合并到 `setup_systemd_timers.py`；2. 加任务级去重 | tech-expert |
| **R08**（v1.1 新增）| 文档漂移（系统变更后未同步更新）| 高 | 中 | 1. 文档变更 checklist；2. RAA 季度审计；3. 自动校验脚本 | system-architect + RAA |
| **R09**（v1.1 新增）| 数据陈旧（news_articles/factor_values 停止 11 天）| 中 | 中 | 1. 数据 SLA 监控；2. 采集中断告警 | data-architect |

---

## 附录：快速启动命令

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 进入 PostgreSQL
docker exec -it <pg_container> psql -U invest_user -d investdb

# 查看所有 cia_*.timer（v1.1 应显示 47 个）
systemctl --user list-timers --all | grep cia_

# 查看 Redis 队列长度
redis-cli llen task_queue

# RAA 审计（用户显式调用）
# 1. 读取 invest-infra 产物
# 2. 写 /home/claw/.openclaw/workspace-audit/memory/audits/raa-audit-*.md
# 3. 写 /home/claw/.openclaw/workspace-audit/memory/handoff/raa-handoff-*.md
# 4. 等用户调度 Arc 修复 → Re-Audit
```

## 附录：关键文件路径（v1.1 修正）

| 文件 | 路径 | 说明 | v1.1 状态 |
|------|------|------|-----------|
| README.md | `/home/claw/invest-infra/README.md` | 系统架构总览（v1.1）| ✅ 已更新 |
| SYSTEM_PLAYBOOK.md | `/home/claw/invest-infra/SYSTEM_PLAYBOOK.md` | 本文件（v1.1 运维手册）| ✅ 已更新 |
| cron_cia.md | `/home/claw/invest-infra/docs/cron_cia.md` | CIA 定时任务手册 | 待更新 |
| ~~progress.md~~ | ~~`/home/claw/invest-infra/data-pipeline/progress.md`~~ | **v1.0 错误路径，文件不存在** | ❌ 删除引用 |
| architecture_review_report_v2.md | `/home/claw/invest-infra/evaluation_reports/FINAL_INTEGRATION_REPORT.md` | v1.1 修正路径 | ✅ 修正 |
| MCP 改造方案 | `/home/claw/invest-infra/docs/需求方案/MCP采集-报告DB化改造方案.md` | ADR-005 详细 | ✅ 补充引用 |
| RAA 修复状态 | `/home/claw/invest-infra/.raa-fix-status.json` | Arc 写入，RAA 只读 | ✅ v1.1 新增 |
| RAA 审计目录（只读）| `raa-audit-readonly` 软链接 | → workspace-audit/memory/audits/ | ✅ v1.1 新增 |
| RAA 移交目录（只读）| `raa-handoff-readonly` 软链接 | → workspace-audit/memory/handoff/ | ✅ v1.1 新增 |

## 附录：联系方式（v1.1 补全）

| 角色 | Agent | 职责范围 |
|------|-------|---------|
| 首席投资官 | CIA | 策略决策、最终裁量 |
| 技术实施专家 | tech-expert | 代码实现、技术风险 |
| 数据架构师 | data-architect | 数据流、数据模型 |
| 系统架构分析师 | system-architect | 架构评审、模块设计、文档维护 |
| 修复执行 Agent（v1.1）| Arc | 根据 RAA 移交执行修复 |
| 独立审计 Agent（v1.1）| RAA | 投研系统独立审计 |

---

*文档维护: system-architect（文档层） + tech-expert（实现层） + Arc（修复层） + RAA（审计层）*  
*最后更新: **2026-06-12**（v1.1，RAA 系统说明审计触发）*  
*版本: **v1.1**（v1.0: 2026-06-07）*  
*审计报告: `/home/claw/.openclaw/workspace-audit/memory/audits/raa-audit-system-docs-20260612.md`*  
*本次变更清单: `../CHANGELOG.md`*
