# 投研系统汇报模块整合分析综合报告

**报告日期:** 2026-06-07  
**综合报告作者:** Arc（技术负责人）  
**整合自:**
- `architecture_review_report.md`（CIA + 多角色联合评审）
- `implementation_roadmap.md`（tech-expert）
- `integration_design.md`（system-architect）
- `new_report_module_analysis.md`（tech-expert × 2）
- `new_report_module_architecture.md`（data-architect）
- `existing_morning_briefing_architecture.md`（data-architect）

---

## 1. 执行摘要

### 1.1 核心结论

**推荐采用"方案 A + 渐进式演进"策略：Morning Briefing 与新汇报模块形式独立、逻辑整合。**

| 项目 | 决策 |
|------|------|
| 短期（0-2 周） | 方案 A：完全独立运行，仅共享基础设施层 |
| 中期（2-4 周） | 增加 AI 增强层，提升盘前报/盘后报内容质量 |
| 长期（4-8 周） | 条件成熟后逐步迁移到方案 C（Morning Briefing 作为新模块盘前报实现） |

### 1.2 关键数据

| 指标 | 值 |
|------|-----|
| 总工作量 | 16h（约 3 个工作日） |
| 阶段数 | 5 个 |
| 关键里程碑 | 4 个 |
| 风险条目 | P0 × 1, P1 × 2, P2 × 2, P3 × 1 |

---

## 2. 系统现状分析

### 2.1 现有系统：Morning Briefing

**架构模式：** 多 Agent 协作（AI Agent 模式）

```
Cron (06:30) → Redis Stream (task_queue) → WOA → PostgreSQL → Redis Stream (cia_task_queue) → CIA → QQ Bot
```

**数据源：** 本地 PostgreSQL 为主，RssCast MCP 为备用  
**报告类型：** 仅盘前洞察  
**核心优势：** 多 Agent 专业化分工、数据追溯完整  
**核心问题：** MCP 依赖风险、节假日判断缺失、错误处理薄弱

### 2.2 新汇报模块

**架构模式：** 脚本规则模式

```
Cron → report_engine.py → reporters/ (pre/midday/post/intraday) → formatters.py → db.py → QQ Channel
```

**数据源：** wudao_aStock MCP（14 个工具，6 个被复用）  
**报告类型：** 盘前报/午盘报/盘后报/盘中轮询（4 种）  
**核心优势：** 模块化设计、职责清晰、易于扩展  
**核心问题：** MCP 单点故障、无降级方案、无错误隔离

### 2.3 两种模式对比

| 维度 | Morning Briefing | 新汇报模块 |
|------|-----------------|------------|
| 执行模式 | AI Agent 协作 | 脚本规则 |
| 数据源 | 本地 PG + RssCast | wudao_aStock MCP |
| 报告类型 | 仅盘前洞察 | 4 种 |
| 复杂度 | 高 | 低 |
| 扩展性 | 需改 prompt | 模块化新增 |
| 错误处理 | 薄弱 | 未设计 |

---

## 3. 三种整合方案对比

### 3.1 方案对比表

| 维度 | 方案 A（完全独立） | 方案 B（复用 PG） | 方案 C（Morning Briefing 子模块） |
|------|-------------------|------------------|--------------------------------|
| **架构复杂度** | 低 | 中 | 高 |
| **数据一致性风险** | 高（双数据源） | 低（统一 PG） | 最低 |
| **实施成本** | 0h | 8-10h | 15-20h |
| **维护成本** | 中（两套管道） | 中 | 低 |
| **风险等级** | 低 | 中 | 高 |
| **推荐指数** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |

### 3.2 推荐方案及理由

**短期采用方案 A，原因：**
1. 现有 Morning Briefing 架构稳定，不宜大改（"没坏就不修"原则）
2. 新模块设计已完成，有独立数据管道
3. 两种模式适用场景不同，强行整合增加复杂度
4. 仅共享基础设施层，降低耦合风险

**长期演进路径：**
- 验证 MCP 稳定性（连续 30 天成功率 > 95%）后，逐步迁移到方案 C
- 触发条件：MCP 稳定性 + 系统稳定性 + 用户反馈

---

## 4. 风险矩阵（按优先级）

| 优先级 | 风险 | 影响范围 | 缓解措施 | 工作量 |
|--------|------|----------|----------|--------|
| **P0** | MCP 单点故障（无降级方案） | 所有汇报类型 | 请求队列 + 限流 + 指数退避重试 | 2h |
| **P1** | intraday_alerts 去重机制缺失 | 盘中轮询重复告警 | 增加唯一约束 `uk_stock_time` | 0.5h |
| **P1** | Cron 节假日判断缺失 | 节假日空跑 | 脚本内增加交易日校验 | 1h |
| **P2** | QQ 消息长度限制无拆分 | 长报告发送失败 | 4000 字符阈值自动分片 | 0.5h |
| **P2** | 错误处理/重试机制缺失 | 报告生成失败无人知晓 | 指数退避 + 执行日志 + 告警 | 1.5h |
| **P3** | 混合架构方向不符合 | 盘前报/盘后报缺少 AI 增强 | 中期增加 AI 增强层 | 2h |

