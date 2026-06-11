# 投研系统汇报模块架构评审报告

**报告日期:** 2026-06-07  
**评审团队:** CIA（首席投资官）、data-architect、system-architect、tech-expert  
**参考文档:** technical_design.md, findings.md, ddl.sql, existing_morning_briefing_architecture.md, new_report_module_analysis.md, integration_design.md, implementation_roadmap.md

---

## 1. 执行摘要

### 1.1 核心发现

本次架构评审针对投研系统汇报模块的整合方案，评估了现有 Morning Briefing（盘前洞察）与新汇报模块（盘前报/午盘报/盘后报/盘中轮询）的整合路径。

**核心结论：推荐采用"混合架构 + 渐进式迁移"策略**

- **短期（0-2 周）：** 方案 A——完全独立运行，仅共享基础设施层
- **中期（2-4 周）：** 增加 AI 增强层，提升内容质量
- **长期（4-8 周）：** 条件成熟后逐步迁移到方案 C——Morning Briefing 作为新模块的盘前报实现

### 1.2 关键风险点（按优先级排序）

| 优先级 | 风险描述 | 影响范围 | 缓解措施 |
|--------|----------|----------|----------|
| **P0** | MCP 单点故障（无降级方案） | 所有汇报类型瘫痪 | 实现请求队列 + 限流 + 指数退避重试 |
| **P1** | intraday_alerts 去重机制缺失 | 重复告警 | 增加唯一约束：`UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time))` |
| **P1** | Cron 节假日判断缺失 | 节假日空跑 | 脚本内增加交易日判断逻辑（akshare + 本地配置表） |
| **P2** | QQ 消息长度限制无拆分逻辑 | 长报告发送失败 | 4000 字符阈值，自动分片 |
| **P3** | 错误处理/重试机制缺失 | 报告生成失败无人知晓 | 指数退避重试 + 执行日志表 + 告警通知 |

### 1.3 工作量估算

| Phase | 任务数 | 工作量 | 累计 |
|-------|--------|--------|------|
| 1. 基础设施准备 | 4 | 2h | 2h |
| 2. 核心引擎开发 | 3 | 3h | 5h |
| 3. 报告模块开发 | 4 | 6h | 11h |
| 4. 集成与测试 | 4 | 3h | 14h |
| 5. 渐进式迁移准备 | 2 | 2h | 16h |
| **合计** | **17** | **16h** | **约 3 个工作日** |

---

## 2. 现有系统分析（Morning Briefing）

### 2.1 系统概述

Morning Briefing（盘前洞察）是一个基于 **多 Agent 协作 + Redis Stream 队列 + 本地 PostgreSQL 数据源** 的自动化投研汇报系统。系统通过 cron 定时触发，协调 WOA（工作协调员 Agent）和 CIA（首席投资官 Agent）两个角色完成从数据采集到报告生成的完整流程。

### 2.2 数据流图

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
                    A2A Notify ◀── curl POST to http://127.0.0.1:19100/a2a
```

### 2.3 关键组件分析

| 组件 | 职责 | 技术细节 |
|------|------|----------|
| **Cron 触发脚本** | 定时任务入口，构建 WOA prompt（约 290 行），通过 Redis Stream 下发任务 | `STREAM="task_queue"`, `CIA_STREAM="cia_task_queue"`, A2A URL: `http://127.0.0.1:19100/a2a` |
| **WOA 任务执行器** | 5 个子任务并行/串行执行，数据源双轨策略（本地 PG + RssCast MCP） | `spawn_mode=cluster`，PG 写入规范含 confidence_level、trigger_signals、tags |
| **Redis Stream 队列** | 双级队列设计：task_queue (WOA) → cia_task_queue (CIA) | Consumer Group: `woa_workers/woa_1`, `cia_workers/cia_1` |
| **PostgreSQL 数据模型** | investment_memos 表，包含 title、summary、body_md、sections_json、tags 等字段 | company_id=5233（固定值），generated_by='jiuwenswarm_woa_v1' |

### 2.4 架构特征识别

| 维度 | 特征 | 说明 |
|------|------|------|
| **多 Agent 协作** | Cron → WOA → CIA 链式依赖，WOA 内部 5 个子任务可并行 | 专业化分工：WOA 负责数据采集，CIA 负责综合研判 |
| **数据源策略** | 本地 PG 为主（禁止外部 API），备用 RssCast MCP | 双轨数据源提高可用性 |
| **Redis Stream 队列** | 解耦生产者和消费者，XACK 机制保证消息不丢失 | 单实例部署，无高可用，无死信队列 |

### 2.5 优势评估

