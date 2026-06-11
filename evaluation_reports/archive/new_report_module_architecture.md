# 新汇报模块架构分析报告

**分析日期:** 2026-06-07  
**分析者:** data-architect  
**任务 ID:** analyze-new-report-design-v2  
**参考文档:** technical_design.md, findings.md  

---

## 1. 系统概述

新汇报模块是一个基于 **脚本规则模式 + MCP 数据源 + PostgreSQL 存储** 的自动化市场汇报系统。与现有 Morning Briefing 的 AI Agent 协作模式不同，新模块采用更轻量级的脚本执行方式，通过 cron 定时触发 Python 脚本完成数据采集、报告生成和推送。

---

## 2. 汇报体系分析

### 2.1 汇报类型矩阵

| 汇报类型 | 触发时间 | cron 表达式 | 数据源 | 复杂度 |
|----------|----------|-------------|--------|--------|
| **盘前报** | 08:30 | `30 08 * * 1-5` | sector_analysis, smart_hotlist, limit_stats, auction_market_scan, official_announcements | 中 |
| **午盘报** | 11:30 | `30 11 * * 1-5` | market_overview, concept_ranking, capital_flow, broken_limit_up, watchlist_list | 中 |
| **盘后报** | 15:30 | `30 15 * * 1-5` | limit_stats, hot_sectors, market_leaders_pick, limit_up_ladder, board_break_analysis, capital_flow | 高 |
| **盘中轮询** | 每小时 (10-14点) | `0 10,11,12,13,14 * * 1-5` | limit_events, limit_down, anomaly_detection | 低 |

### 2.2 内容模块设计评估

**盘前报（pre_market）:**
- ✅ 结构清晰，涵盖宏观环境、强势行业、情绪温度计、今日候选、风险提示
- ⚠️ 依赖隔夜美股数据，需确认 MCP 工具是否支持国际指数查询
- ⚠️ VIX 恐慌指数数据来源需明确

**午盘报（midday）:**
- ✅ 上午复盘 + 板块异动 + 强势股跟踪，逻辑合理
- ⚠️ concept_ranking 和 capital_flow 数据在现有 Morning Briefing 中未采集，需确认 MCP 可用性

**盘后报（post_market）:**
- ✅ 完整复盘设计，包含涨跌停分析、资金流、明日展望
- 🔴 依赖工具最多（6 个），批量调用风险最高
- ⚠️ board_break_analysis 和 limit_up_ladder 数据量大，需注意性能

**盘中轮询（intraday_alert）:**
- ✅ 异动监控设计合理，聚焦涨停/跌停/异常波动
- 🔴 每小时触发一次，5 次/天，需严格控制 MCP 调用频率
- ⚠️ anomaly_detection 算法复杂度未知

---

## 3. 技术架构分析

### 3.1 系统架构图

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Cron Job  │────▶│  report_engine.py│────▶│  reporters/     │
│ (4 个任务)  │     │  (主入口)         │     │  pre_market.py  │
│             │     └────────┬─────────┘     │  midday.py      │
└─────────────┘              │                │  post_market.py │
                             │                │  intraday.py    │
                    ┌────────▼─────────┐      └────────┬────────┘
                    │   formatters.py  │               │
                    │  (消息格式化)     │               │
                    └────────┬─────────┘               │
                             │                         │
                    ┌────────▼─────────┐      ┌────────▼────────┐
                    │   db.py          │      │  QQ Channel     │
                    │  (数据库操作)     │      │  (推送)          │
                    └────────┬─────────┘      └─────────────────┘
                             │
                    ┌────────▼─────────┐
                    │ wudao_aStock MCP │
                    │  (数据源)         │
                    └──────────────────┘