---

## 5. 实施路线图

### 5.1 Phase 分解与依赖

```
Phase 1 (基础设施) ──→ Phase 2 (核心引擎) ──→ Phase 3 (报告模块) ──→ Phase 4 (集成测试)
                                                    │
                                                    ↓
                                              Phase 5 (迁移准备)
```

### 5.2 详细工作量

| Phase | 任务 | 工作量 | 累计 |
|-------|------|--------|------|
| **Phase 1** | DDL 建表 + content_hash 字段 | 0.5h | |
| | 交易日判断模块 | 0.5h | |
| | QQ 推送封装 | 0.5h | |
| | MCP 客户端封装 | 0.5h | **2h** |
| **Phase 2** | report_engine.py | 1h | |
| | formatters.py | 1h | |
| | db.py | 1h | **3h** |
| **Phase 3** | pre_market.py | 1.5h | |
| | midday.py | 1.5h | |
| | post_market.py | 2h | |
| | intraday_alert.py | 1h | **6h** |
| **Phase 4** | Cron 任务注册 | 0.5h | |
| | 单元测试 | 1h | |
| | 集成测试 | 1h | |
| | 文档编写 | 0.5h | **3h** |
| **Phase 5** | Morning Briefing 适配层 | 1h | |
| | 数据源双轨策略 | 1h | **2h** |
| **合计** | **17 个任务** | **16h** | |

### 5.3 甘特图

```
Day 1       Day 2       Day 3       Day 4       Day 5
│           │           │           │           │
├─Phase 1──┤           │           │           │
│ 基础设施准备 (2h)      │           │           │
│           ├─Phase 2───┤           │           │
│           │ 核心引擎开发 (3h)      │           │
│           │           ├─Phase 3───┤           │
│           │           │ 报告模块开发 (6h)      │
│           │           │           ├─Phase 4───┤
│           │           │           │ 集成测试 (3h)
│           │           │           │           ├─Phase 5──
│           │           │           │           │ 迁移准备 (2h)
```

### 5.4 里程碑

| 里程碑 | 完成时间 | 验收标准 |
|--------|----------|----------|
| M1: 基础设施就绪 | Day 1 结束 | DDL 执行成功、交易日判断模块可用、QQ/MCP 封装完成 |
| M2: 核心引擎完成 | Day 2 结束 | report_engine.py 可路由所有汇报类型、formatters.py 支持分片 |
| M3: 全模块上线 | Day 4 结束 | 4 种汇报类型均可生成报告并推送到 QQ |
| M4: 迁移准备就绪 | Day 5 结束 | Morning Briefing 适配层可用、双轨策略实现 |

---

## 6. 数据库设计评审

### 6.1 问题汇总

| 表名 | 问题 | 优先级 | 修复方案 |
|------|------|--------|----------|
| `market_reports` | 缺少 content_hash、status 字段 | P2 | ALTER TABLE 增加字段 |
| `report_subscriptions` | user_id 过长、缺少 last_sent_at | P2 | 修改为 CHAR(32)、增加字段 |
| `intraday_alerts` | 缺少唯一约束、alert_source、resolved | **P1** | 增加唯一约束 + 字段 |

### 6.2 建议 SQL 修复

```sql
-- intraday_alerts（最高优先级）
ALTER TABLE intraday_alerts 
ADD UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time)),
ADD COLUMN alert_source VARCHAR(50) COMMENT '告警来源工具',
ADD COLUMN resolved BOOLEAN DEFAULT FALSE COMMENT '是否已处理';

-- market_reports
ALTER TABLE market_reports 
ADD COLUMN content_hash VARCHAR(32) COMMENT '内容 MD5 摘要，用于去重',
ADD COLUMN status ENUM('success', 'failed', 'partial') DEFAULT 'success' COMMENT '报告生成状态';

-- report_subscriptions
ALTER TABLE report_subscriptions 
MODIFY COLUMN user_id CHAR(32) NOT NULL COMMENT '用户 ID',
ADD COLUMN last_sent_at DATETIME COMMENT '最后推送时间';
```

---

## 7. MCP 工具依赖分析

### 7.1 工具清单

| 汇报类型 | 依赖工具数 | 工具列表 |
|----------|-----------|----------|
| 盘前报 | 5 | sector_analysis, smart_hotlist, limit_stats, auction_market_scan, official_announcements |
| 午盘报 | 5 | market_overview, concept_ranking, capital_flow, broken_limit_up, watchlist_list |
| 盘后报 | 6 | limit_stats, hot_sectors, market_leaders_pick, limit_up_ladder, board_break_analysis, capital_flow |
| 盘中轮询 | 3 | limit_events, limit_down, anomaly_detection |

**总计:** 14 个独立工具，其中 `capital_flow` 被午盘报和盘后报复用