| 维度 | 优势 | 说明 |
|------|------|------|
| **解耦性** | 多阶段解耦 | Cron/Redis/Agent/PG 各司其职，职责清晰 |
| **可扩展性** | 模块化设计 | 5 个子任务可独立扩展 |
| **数据追溯** | PG 持久化 | 所有分析结果写入 investment_memos，支持历史查询 |
| **容错性** | XACK 机制 | Redis Stream 保证消息不丢失，失败可重试 |
| **多 Agent 协作** | 专业化分工 | WOA 负责数据采集，CIA 负责综合研判 |

### 2.6 局限性评估

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| **单点故障** | Redis/PG 单实例，无高可用 | 🔴 高 |
| **数据时效性** | 本地 PG 数据依赖采集管线，可能延迟 | 🔴 高 |
| **akshare 依赖风险** | akshare 被 block 时整个流程受影响 | 🔴 高 |
| **串行依赖** | Cron → WOA → CIA 严格串行，任一环节阻塞则全流程阻塞 | 🟠 中高 |
| **错误处理薄弱** | 大部分异常仅 print 日志，无重试机制 | 🟠 中高 |
| **Prompt 过长** | WOA prompt 约 290 行，难以维护和调试 | 🟡 中 |

---

## 3. 新模块分析（technical_design）

### 3.1 汇报体系分析

| 汇报类型 | 触发时间 | Cron 表达式 | MCP 工具依赖数 | 核心功能 |
|----------|----------|-------------|----------------|----------|
| **盘前报**（pre_market） | 08:30 | `30 08 * * 1-5` | 5 | 宏观预期、强势行业、情绪预判 |
| **午盘报**（midday） | 11:30 | `30 11 * * 1-5` | 5 | 上午复盘、异动监控、板块轮动 |
| **盘后报**（post_market） | 15:30 | `30 15 * * 1-5` | 6 | 完整复盘、涨跌停、主线分析 |
| **盘中轮询**（intraday_alert） | 每小时 | `0 10,11,12,13,14 * * 1-5` | 3 | 异动提醒、炸板/涨停监控 |

### 3.2 MCP 工具依赖分析（重点）

| 汇报类型 | 依赖工具 | 串行/并行 | 预计耗时 |
|----------|----------|-----------|----------|
| 盘前报 | sector_analysis, smart_hotlist, limit_stats, auction_market_scan, official_announcements | 串行 | 500ms + 网络延迟 |
| 午盘报 | market_overview, concept_ranking, capital_flow, broken_limit_up, watchlist_list | 串行 | 500ms + 网络延迟 |
| 盘后报 | limit_stats, hot_sectors, market_leaders_pick, limit_up_ladder, board_break_analysis, capital_flow | 串行 | 600ms + 网络延迟 |
| 盘中轮询 | limit_events, limit_down, anomaly_detection | 串行 | 300ms + 网络延迟 |

**关键风险：**
- 盘后报需调用 6 个工具，仅工具调用就需 600ms+
- 加上网络延迟（假设 200ms/次），总耗时可能超过 1.8s
- 如果某个工具超时或失败，整个报告生成将失败

### 3.3 技术架构评估

| 模块 | 路径 | 职责 | 评价 |
|------|------|------|------|
| `report_engine.py` | scripts/ | 主入口，参数解析，调用对应模块 | ⚠️ 单点故障风险 |
| `pre_market.py` | modules/reports/ | 盘前报数据组装 | ✅ 职责清晰 |
| `midday.py` | modules/reports/ | 午盘报数据组装 | ✅ 职责清晰 |
| `post_market.py` | modules/reports/ | 盘后报数据组装 | ⚠️ 依赖 6 个 MCP 工具，复杂度高 |
| `intraday_alert.py` | modules/reports/ | 盘中异动监控 | ⚠️ 缺少去重机制 |
| `formatters.py` | modules/ | 消息格式化（Markdown） | ✅ 职责清晰 |
| `db.py` | modules/ | 数据库操作 | ⚠️ 与 reporters 混在一起，职责不够清晰 |

### 3.4 数据流分析

```
Cron 触发 → report_engine.py → 对应 reporter (pre/midday/post/intraday)
    ↓
MCP 工具调用 (wudao_aStock) → 数据获取
    ↓
formatters.py → Markdown 格式化
    ↓
db.py → 存入 market_reports 表
    ↓
QQ 频道推送
```

**关键问题：**
1. **无错误隔离**：report_engine.py 作为单入口，一个模块失败可能影响其他模块
2. **无配置管理**：MCP 端点、数据库连接、推送渠道等硬编码
3. **无监控告警**：报告生成失败无人知晓

### 3.5 混合架构方向评估

| 维度 | 当前设计 | 混合架构要求 | 匹配度 |
|------|----------|--------------|--------|
| AI 智能体模式 | ❌ 缺失 | 盘前报/盘后报需要 LLM 摘要 | 低 |
| 脚本规则模式 | ✅ 完整 | 午盘报/盘后报/盘中轮询适合脚本模式 | 高 |
| 数据源双轨策略 | ❌ 纯 MCP | 本地 PG 为主，MCP 为辅 | 低 |
| 共享基础设施 | ⚠️ 未定义 | QQ 推送通道、数据库、节假日判断逻辑 | 中 |

