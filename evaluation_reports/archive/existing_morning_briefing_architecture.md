# 现有 Morning Briefing 架构分析报告

**分析日期:** 2026-06-07  
**分析者:** data-architect  
**任务 ID:** analyze-existing-morning-briefing  

---

## 1. 系统概述

Morning Briefing（盘前洞察）是一个基于 **多 Agent 协作 + Redis Stream 队列 + 本地 PostgreSQL 数据源** 的自动化投研汇报系统。系统通过 cron 定时触发，协调 WOA（工作协调员 Agent）和 CIA（首席投资官 Agent）两个角色完成从数据采集到报告生成的完整流程。

---

## 2. 数据流图

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Cron Job  │────▶│  Redis Stream│────▶│    WOA       │────▶│  PostgreSQL  │
│ (06:30)     │     │ task_queue   │     │ (协调 Agent) │     │ investment_  │
│ 周一至周五  │     │              │     │              │     │ memos        │
└─────────────┘     └──────┬───────┘     └──────┬───────┘     └──────────────┘
                           │                     │
                           │ XADD               │ XREADGROUP
                           │                     │ (5 个子任务并行)
                           │                     ▼
                           │              ┌──────────────┐
                           │              │ CIA Agent    │
                           │              │ (研判 Agent) │
                           │              └──────┬───────┘
                           │                     │
                           │ cia_task_queue      │ XADD
                           │                     ▼
                           │              ┌──────────────┐
                           │              │   QQ Bot     │
                           │              │  (推送通知)   │
                           │              └──────────────┘
                           │
                    A2A Notify ◀── curl POST to http://127.0.0.1:19100/a2a