```

### 3.2 核心模块职责

| 模块 | 路径 | 职责 | 依赖 |
|------|------|------|------|
| `report_engine.py` | `scripts/` | 参数解析、日志、异常处理、模块路由 | argparse, logging |
| `pre_market.py` | `modules/reports/` | 盘前报数据组装 | MCP tools: sector_analysis, smart_hotlist... |
| `midday.py` | `modules/reports/` | 午盘报数据组装 | MCP tools: market_overview, concept_ranking... |
| `post_market.py` | `modules/reports/` | 盘后报数据组装 | MCP tools: limit_stats, hot_sectors... |
| `intraday_alert.py` | `modules/reports/` | 盘中异动检测 + 推送 | MCP tools: limit_events, limit_down... |
| `formatters.py` | `modules/` | Markdown 消息格式化 | 无 |
| `db.py` | `modules/` | PostgreSQL 数据库操作 | psycopg2 |

### 3.3 MCP 工具依赖分析

**盘前报（5 个工具）:**
```
sector_analysis        → 行业分析
smart_hotlist          → 热门股列表
limit_stats            → 涨跌停统计
auction_market_scan    → 集合竞价扫描
official_announcements → 官方公告
```

**午盘报（5 个工具）:**
```
market_overview        → 市场概览
concept_ranking        → 概念板块排行
capital_flow           → 资金流向
broken_limit_up        → 炸板股列表
watchlist_list         → 自选股列表
```

**盘后报（6 个工具）:**
```
limit_stats            → 涨跌停统计
hot_sectors            → 热门板块
market_leaders_pick    → 龙头股选择
limit_up_ladder        → 涨停梯队
board_break_analysis   → 炸板分析
capital_flow           → 资金流向（与午盘报共享）
```

**盘中轮询（3 个工具）:**
```
limit_events           → 涨停事件
limit_down             → 跌停列表
anomaly_detection      → 异常检测
```

**总计: 14 个独立 MCP 工具，其中 capital_flow 被午盘报和盘后报复用**

---

## 4. 数据库设计分析

### 4.1 market_reports 表

```sql
CREATE TABLE market_reports (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL,
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL,
    content     JSON COMMENT '完整报告内容',
    summary     JSON COMMENT '汇总数据（用于快速查询）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_type (trade_date, report_type),
    INDEX idx_trade_date (trade_date),
    INDEX idx_report_type (report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评估:**
- ✅ 复合唯一键防止重复插入
- ✅ JSON 字段灵活存储不同报告类型的内容
- ✅ 索引设计合理，支持按日期和类型查询
- ⚠️ 缺少 report_hash 字段，无法检测内容变更
- ⚠️ 缺少 status 字段（success/failed/partial），无法追踪执行状态

### 4.2 report_subscriptions 表

```sql
CREATE TABLE report_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(50) NOT NULL COMMENT '用户ID',
    report_type ENUM(...) NOT NULL,
    enabled     BOOLEAN DEFAULT TRUE,
    channel     VARCHAR(20) DEFAULT 'qq',
    notify_time TIME COMMENT '自定义通知时间',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_type (user_id, report_type),
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评估:**
- ✅ 支持用户订阅配置，为未来个性化推送预留空间
- ✅ enabled 字段支持动态启停
- ⚠️ 当前系统为单用户场景，此表可能暂时闲置
- ⚠️ notify_time 字段与 cron 固定时间冲突，需明确优先级

### 4.3 intraday_alerts 表

```sql
CREATE TABLE intraday_alerts (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL,
    alert_time  DATETIME NOT NULL,
    alert_type  ENUM('limit_up', 'limit_down', 'break_seal', 'anomaly') NOT NULL,
    stock_code  VARCHAR(10),
    stock_name  VARCHAR(50),
    detail      JSON COMMENT '异动详情',
    notified    BOOLEAN DEFAULT FALSE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_trade_date (trade_date),
    INDEX idx_alert_type (alert_type),
    INDEX idx_notified (notified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评估:**
- 🔴 **缺少去重机制**: 同一股票在同一时间的涨停事件可能被重复记录
- 🔴 **缺少唯一约束**: 应添加 `(trade_date, alert_time, stock_code, alert_type)` 的唯一索引
- ⚠️ notified 字段用于标记是否已推送，但无重试机制
- ✅ 索引设计合理，支持按日期和类型查询

---

## 5. Cron 任务注册方案分析

### 5.1 当前设计

```bash
# 盘前报 - 08:30
30 08 * * 1-5 cd /home/claw/invest-infra && .venv/bin/python scripts/report_engine.py --type pre_market

# 午盘报 - 11:30
30 11 * * 1-5 ...

# 盘后报 - 15:30
30 15 * * 1-5 ...

# 盘中轮询 - 每小时 (10-14点)
0 10,11,12,13,14 * * 1-5 ...
```

### 5.2 问题分析

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **节假日触发** | cron `1-5` 仅排除周末，法定节假日仍会触发 | 🔴 高 |
| **无交易日校验** | 脚本内未检查是否为交易日 | 🔴 高 |
| **任务重叠风险** | 盘中轮询 11:00 与午盘报 11:30 间隔仅 30 分钟 | 🟡 中 |
| **无任务锁机制** | 如果前一个任务未执行完，下一个任务可能并发执行 | 🟠 中高 |

### 5.3 建议改进

```bash
# 方案 1: 在脚本内增加交易日校验
if not is_trading_day():
    logger.info("非交易日，跳过执行")
    sys.exit(0)

# 方案 2: 使用 crontab 注释标记节假日
# 春节假期（示例）
# 0 8 * * 1-5 # 跳过 2026-02-15 至 2026-02-21
```

---

## 6. 技术风险点详细分析

### 🔴 风险 1: MCP 工具批量调用无并发控制

**问题描述:**
- 盘后报需调用 6 个 MCP 工具，午盘报/盘前报各需 5 个
- 设计文档提到"建议间隔 100ms"，但未实现
- 无失败重试机制

**影响:**
- 可能触发 MCP 服务端频率限制
- 批量调用超时导致整个报告生成失败
- 部分数据缺失时报告质量下降

**建议方案:**
```python
import time
from functools import wraps

def rate_limited(interval_ms=100):
    """速率限制装饰器"""
    last_call = {}
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            if func.__name__ in last_call:
                elapsed = (now - last_call[func.__name__]) * 1000
                if elapsed < interval_ms:
                    time.sleep((interval_ms - elapsed) / 1000)
            result = func(*args, **kwargs)
            last_call[func.__name__] = time.time()
            return result
        return wrapper
    return decorator

# 使用示例
@rate_limited(100)
def call_mcp_tool(tool_name, args):
    ...
```

**重试机制:**
```python
import random

def call_with_retry(func, max_retries=3, base_delay=1.0):
    """指数退避重试"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)
```

### 🔴 风险 2: intraday_alerts 表缺少去重机制

**问题描述:**
- 同一股票在同一时间的涨停事件可能被重复记录
- 盘中轮询每小时触发，如果数据源返回相同结果，会产生重复记录

**影响:**
- 数据库膨胀，查询性能下降
- 推送重复通知，用户体验差
- 历史数据分析失真

**建议方案:**
```sql
-- 添加唯一约束
ALTER TABLE intraday_alerts 
ADD UNIQUE INDEX uk_alert (trade_date, alert_time, stock_code, alert_type);

-- 或使用 INSERT ... ON CONFLICT DO UPDATE
INSERT INTO intraday_alerts (...) VALUES (...)
ON CONFLICT (trade_date, alert_time, stock_code, alert_type) 
DO UPDATE SET detail = EXCLUDED.detail, notified = FALSE;
```

### 🟠 风险 3: Cron 表达式节假日触发问题

**问题描述:**
- cron `1-5` 仅排除周六日，中国法定节假日（春节、国庆等）仍会触发
- A 股休市期间调用 MCP 工具可能返回空数据或错误

**影响:**
- 无效任务执行，浪费资源
- 可能产生空报告或错误报告
- QQ 推送无意义内容

**建议方案:**
```python
from datetime import date
import holidays

def is_trading_day(d: date = None) -> bool:
    """检查是否为 A 股交易日"""
    if d is None:
        d = date.today()
    
    # 排除周末
    if d.weekday() >= 5:
        return False
    
    # 排除中国法定节假日
    cn_holidays = holidays.China(years=d.year)
    if d in cn_holidays:
        return False
    
    return True
```

### 🟡 风险 4: QQ 消息长度限制无拆分逻辑

**问题描述:**
- QQ 消息单条长度有限（通常 2000-4000 字符）
- 盘后报内容可能较长（涨跌停统计 + 板块排行 + 资金流分析）
- 设计文档提到"需拆分或压缩"，但未实现

**影响:**
- 长消息可能被截断，丢失关键信息
- 推送失败或显示异常

**建议方案:**
```python
def split_message(text: str, max_chars: int = 3500) -> list:
    """按段落拆分消息"""
    paragraphs = text.split('\n\n')
    chunks = []
    current = ""
    
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current += '\n\n' + para if current else para
    
    if current:
        chunks.append(current.strip())
    
    return chunks

# 发送时循环
for i, chunk in enumerate(chunks):
    send_to_qq(chunk, suffix=f"({i+1}/{len(chunks)})")
```

### 🟠 风险 5: 错误处理/重试机制缺失

**问题描述:**
- 设计文档中未提及异常处理策略
- MCP 工具调用失败时，整个报告可能中断
- 无降级方案（部分数据缺失时的处理）

**影响:**
- 单次工具调用失败导致整份报告无法生成
- 用户收不到任何推送，误以为系统故障
- 无日志记录，问题难以排查

**建议方案:**
```python
class ReportGenerator:
    def __init__(self):
        self.errors = []
        self.partial_data = {}
    
    def generate(self, report_type: str) -> dict:
        """生成报告，支持部分成功"""
        try:
            data = self._fetch_all_data(report_type)
            content = self._format_report(report_type, data)
            self._save_to_db(report_type, content, status='success')
            return {'status': 'success', 'content': content}
        except Exception as e:
            self.errors.append(str(e))
            if self.partial_data:
                # 降级：使用部分数据生成报告
                content = self._format_report_partial(report_type, self.partial_data)
                self._save_to_db(report_type, content, status='partial')
                return {'status': 'partial', 'content': content, 'errors': self.errors}
            else:
                self._save_to_db(report_type, None, status='failed', error=str(e))
                return {'status': 'failed', 'error': str(e)}
    
    def _fetch_all_data(self, report_type: str) -> dict:
        """获取所有数据，记录失败的工具"""
        tools = self._get_tools_for_report(report_type)
        data = {}
        
        for tool in tools:
            try:
                result = call_mcp_tool(tool.name, tool.args)
                data[tool.name] = result
            except Exception as e:
                self.errors.append(f"{tool.name}: {e}")
                data[tool.name] = None  # 标记为失败
        
        self.partial_data = data  # 保存部分数据用于降级
        return data
```

---

## 7. 与现有 Morning Briefing 的对比

| 维度 | Morning Briefing (现有) | 新汇报模块 (设计) |
|------|------------------------|------------------|
| **执行模式** | AI Agent 集群模式 | 脚本规则模式 |
| **数据源** | 本地 PG + RssCast MCP | wudao_aStock MCP |
| **报告类型** | 仅盘前洞察 | 4 种（盘前/午盘/盘后/盘中） |
| **数据存储** | investment_memos (通用) | market_reports (专用) |
| **复杂度** | 高（多 Agent 协作） | 低（单脚本执行） |
| **MCP 依赖** | RssCast (备用) | wudao_aStock (主要) |
| **错误处理** | 薄弱（print 日志） | 未设计 |
| **去重机制** | ON CONFLICT DO NOTHING | 无 |
| **节假日处理** | 无 | cron 1-5 不够 |
| **消息拆分** | 无（QQ 通知极短） | 需实现 |

---

## 8. 架构改进建议

### 8.1 短期改进（Phase 1）

| 优先级 | 改进项 | 工作量 | 说明 |
|--------|--------|--------|------|
| P0 | 添加 MCP 速率限制 | 0.5h | 实现 100ms 间隔装饰器 |
| P0 | 添加交易日校验 | 0.5h | is_trading_day() 函数 |
| P0 | intraday_alerts 去重约束 | 0.25h | 添加唯一索引 |
| P1 | QQ 消息拆分逻辑 | 0.5h | split_message() 函数 |
| P1 | 基础错误处理 | 1h | try/except + 日志记录 |

### 8.2 中期改进（Phase 2）

| 优先级 | 改进项 | 工作量 | 说明 |
|--------|--------|--------|------|
| P1 | MCP 重试机制 | 1h | 指数退避重试 |
| P1 | 报告状态追踪 | 0.5h | market_reports.status 字段 |
| P2 | 配置外部化 | 1h | Redis/PG/MCP 配置从环境变量读取 |
| P2 | 结构化日志 | 1h | 使用 logging 模块替代 print |

### 8.3 长期改进（Phase 3）

| 优先级 | 改进项 | 工作量 | 说明 |
|--------|--------|--------|------|
| P2 | 任务锁机制 | 1h | 防止 cron 任务并发执行 |
| P2 | 监控告警 | 2h | 任务失败通知（QQ/邮件） |
| P3 | 数据源抽象层 | 2h | 统一 MCP/PG 数据访问接口 |
| P3 | 单元测试 | 4h | 核心模块测试覆盖 |

---

## 9. 总结

新汇报模块设计简洁、模块化程度高，适合规则化数据聚合场景。与现有 Morning Briefing 的 AI Agent 模式形成互补：

**优势:**
- 架构简单，易于理解和维护
- 模块化设计，新增报告类型只需添加新文件
- 专用数据库表，数据结构清晰
- 脚本执行模式，资源占用低

**主要风险:**
1. **MCP 工具批量调用无并发控制** — 需立即实现速率限制
2. **intraday_alerts 缺少去重机制** — 需添加唯一约束
3. **节假日触发问题** — 需增加交易日校验
4. **QQ 消息长度限制** — 需实现消息拆分
5. **错误处理缺失** — 需建立完整的异常处理链

**整合建议:**
- 采用**混合架构**策略：Morning Briefing 保持现有 AI 模式，新模块使用脚本规则模式
- 两种模式共享基础设施（Redis/PG/QQ），但业务逻辑完全隔离
- 短期优先修复 5 个技术风险点，确保系统稳定运行

---

*报告结束*