**结论：** 当前设计**不符合**"AI 智能体模式 + 脚本规则模式双轨"的整合方向。

---

## 4. 整合方案推荐（混合架构）

### 4.1 两种模式的职责划分

| 模式 | 适用场景 | 代表汇报 | 数据源 | 执行方式 |
|------|---------|---------|--------|---------|
| **AI 智能体模式** | 需综合研判、跨维度推理、情景假设 | Morning Briefing（盘前洞察） | 本地 PG + RssCast MCP | 多 Agent 协作（WOA → CIA） |
| **脚本规则模式** | 规则化数据聚合、固定模板、异动监控 | 盘前报/午盘报/盘后报/盘中轮询 | wudao_aStock MCP | 单脚本执行（report_engine.py） |

### 4.2 架构分层图

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层（业务逻辑隔离）                      │
│  ┌──────────────────┐         ┌──────────────────────────┐  │
│  │ Morning Briefing  │         │   新汇报模块              │  │
│  │ (AI Agent 模式)   │         │  (脚本规则模式)           │  │
│  │ WOA → CIA        │         │  report_engine.py        │  │
│  └────────┬─────────┘         └──────────┬───────────────┘  │
├───────────┼──────────────────────────────┼──────────────────┤
│           │          共享基础设施层       │                  │
│  ┌────────▼──────────────────────────────▼────────────────┐ │
│  │  PostgreSQL (investdb)  │  Redis Stream  │  QQ Bot     │ │
│  └────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    数据源层（双轨策略）                        │
│  ┌──────────────────┐         ┌──────────────────────────┐  │
│  │   本地 PG 数据    │         │   MCP 工具 (wudao_aStock)│  │
│  │ index_quotes     │         │ sector_analysis          │  │
│  │ etf_quotes       │         │ smart_hotlist            │  │
│  │ north_flow       │         │ limit_stats              │  │
│  └──────────────────┘         └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 三种整合方案对比

| 维度 | 方案 A（完全独立） | 方案 B（复用 PG） | 方案 C（Morning Briefing 子模块） |
|------|-------------------|------------------|--------------------------------|
| **架构复杂度** | 低 | 中 | 高 |
| **数据一致性风险** | 高（双数据源矛盾） | 低（统一 PG） | 最低（完全复用） |
| **实施成本** | 最低（0h） | 中（8-10h） | 最高（15-20h） |
| **维护成本** | 中（两套管道） | 中（共享采集层） | 低（统一引擎） |
| **风险等级** | 低（隔离好） | 中（数据覆盖缺口） | 高（耦合深） |
| **推荐指数** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |

### 4.4 推荐结论：方案 A + 渐进式演进

**核心决策：** 短期采用方案 A，长期根据 MCP 稳定性逐步演进到方案 C。

**推荐理由：**
1. 现有 Morning Briefing 架构稳定，不宜大改（"如果没坏，就不要修"原则）
2. 新模块设计已完成，有自己的数据管道和数据库表
3. 两种模式适用场景不同，强行整合反而增加复杂度
4. 渐进式演进降低风险

### 4.5 共享基础设施清单

| 组件 | 复用方式 | 注意事项 |
|------|----------|----------|
| **Redis Stream** | 可复用 task_queue/cia_task_queue 机制 | 需新增队列名称（如 report_queue） |
| **PostgreSQL** | 可复用 investdb 连接配置 | 建议新建专用表，不混用 investment_memos |
| **QQ Bot** | 复用 `_qq_notify()` 函数逻辑 | 新模块使用 QQ Channel 而非 QQ Bot |
| **节假日判断** | 需新增（现有系统无此功能） | cron 表达式限定 1-5 不够，需排除法定节假日 |
| **日志框架** | 可复用 print 日志模式 | 建议升级为结构化日志 |
| **交易日历 API** | 可复用 tushare/akshare 接口 | 缓存本地交易日历，减少 API 调用 |

---

## 5. 技术实施路径

### 5.1 Phase 分解与依赖关系

```
Phase 1 (基础设施) ──→ Phase 2 (核心引擎) ──→ Phase 3 (报告模块) ──→ Phase 4 (集成测试)
                                                    │
                                                    ↓
                                              Phase 5 (迁移准备)
```

### 5.2 Phase 1：基础设施准备（2h）