```

### 数据流转步骤

| 步骤 | 组件 | 操作 | 说明 |
|------|------|------|------|
| 1 | Cron (06:30) | `XADD task_queue` | 写入完整 WOA prompt 到 Redis Stream |
| 2 | Cron | A2A Notify | curl POST 通知 WOA 去领任务 |
| 3 | WOA | `XREADGROUP` | 从 task_queue 领取任务，解析 prompt |
| 4 | WOA | 集群模式 | spawn_mode=cluster 并行执行 5 个子任务 |
| 5 | WOA | PG INSERT | 5 条 memo 写入 investment_memos (company_id=5233) |
| 6 | WOA | `XADD cia_task_queue` | 生成 CIA prompt 并写入第二级队列 |
| 7 | WOA | QQ Notify | 发送简短完成通知（含 task_id） |
| 8 | WOA | `XACK` | 确认任务完成，清除 Stream 消息 |
| 9 | CIA | `XREADGROUP` | 从 cia_task_queue 领取 prompt |
| 10 | CIA | PG SELECT | 读取今日 5 条 memo |
| 11 | CIA | QQ Notify | 输出最终盘前洞察到 QQ |

---

## 3. 关键组件分析

### 3.1 Cron 触发脚本 (`cron_morning_briefing.py`)

**职责:** 定时任务入口，负责初始化流程

**核心逻辑:**
- 每日 06:30（周一至周五）由 cron 触发
- 构建完整的 WOA prompt（约 290 行），包含：
  - 5 个子任务定义（morning_collect, factor_calculation, etf_alpha_signal, risk_monitoring, daily_report）
  - 数据源说明（本地 PG 查询函数列表）
  - CIA prompt 生成规则
  - PG investment_memos 写入格式规范
- 通过 Redis Stream 下发任务
- 通过 A2A (Agent-to-Agent) HTTP 接口通知 WOA

**技术细节:**
```python
STREAM = "task_queue"           # WOA 领取的任务流
CIA_STREAM = "cia_task_queue"   # CIA 领取的 prompt 流
GROUP = "woa_workers"           # Consumer Group
CONSUMER = "woa_1"              # Consumer 实例
A2A_URL = "http://127.0.0.1:19100/a2a"
```

### 3.2 WOA 任务执行器 (`woa_tasks/`)

**文件结构:**
- `batch_morning_briefing.py` — 批量执行器（模拟数据，用于测试）
- `parallel_morning_briefing.py` — 集群模式执行器（实际生产版本）
- `local_data_source.py` — 本地 PG 查询封装层
- `task_*.py` — 动态生成的任务文件

**核心设计:**
- **5 个子任务并行/串行执行**: morning_collect → factor_calculation → etf_alpha_signal → risk_monitoring → daily_report
- **数据源双轨策略**: 
  - 优先使用本地 PG（`local_data_source.py`）
  - 备用 RssCast MCP（`_call_rsscast()` 函数）
- **PG 写入规范**: 每条 memo 包含 confidence_level、trigger_signals、tags 等元数据

**关键查询函数:**
| 函数 | 数据表 | 用途 |
|------|--------|------|
| `query_index_kline()` | index_quotes / indices | 指数 K 线（沪深300/上证/深证等） |
| `query_stock_kline()` | daily_quotes / companies | 个股 K 线 |
| `query_etf_quotes()` | etf_quotes / etfs | ETF 行情 |
| `query_north_flow()` | north_flow_hist | 北向资金 |
| `query_news()` | news_articles | 新闻舆情 |
| `query_fund_flow()` | fund_flow_big_deal | 大单资金流 |

### 3.3 Redis Stream 队列机制

**双级队列设计:**
```
task_queue (WOA) ──▶ cia_task_queue (CIA)
```

**消息格式:**
```json
{
  "task_id": "<UUID>",
  "task_type": "morning_briefing",
  "payload": {
    "prompt": "<完整 WOA prompt>",
    "date": "2026-06-07",
    "note": "..."
  },
  "created_at": "<ISO timestamp>"
}
```

**Consumer Group:**
- `woa_workers` / `woa_1` — WOA 消费者组
- `cia_workers` / `cia_1` — CIA 消费者组

### 3.4 PostgreSQL 数据模型

**investment_memos 表结构（关键��段）:**
```sql
company_id: 5233          -- 固定值，代表投研团队
title: [HIGH/MEDIUM/LOW] task_type - {date}
memo_date: {date}
memo_type: task_type      -- morning_collect/factor_calculation/...
summary: 一句话结论
body_md: 详细分析（Markdown）
sections_json: {}         -- 结构化数据
tags: ['morning_briefing', task_type, 'rsscast']
generated_by: 'jiuwenswarm_woa_v1'
model_used: 'MiniMax-M2.7'
confidence_level: HIGH/MEDIUM/LOW
trigger_signals: JSON     -- 信号类型→内容映射
follow_up_status: 'pending'
version: 1
```

---

## 4. 架构特征识别

### 4.1 多 Agent 协作模式

| 角色 | 职责 | 触发方式 |
|------|------|----------|
| **Cron** | 任务调度、流程启动 | 定时触发（06:30） |
| **WOA** | 数据采集、因子计算、报告整合 | Redis Stream 领取 |
| **CIA** | 综合研判、最终洞察输出 | Redis Stream 领取（WOA 完成后） |

**协作特点:**
- **链式依赖**: Cron → WOA → CIA，严格串行
- **Agent 间通信**: 通过 Redis Stream + QQ 通知双通道
- **并行处理**: WOA 内部 5 个子任务可并行（spawn_mode=cluster）

### 4.2 数据源策略

**本地 PG 为主:**
- 所有行情数据从本地 PostgreSQL 获取
- 禁止调用外部 API（akshare/RssCast 等）
- 数据缺失时如实标注，禁止编造

**备用 RssCast MCP:**
- 当本地 PG 数据不可用时，通过 `_call_rsscast()` 调用 RssCast
- 需要 Bearer Token 认证
- 作为 akshare 被 block 时的替代方案

### 4.3 Redis Stream 队列机制

**优势:**
- 解耦生产者和消费者
- 支持 Consumer Group 实现负载均衡
- XACK 机制保证消息不丢失

**局限:**
- 单实例部署，无高可用
- 无死信队列，处理失败的消息会堆积
- 无优先级队列，所有任务同等优先级

### 4.4 数据完整性保障

**置信度评估:**
```python
confidence = 'high' if n_signals >= 4 else ('medium' if n_signals >= 2 else 'low')
```

**数据来源标注:**
- 每个数据点必须标注来源表、字段名、日期
- 示例：`沪深300收盘 4935.39 点（index_quotes.close）【来源：index_quotes，日期：2026-06-02】`

---

## 5. 优势评估

### 5.1 架构优势

| 维度 | 优势 | 说明 |
|------|------|------|
| **解耦性** | 多阶段解耦 | Cron/Redis/Agent/PG 各司其职，职责清晰 |
| **可扩展性** | 模块化设计 | 5 个子任务可独立扩展，新增报告类型只需添加 handler |
| **数据追溯** | PG 持久化 | 所有分析结果写入 investment_memos，支持历史查询 |
| **容错性** | XACK 机制 | Redis Stream 保证消息不丢失，失败可重试 |
| **多 Agent 协作** | 专业化分工 | WOA 负责数据采集，CIA 负责综合研判，各司其职 |

### 5.2 数据架构优势

| 维度 | 优势 | 说明 |
|------|------|------|
| **本地化** | 不依赖外部 API | 所有数据从本地 PG 获取，降低外部依赖风险 |
| **结构化** | 标准化 memo 格式 | 统一的 title/summary/body_md/tags 结构 |
| **元数据丰富** | confidence/triggers/tags | 每条 memo 包含置信度、触发信号等元数据 |
| **双轨数据源** | PG + RssCast | 本地为主，外部备用，提高可用性 |

---

## 6. 局限性评估

### 6.1 架构局限

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **单点故障** | Redis/PG 单实例，无高可用 | 🔴 高 |
| **硬编码配置** | Redis/PG/QQ 配置写死在代码中 | 🟡 中 |
| **无监控告警** | 任务失败无通知机制 | 🟡 中 |
| **A2A 耦合** | WOA 通过 HTTP 回调通知，无标准协议 | 🟡 中 |
| **串行依赖** | Cron → WOA → CIA 严格串行，任一环节阻塞则全流程阻塞 | 🟠 中高 |

### 6.2 数据架构局限

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **数据时效性** | 本地 PG 数据依赖采集管线，可能延迟 | 🔴 高 |
| **akshare 依赖风险** | akshare 被 block 时整个流程受影响 | 🔴 高 |
| **北向资金时序问题** | 需收盘后（15:00+）才有完整数据，但 Morning Briefing 在 06:30 执行 | 🟡 中 |
| **无去重机制** | investment_memos 使用 ON CONFLICT DO NOTHING，可能丢失更新 | 🟡 中 |
| **硬编码 company_id=5233** | 无法支持多团队/多策略场景 | 🟢 低 |

### 6.3 可维护性局限

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **Prompt 过长** | WOA prompt 约 290 行，难以维护和调试 | 🟡 中 |
| **配置分散** | Redis/PG/QQ/A2A 配置散落在多处 | 🟡 中 |
| **无单元测试** | 代码缺乏测试覆盖 | 🟡 中 |
| **错误处理薄弱** | 大部分异常仅 print 日志，无重试机制 | 🟠 中高 |

---

## 7. 与新汇报模块的对比分析

| 维度 | Morning Briefing (现有) | 新汇报模块 (设计) |
|------|------------------------|------------------|
| **触发方式** | Cron + A2A Notify | Cron 直接调用 Python 脚本 |
| **执行模式** | AI Agent 集群模式 | 脚本规则模式 |
| **数据源** | 本地 PG + RssCast MCP | wudao_aStock MCP |
| **输出渠道** | QQ Bot | QQ Channel |
| **数据存储** | investment_memos (通用 memo 表) | market_reports (专用报表表) |
| **报告类型** | 仅盘前洞察 | 盘前/午盘/盘后/盘中轮询 |
| **复杂度** | 高（多 Agent 协作） | 低（单脚本执行） |
| **扩展性** | 需修改 prompt + 添加 handler | 模块化设计，易于扩展 |

---

## 8. 整合建议

### 8.1 共享基础设施清单

基于现有架构分析，以下组件可作为新汇报模块的共享基础：

| 组件 | 复用方式 | 注意事项 |
|------|----------|----------|
| **Redis Stream** | 可复用 task_queue/cia_task_queue 机制 | 需新增队列名称 |
| **PostgreSQL** | 可复用 investdb 连接配置 | 建议新建专用表，不混用 investment_memos |
| **QQ Bot** | 复用 `_qq_notify()` 函数逻辑 | 新模块使用 QQ Channel 而非 QQ Bot |
| **节假日判断** | 需新增（现有系统无此功能） | cron 表达式限定 1-5 不够，需排除法定节假日 |
| **日志框架** | 可复用 print 日志模式 | 建议升级为结构化日志 |

### 8.2 推荐整合策略

**方案 A：完全独立运行**（推荐）

理由:
1. 现有 Morning Briefing 架构稳定，不宜大改
2. 新模块设计已完成，有自己的数据管道和数据库表
3. 两种模式（AI Agent vs 脚本规则）适用场景不同，强行整合反而增加复杂度
4. 仅共享基础设施（Redis/PG/QQ），保持业务逻辑隔离

**长期演进方向:**
- 如果 MCP 数据源（wudao_aStock/RssCast）稳定，可逐步将 Morning Briefing 迁移到统一的数据管道
- 考虑引入消息队列中间件（如 RabbitMQ/Kafka）替代 Redis Stream，提高可靠性

---

## 9. 总结

Morning Briefing 是一个设计良好的多 Agent 协作系统，通过 Redis Stream 解耦了任务调度、数据采集和报告生成三个环节。其核心优势在于：
- **职责分离清晰**: Cron/Redis/Agent/PG 各司其职
- **数据追溯完整**: 所有分析结果持久化到 PG
- **双轨数据源**: 本地 PG 为主，RssCast 备用

主要局限在于：
- **单点故障风险**: Redis/PG 无高可用
- **数据时效性依赖**: 本地 PG 数据可能延迟
- **错误处理薄弱**: 缺乏重试和告警机制

对于新汇报模块的整合，建议采用**完全独立运行**策略，仅共享基础设施层，保持业务逻辑隔离。

---

*报告结束*