### 7.2 调用策略

| 策略 | 说明 | 依据 |
|------|------|------|
| 调用模式 | 串行 + 100ms 间隔 | findings.md 已验证频率限制风险 |
| 重试策略 | 指数退避，最多 3 次（1s/2s/4s） | 应对临时网络波动 |
| 降级策略 | 连续失败 3 次返回空结果 + 日志 | 避免阻塞主流程 |
| 并行优化 | limit_stats 和 capital_flow 可并行（盘后报） | 无依赖关系 |

### 7.3 降级场景

| 场景 | 降级方案 |
|------|----------|
| MCP 工具超时 | 标注"数据获取中"，跳过该模块，继续生成报告 |
| MCP 工具不可用 | 使用缓存数据，或标注"数据暂不可用" |
| 全部 MCP 工具失败 | 返回空报告 + 告警通知 |

---

## 8. 共享基础设施清单

| 组件 | 复用方式 | 注意事项 |
|------|----------|----------|
| **Redis Stream** | 可复用 task_queue/cia_task_queue 机制 | 需新增队列名称（如 report_queue） |
| **PostgreSQL** | 可复用 investdb 连接配置 | 建议新建专用表，不混用 investment_memos |
| **QQ Bot** | 复用 `_qq_notify()` 函数逻辑 | 新模块使用 QQ Channel 而非 QQ Bot |
| **节假日判断** | 需新增（现有系统无此功能） | 使用 akshare + 本地配置表覆盖调休场景 |
| **日志框架** | 可复用 print 日志模式 | 建议升级为结构化日志 |
| **交易日历 API** | 可复用 tushare/akshare 接口 | 缓存本地交易日历，减少 API 调用 |

---

## 9. 渐进式迁移计划

### 9.1 触发条件

| 条件 | 衡量标准 | 数据来源 |
|------|----------|----------|
| MCP 稳定性 | 连续 30 天成功率 > 95% | mcp_client.py 日志统计 |
| 系统稳定性 | 新模块运行稳定 2 周无严重故障 | 错误日志 + 监控告警 |
| 用户反馈 | 订阅数据良好（活跃率 > 80%） | report_subscriptions 表统计 |

### 9.2 迁移步骤

| 阶段 | 时间 | 目标 | 工作量 |
|------|------|------|--------|
| **阶段 1**（短期） | 0-2 周 | 方案 A：完全独立运行 | 0h |
| **阶段 2**（中期） | 2-4 周 | 增加 AI 增强层，提升内容质量 | 2h |
| **阶段 3**（长期） | 4-8 周 | 方案 C：Morning Briefing 作为盘前报实现 | 15-20h |

### 9.3 回滚策略

| 场景 | 回滚动作 | 预期恢复时间 |
|------|----------|--------------|
| MCP 成功率 < 90% | 停用迁移，恢复方案 A | 1h |
| 报告生成失败率 > 5% | 回退到独立管道 | 30min |
| 用户投诉激增 | 暂停迁移，分析问题 | 2h |

---

## 10. 最终建议

### 10.1 短期行动（0-2 周）

1. **部署新汇报模块**，采用方案 A（完全独立运行）
2. **解决 P0-P1 风险**：MCP 并发控制、intraday_alerts 去重、Cron 节假日判断
3. **共享 QQ 推送通道**，复用现有 QQBot 接口
4. **实现 MCP 客户端封装**，统一限流和重试逻辑

### 10.2 中期行动（2-4 周）

1. **增加 AI 增强层**，对盘前报/盘后报调用 LLM 生成自然语言总结
2. **建立数据一致性监控**，对比两个系统的数据差异
3. **实现错误隔离机制**，report_engine.py 支持"部分成功"策略

### 10.3 长期行动（4-8 周）

1. **评估方案 C 可行性**，如果 MCP 稳定且数据一致性好，可逐步迁移
2. **引入消息队列中间件**（如 RabbitMQ/Kafka），替代 Redis Stream
3. **扩展推送渠道**，支持微信/钉钉/Telegram 等多渠道

---

## 附录：报告来源清单

| 报告 | 作者 | 状态 |
|------|------|------|
| `architecture_review_report.md` | CIA + 多角色联合 | ✅ 综合评审结论 |
| `implementation_roadmap.md` | tech-expert | ✅ 实施路线图 |
| `integration_design.md` | system-architect | ✅ 方案对比 |
| `new_report_module_analysis.md` | tech-expert | ✅ 技术评估（两个版本内容高度重复，整合时已合并） |
| `new_report_module_architecture.md` | data-architect | ✅ 架构分析 |
| `existing_morning_briefing_architecture.md` | data-architect | ✅ 现有系统分析 |
| `morning-briefing-analysis-plan.md` | - | 参考文档 |

---

**综合报告作者:** Arc（技术负责人）  
**整合日期:** 2026-06-07  
**核心结论:** 推荐方案 A + 渐进式演进路径  
**实际输出:** Arc（基于 7 份原始报告整合生成）