| 任务 | 工作量 | 详细步骤 | 交付物 |
|------|--------|----------|--------|
| DDL 建表 | 0.5h | 1. 执行 ddl.sql 创建 3 张核心表<br>2. 增加 content_hash 字段（MD5 摘要，用于去重）<br>3. 优化索引：为 market_reports 增加 created_at 降序索引 | SQL 脚本 + 建表验证报告 |
| 交易日判断模块 | 0.5h | 1. 基于 akshare.tool_trade_date_hist_sina() 获取历史交易日历<br>2. 创建本地节假日配置表（支持调休补班）<br>3. 实现 is_trading_day(date) 函数 | trading_calendar.py + 单元测试 |
| QQ 推送封装 | 0.5h | 1. 复用 cron_morning_briefing.py 中的 _qq_notify 逻辑<br>2. 增加重试机制（最多 3 次，间隔 1s）<br>3. 实现 send_message(text, silent=False) 统一接口 | qq_notifier.py + 集成测试 |
| MCP 客户端封装 | 0.5h | 1. 统一调用接口：call_tool(tool_name, params)<br>2. 内置限流：串行调用 + 100ms 间隔<br>3. 指数退避重试：最多 3 次，间隔 1s/2s/4s<br>4. 降级策略：连续失败 3 次返回空结果并记录日志 | mcp_client.py + 单元测试 |

**技术决策点：**
- **交易日判断:** 使用 akshare 获取历史数据 + 本地配置表，覆盖调休场景（周末补班也算交易日）
- **QQ 推送:** 复用现有 openclaw CLI 方式（`/home/claw/.npm-global/bin/openclaw message send`），避免重复开发
- **MCP 客户端:** 采用装饰器模式实现限流和重试，便于后续扩展

### 5.3 Phase 2：核心引擎开发（3h）

