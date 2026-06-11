# 现有 Morning Briefing 架构分析计划

## 任务目标
深入分析现有 Morning Briefing 系统的数据流、数据源、通信机制，为后续与新汇报模块的整合设计提供依据。

## 执行步骤

### Step 1: 源码级数据流分析（已完成）
- ✅ 已读取 `cron_morning_briefing.py` 完整源码
- ✅ 已读取新汇报模块 `technical_design.md`
- **核心发现**：
  - 现有系统：cron → Redis Stream → WOA(5子任务并行) → PG写入 → Redis Stream → CIA → QQ推送
  - 新系统设计：cron → report_engine.py → MCP工具 → PG写入 → QQ推送
  - **关键差异**：数据源不同（本地PG vs 外部MCP）、协作模式不同（多Agent vs 单引擎）

### Step 2: 数据源深度分析
- [ ] 检查 PostgreSQL 数据库结构（investdb）
  - 查看现有表结构：index_quotes, stock_daily, etf_quotes, etf_alpha_signals, risk_alerts, news_articles, north_flow_hist, investment_memos
  - 评估新汇报模块依赖的 MCP 工具与现有 PG 表的映射关系
- [ ] 检查 Redis Stream 配置
  - task_queue / cia_task_queue 的 consumer group 配置
  - 消息格式和生命周期管理

### Step 3: 数据流完整性验证
- [ ] 确认 WOA 实际执行逻辑（可能通过 Skill 或 prompt 驱动）
- [ ] 确认 CIA prompt 生成和执行的完整链路
- [ ] 评估现有数据管道（data-pipeline/src/）的查询函数实现

### Step 4: 输出分析报告
- [ ] 编写 `morning-briefing-data-flow-analysis.md`，包含：
  - 完整数据流图（Mermaid）
  - 数据源清单与可靠性评估
  - 与新汇报模块的数据依赖对比矩阵
  - 关键发现和问题标注

## 交付物
- `/home/claw/.jiuwenswarm/.agent_teams/量化团队_sess_19e9fc49962_67eb9d/team-workspace/artifacts/reports/morning-briefing-data-flow-analysis.md`

## 时间预估
- Step 1: 已完成（约30分钟）
- Step 2: 约1小时
- Step 3: 约1小时
- Step 4: 约30分钟
- **合计**: 约2.5小时