| 任务 | 工作量 | 详细步骤 | 交付物 |
|------|--------|----------|--------|
| report_engine.py | 1h | 1. 参数解析：--type pre_market/midday/post_market/intraday_alert<br>2. 日志系统：统一日志格式，支持文件 + 控制台输出<br>3. 异常处理：捕获所有异常并记录，不中断主流程<br>4. 模块路由：ReportEngineFactory.get_reporter(report_type) | report_engine.py + 单元测试 |
| formatters.py | 1h | 1. Markdown 模板引擎：预定义各汇报类型的模板<br>2. QQ 消息分片：超过 4000 字符自动拆分，添加 [1/3]、[2/3] 标记<br>3. 数据注入：支持 {{variable}} 占位符替换 | formatters.py + 单元测试 |
| db.py | 1h | 1. SQLAlchemy ORM 封装（而非原生 SQL）<br>2. 连接池管理：使用 create_engine(pool_size=5, max_overflow=10）<br>3. CRUD 操作：save_report()、get_reports()、get_alerts()<br>4. 事务处理：支持批量插入和回滚 | db.py + 单元测试 |

**技术决策点：**
- **ORM 框架:** 选择 SQLAlchemy（而非原生 SQL），便于后续迁移到方案 C 时减少改造成本
- **消息分片:** formatters.py 内置 QQ 消息分片逻辑，超过 4000 字符自动拆分
- **工厂模式:** report_engine.py 采用工厂模式，新增汇报类型只需添加新类并注册

### 5.4 Phase 3：报告模块开发（6h）

| 任务 | 工作量 | 详细步骤 | 交付物 |
|------|--------|----------|--------|
| pre_market.py | 1.5h | 1. 调用 5 个 MCP 工具：sector_analysis、smart_hotlist、limit_stats、auction_market_scan、official_announcements<br>2. 数据组装：整合宏观环境、强势行业、情绪温度计、今日候选、风险提示<br>3. 格式化：使用 pre_market.md 模板 | pre_market.py + 集成测试 |
| midday.py | 1.5h | 1. 调用 5 个 MCP 工具：market_overview、concept_ranking、capital_flow、broken_limit_up、watchlist_list<br>2. 数据组装：上午走势、板块异动、强势股跟踪、风险提示<br>3. 格式化：使用 midday.md 模板 | midday.py + 集成测试 |
| post_market.py | 2h | 1. 调用 6 个 MCP 工具：limit_stats、hot_sectors、market_leaders_pick、limit_up_ladder、board_break_analysis、capital_flow<br>2. **优化:** limit_stats 和 capital_flow 可并行调用（无依赖）<br>3. 数据组装：今日概况、最强主线、涨跌停分析、资金流、明日展望<br>4. 格式化：使用 post_market.md 模板 | post_market.py + 集成测试 |
| intraday_alert.py | 1h | 1. 调用 3 个 MCP 工具：limit_events、limit_down、anomaly_detection<br>2. **去重逻辑:** 基于 (trade_date, stock_code, alert_type) 唯一约束，避免重复告警<br>3. 数据组装：涨停监控、跌停监控、异常波动、板块异动<br>4. 格式化：使用 intraday_alert.md 模板 | intraday_alert.py + 集成测试 |

**技术决策点：**
- **MCP 调用策略:** 串行调用 + 100ms 间隔 + 指数退避重试（最多 3 次）
- **盘后报优化:** 6 个工具中 limit_stats 和 capital_flow 可并行调用（无依赖），减少总耗时
- **intraday_alert 去重:** 数据库增加唯一约束，应用层先查询再插入

### 5.5 Phase 4：集成与测试（3h）

| 任务 | 工作量 | 详细步骤 | 交付物 |
|------|--------|----------|--------|
| Cron 任务注册 | 0.5h | 1. 盘前报：`30 08 * * 1-5`<br>2. 午盘报：`30 11 * * 1-5`<br>3. 盘后报：`30 15 * * 1-5`<br>4. 盘中轮询：`0 10,11,12,13,14 * * 1-5`（脚本内增加交易日校验） | Cron 配置 + 验证脚本 |
| 单元测试 | 1h | 1. MCP 客户端：mock 外部 API，验证限流和重试逻辑<br>2. formatters.py：验证 QQ 消息分片逻辑（4000 字符阈值）<br>3. db.py：验证 CRUD 操作和连接池管理 | pytest 测试用例 + 覆盖率报告 |
| 集成测试 | 1h | 1. 端到端流程：cron → report_engine → reporter → QQ 推送<br>2. 异常场景：MCP 超时、数据库连接失败、QQ 推送失败<br>3. 验证所有汇报类型的输出格式 | 集成测试报告 + 异常处理日志 |
| 文档编写 | 0.5h | 1. API 文档：各模块接口说明<br>2. 部署指南：环境配置、依赖安装、Cron 注册步骤<br>3. 故障排查手册：常见问题及解决方案 | docs/ 目录 + README.md |

**技术决策点：**
- **Cron 表达式:** 盘中轮询改为 `0 10,11,12,13,14 * * 1-5`，脚本内增加交易日校验（避免节假日空跑）
- **测试策略:** MCP 调用使用 mock，避免真实 API 依赖；数据库使用 SQLite 内存数据库

### 5.6 Phase 5：渐进式迁移准备（2h）

| 任务 | 工作量 | 详细步骤 | 交付物 |
|------|--------|----------|--------|
| Morning Briefing 适配层 | 1h | 1. 将 Morning Briefing 的盘前报逻辑封装为可调用接口<br>2. 实现 call_morning_briefing() 函数，返回结构化数据<br>3. 在 report_engine.py 中注册 pre_market 类型时优先调用此接口 | morning_briefing_adapter.py + 集成测试 |
| 数据源双轨策略 | 1h | 1. MCP 失败时降级到本地 PG 查询（使用 query_index_kline、query_stock_kline 等）<br>2. 实现 fallback_data_source() 函数，自动切换数据源<br>3. 记录降级日志，便于后续评估迁移时机 | data_source_fallback.py + 集成测试 |

**触发条件（何时启动迁移）：**
- ✅ MCP 连续 30 天成功率 > 95%
- ✅ 新模块运行稳定 2 周无严重故障
- ✅ 用户反馈良好（可通过订阅数据评估）

### 5.7 甘特图与时间线

```
Week 1                    Week 2                    Week 3
Day 1     Day 2     Day 3     Day 4     Day 5     Day 6     Day 7
│         │         │         │         │         │         │
├─Phase 1─┤         │         │         │         │         │
│ 基础设施准备 (2h)   │         │         │         │         │
│         ├─Phase 2─┤         │         │         │         │
│         │ 核心引擎开发 (3h)   │         │         │         │
│         │         ├─Phase 3─┤         │         │         │
│         │         │ 报告模块开发 (6h)   │         │         │
│         │         │         ├─Phase 4─┤         │         │
│         │         │         │ 集成与测试 (3h)   │         │
│         │         │         │         ├─Phase 5─┤         │
│         │         │         │         │ 迁移准备 (2h)   │
```

**关键里程碑：**
| 里程碑 | 完成时间 | 验收标准 |
|--------|----------|----------|
| M1: 基础设施就绪 | Day 1 结束 | DDL 执行成功、交易日判断模块可用、QQ/MCP 封装完成 |
| M2: 核心引擎完成 | Day 2 结束 | report_engine.py 可路由所有汇报类型、formatters.py 支持分片 |
| M3: 全模块上线 | Day 4 结束 | 4 种汇报类型均可生成报告并推送到 QQ |
| M4: 迁移准备就绪 | Day 5 结束 | Morning Briefing 适配层可用、双轨策略实现 |

### 5.8 工作量估算表

| Phase | 任务 | 工作量 | 依据 |
|-------|------|--------|------|
| **Phase 1** | DDL 建表 | 0.5h | 3 张核心表，参考 ddl.sql，需增加 content_hash 字段 |
| | 交易日判断模块 | 0.5h | 基于 akshare + 本地配置表，实现 is_trading_day() |
| | QQ 推送封装 | 0.5h | 复用现有逻辑，增加重试机制 |
| | MCP 客户端封装 | 0.5h | 统一接口 + 限流 + 重试 + 降级 |
| **Phase 1 小计** | | **2h** | |
| **Phase 2** | report_engine.py | 1h | 参数解析、日志、异常处理、工厂模式路由 |
| | formatters.py | 1h | Markdown 模板引擎 + QQ 消息分片（4000 字符） |
| | db.py | 1h | SQLAlchemy ORM + 连接池 + CRUD 封装 |
| **Phase 2 小计** | | **3h** | |
| **Phase 3** | pre_market.py | 1.5h | 5 个 MCP 工具调用 + 数据组装 |
| | midday.py | 1.5h | 5 个 MCP 工具调用 + 数据组装 |
| | post_market.py | 2h | 6 个 MCP 工具调用（最复杂）+ 并行优化 |
| | intraday_alert.py | 1h | 3 个 MCP 工具调用 + 去重逻辑 |
| **Phase 3 小计** | | **6h** | |
| **Phase 4** | Cron 任务注册 | 0.5h | 4 个 cron 表达式 + 节假日排除逻辑 |
| | 单元测试 | 1h | MCP 客户端、formatters、db.py 核心逻辑 |
| | 集成测试 | 1h | 端到端验证（cron → engine → reporter → QQ） |
| | 文档编写 | 0.5h | API 文档 + 部署指南 + 故障排查手册 |
| **Phase 4 小计** | | **3h** | |
| **Phase 5** | Morning Briefing 适配层 | 1h | 封装现有流程为可调用接口 |
| | 数据源双轨策略 | 1h | MCP 失败时降级到本地 PG 查询 |
| **Phase 5 小计** | | **2h** | |
| **合计** | **17 个任务** | **16h** | **约 3 个工作日** |

---

## 6. 数据库架构分析

### 6.1 market_reports 表

```sql
CREATE TABLE IF NOT EXISTS market_reports (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL COMMENT '交易日期',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL COMMENT '汇报类型',
    content     JSON COMMENT '完整报告内容',
    summary     JSON COMMENT '汇总数据（用于快速查询）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_type (trade_date, report_type),
    INDEX idx_trade_date (trade_date),
    INDEX idx_report_type (report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='市场汇报记录表';
```

**评价：**
- ✅ `UNIQUE KEY uk_date_type` 防止同一天同一类型重复报告
- ⚠️ `content` 用 JSON 存储完整报告——查询效率低，不利于历史分析
- ⚠️ 缺少 `content_hash` 字段，无法检测内容重复
- ⚠️ 缺少 `status` 字段（success/failed/partial），无法追踪报告生成状态

**建议修复：**
```sql
-- 增加 content_hash 字段
ALTER TABLE market_reports ADD COLUMN content_hash VARCHAR(32) COMMENT '内容 MD5 摘要，用于去重';

-- 增加 status 字段
ALTER TABLE market_reports ADD COLUMN status ENUM('success', 'failed', 'partial') DEFAULT 'success' COMMENT '报告生成状态';

-- 为 JSON 字段添加 GIN 索引（提升查询效率）
CREATE INDEX idx_content_gin ON market_reports USING GIN (content);
```

### 6.2 report_subscriptions 表

```sql
CREATE TABLE IF NOT EXISTS report_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(50) NOT NULL COMMENT '用户 ID',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL COMMENT '汇报类型',
    enabled     BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    channel     VARCHAR(20) DEFAULT 'qq' COMMENT '推送渠道',
    notify_time TIME COMMENT '自定义通知时间（可选）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_type (user_id, report_type),
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='汇报订阅配置表';
```

**评价：**
- ✅ `UNIQUE KEY uk_user_type` 防止重复订阅
- ⚠️ `user_id VARCHAR(50)` 过长，建议固定长度（如 CHAR(32)）
- ⚠️ 没有用户表关联，数据完整性存疑
- ⚠️ 缺少 `last_sent_at` 字段，无法追踪推送历史

**建议修复：**
```sql
-- 修改 user_id 为固定长度
ALTER TABLE report_subscriptions MODIFY COLUMN user_id CHAR(32) NOT NULL COMMENT '用户 ID';

-- 增加 last_sent_at 字段
ALTER TABLE report_subscriptions ADD COLUMN last_sent_at DATETIME COMMENT '最后推送时间';
```

### 6.3 intraday_alerts 表（重点问题）

```sql
CREATE TABLE IF NOT EXISTS intraday_alerts (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL COMMENT '交易日期',
    alert_time  DATETIME NOT NULL COMMENT '异动时间',
    alert_type  ENUM('limit_up', 'limit_down', 'break_seal', 'anomaly') NOT NULL COMMENT '异动类型',
    stock_code  VARCHAR(10) COMMENT '股票代码',
    stock_name  VARCHAR(50) COMMENT '股票名称',
    detail      JSON COMMENT '异动详情',
    notified    BOOLEAN DEFAULT FALSE COMMENT '是否已推送',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_trade_date (trade_date),
    INDEX idx_alert_type (alert_type),
    INDEX idx_notified (notified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='盘中异动记录表';
```

**评价：**
- ❌ **缺少唯一约束**：同一股票同一时间段的重复告警可能被重复记录
- ⚠️ 缺少 `alert_source` 字段，无法追溯告警来源（哪个 MCP 工具触发）
- ⚠️ 缺少 `resolved` 字段，无法追踪告警处理状态

**建议修复：**
```sql
-- 增加唯一约束
ALTER TABLE intraday_alerts ADD UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time));

-- 增加追溯字段
ALTER TABLE intraday_alerts ADD COLUMN alert_source VARCHAR(50) COMMENT '告警来源工具';
ALTER TABLE intraday_alerts ADD COLUMN resolved BOOLEAN DEFAULT FALSE COMMENT '是否已处理';

-- 为 JSON 字段添加 GIN 索引
CREATE INDEX idx_detail_gin ON intraday_alerts USING GIN (detail);
```

### 6.4 sector_filter_candidates/reports 表

- 这两个表属于独立功能（行业 ETF 成分股筛选），与汇报模块无直接关系
- **建议：** 拆分到独立模块，避免与汇报模块耦合

### 6.5 数据库设计汇总

| 表名 | 问题数 | 优先级 | 建议修复 |
|------|--------|--------|----------|
| market_reports | 3 | P2 | 增加 content_hash、status 字段，添加 GIN 索引 |
| report_subscriptions | 3 | P2 | 修改 user_id 为 CHAR(32)，增加 last_sent_at 字段 |
| intraday_alerts | 3 | **P1** | 增加唯一约束、alert_source、resolved 字段，添加 GIN 索引 |
| sector_filter_candidates/reports | 0 | - | 拆分到独立模块 |

---

## 7. 风险评估与缓解措施

### 7.1 技术风险（按优先级排序）

| 优先级 | 风险描述 | 影响范围 | 缓解措施 | 责任人 | 预计工作量 |
|--------|----------|----------|----------|--------|------------|
| **P0** | MCP 单点故障（无降级方案） | 所有汇报类型瘫痪 | 实现请求队列 + 限流 + 指数退避重试（方案 C） | tech-expert | 2h |
| **P1** | intraday_alerts 去重机制缺失 | 重复告警 | 增加唯一约束：`UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time))` | tech-expert | 0.5h |
| **P1** | Cron 节假日判断缺失 | 节假日空跑 | 脚本内增加交易日判断逻辑（使用 tushare/akshare 交易日历 API） | tech-expert | 1h |
| **P2** | QQ 消息长度限制无拆分逻辑 | 长报告发送失败 | 设置每条消息最大 4000 字符，自动分片 | tech-expert | 0.5h |
| **P3** | 错误处理/重试机制缺失 | 报告生成失败无人知晓 | 指数退避重试（最多 3 次）+ 执行日志表 + 告警通知 | tech-expert | 1.5h |
| **P4** | 混合架构方向不符合 | 内容质量不足 | 增加 AI 增强层，对盘前报/盘后报调用 LLM 生成自然语言总结 | tech-expert + system-architect | 2h |

### 7.2 降级策略设计

| 场景 | 降级方案 |
|------|----------|
| MCP 工具超时 | 标注"数据获取中"，跳过该模块，继续生成报告 |
| MCP 工具不可用 | 使用缓存数据（如有），或标注"数据暂不可用" |
| 全部 MCP 工具失败 | 返回空报告 + 告警通知 |

### 7.3 错误隔离与部分成功策略

```python
# report_engine.py 伪代码
async def generate_report(report_type: str):
    try:
        data = await fetch_data(report_type)
        content = await format_report(data)
        await save_to_db(content)
        await send_to_qq(content)
        return {"status": "success", "report_type": report_type}
    except MCPTimeoutError as e:
        # 部分成功：标注数据缺失，继续生成报告
        content = await format_report_with_missing_data(data, e.missing_tools)
        await save_to_db(content, status="partial")
        await send_to_qq(content + "\n⚠️ 部分数据暂不可用")
        return {"status": "partial", "report_type": report_type, "missing": e.missing_tools}
    except MCPUnavailableError as e:
        # 完全失败：返回空报告 + 告警通知
        await send_alert(f"报告生成失败：{e.message}")
        return {"status": "failed", "report_type": report_type, "error": str(e)}
```

### 7.4 项目风险

| 风险 | 严重度 | 概率 | 缓解措施 |
|------|--------|------|----------|
| MCP 工具频率限制 | 高 | 中 | 限流 + 重试 + 降级策略（已在 mcp_client.py 实现） |
| QQ 消息长度限制 | 中 | 低 | formatters.py 内置分片逻辑（4000 字符阈值） |
| 数据库连接池耗尽 | 中 | 低 | pool_size=5, max_overflow=10，监控连接数 |
| Cron 节假日误触发 | 高 | 中 | 脚本内增加交易日判断逻辑 |
| 工作量超支 | 中 | 低 | Phase 3 可并行开发（pre/midday），预留 20% 缓冲时间 |
| MCP 数据源不稳定 | 高 | 中 | 渐进式迁移策略，双轨降级方案 |

---

## 8. 最终建议

### 8.1 实施优先级

1. **P0（立即执行）:** Phase 1 + Phase 2（基础设施 + 核心引擎）
   - 理由：为后续开发提供支撑，无依赖关系
   - 时间：Day 1-2

2. **P1（紧随其后）:** Phase 3（报告模块开发）
   - 理由：核心业务逻辑，需尽早验证 MCP 数据源稳定性
   - 时间：Day 2-4

3. **P2（最后执行）:** Phase 4 + Phase 5（集成测试 + 迁移准备）
   - 理由：依赖 Phase 3 完成，为后续优化做准备
   - 时间：Day 4-5

### 8.2 关键成功因素

1. **MCP 数据源稳定性** — 这是整个系统的基石，需优先验证
2. **交易日判断准确性** — 避免节假日空跑，影响用户体验
3. **QQ 推送可靠性** — 用户直接感知的环节，需确保高可用
4. **渐进式迁移策略** — 降低耦合风险，便于后续优化

### 8.3 短期行动（0-2 周）

1. **部署新汇报模块**，采用方案 A（完全独立运行）
2. **共享 QQ 推送通道**，复用现有 QQBot 接口
3. **新增交易日判断逻辑**，避免节假日空跑
4. **实现 MCP 并发控制**，解决 P0 级风险

### 8.4 中期行动（2-4 周）

1. **增加 AI 增强层**，对盘前报/盘后报调用 LLM 生成自然语言总结
2. **建立数据一致性监控**，对比两个系统的数据差异
3. **实现错误隔离机制**，report_engine.py 支持"部分成功"策略

### 8.5 长期行动（4-8 周）

1. **评估方案 C 可行性**，如果 MCP 稳定且数据一致性好，可逐步迁移
2. **引入消息队列中间件**（如 RabbitMQ/Kafka），替代 Redis Stream
3. **扩展推送渠道**，支持微信/钉钉/Telegram 等多渠道

### 8.6 渐进式迁移触发条件

| 条件 | 衡量标准 | 数据来源 |
|------|----------|----------|
| MCP 稳定性 | 连续 30 天成功率 > 95% | mcp_client.py 日志统计 |
| 系统稳定性 | 新模块运行稳定 2 周无严重故障 | 错误日志 + 监控告警 |
| 用户反馈 | 订阅数据良好（活跃率 > 80%） | report_subscriptions 表统计 |

### 8.7 回滚策略

| 场景 | 回滚动作 | 预期恢复时间 |
|------|----------|--------------|
| MCP 成功率 < 90% | 停用迁移，恢复方案 A | 1h（切换配置） |
| 报告生成失败率 > 5% | 回退到独立管道 | 30min（切换 cron 指向） |
| 用户投诉激增 | 暂停迁移，分析问题 | 2h（定位 + 修复） |

---

## 附录 A：参考文档清单

| 文档 | 作者 | 状态 |
|------|------|------|
| existing_morning_briefing_architecture.md | data-architect | ✅ completed |
| new_report_module_analysis.md | tech-expert | ✅ completed |
| integration_design.md | system-architect | ✅ completed |
| implementation_roadmap.md | tech-expert | ✅ completed |
| technical_design.md | Arc | 参考文档 |
| findings.md | Arc | 参考文档 |
| ddl.sql | Arc | 参考文档 |

## 附录 B：团队成员贡献

| 成员 | 角色 | 贡献 |
|------|------|------|
| **CIA** | 首席投资官 | 策略方向指导、最终决策 |
| **data-architect** | 数据架构师 | 现有 Morning Briefing 架构分析、数据库设计评审 |
| **system-architect** | 系统架构分析师 | 整合方案设计（三种方案对比）、混合架构评估 |
| **tech-expert** | 技术实施专家 | 新模块技术评估、MCP 工具依赖分析、实施路线图制定 |

---

*本报告由投研系统汇报模块架构评审团队联合编写，2026-06-07*  
*核心结论：推荐方案 A（完全独立运行）+ 渐进式演进路径*
