# 新汇报模块架构分析报告

**分析日期:** 2026-06-07  
**分析者:** tech-expert（技术实施专家）  
**参考文档:** technical_design.md, findings.md, ddl.sql  
**协作方:** system-architect（架构设计评审）

---

## 1. 汇报体系分析

### 1.1 四种汇报类型概览

| 汇报类型 | 触发时间 | Cron 表达式 | 核心功能 | MCP 工具依赖数 |
|----------|----------|-------------|----------|----------------|
| **盘前报**（pre_market） | 08:30 | `30 08 * * 1-5` | 宏观预期、强势行业、情绪预判 | 5 |
| **午盘报**（midday） | 11:30 | `30 11 * * 1-5` | 上午复盘、异动监控、板块轮动 | 5 |
| **盘后报**（post_market） | 15:30 | `30 15 * * 1-5` | 完整复盘、涨跌停、主线分析 | 6 |
| **盘中轮询**（intraday_alert） | 每小时 | `0 10,11,12,13,14 * * 1-5` | 异动提醒、炸板/涨停监控 | 3 |

### 1.2 内容模块设计评估

#### 盘前报（pre_market）
- **优势**：覆盖宏观环境、强势行业、情绪温度计、今日候选、风险提示五大板块，结构完整
- **问题**：与现有 Morning Briefing 的【宏观环境】【强势行业】【情绪温度计】高度重叠，数据来源不同（MCP vs PG）可能导致数据矛盾

#### 午盘报（midday）
- **优势**：上午走势 + 板块异动 + 强势股跟踪 + 风险提示，覆盖全面
- **问题**：`broken_limit_up`（炸板股名单）在盘中轮询中也有类似功能，存在重复采集风险

#### 盘后报（post_market）
- **优势**：今日概况 + 最强主线 + 涨跌停分析 + 资金流 + 明日展望，是最完整的汇报类型
- **问题**：依赖 6 个 MCP 工具串行调用，执行时间最长（预计 >3s），失败风险最高

#### 盘中轮询（intraday_alert）
- **优势**：每小时触发，覆盖涨停/跌停/异常波动/板块异动，实时性强
- **问题**：`0 10,11,12,13,14 * * 1-5` 在周末/节假日仍会触发（cron 的 1-5 只排除周六日），且与午盘报时间重叠（11:00）

### 1.3 数据依赖关系图

```
盘前报 (08:30)
├── sector_analysis → 强势行业延续
├── smart_hotlist → 今日候选
├── limit_stats → 情绪温度计
├── auction_market_scan → 集合竞价异动
└── official_announcements → 风险提示

午盘报 (11:30)
├── market_overview → 上午走势
├── concept_ranking → 板块异动
├── capital_flow → 资金流入板块
├── broken_limit_up → 炸板股名单
└── watchlist_list → 强势股跟踪

盘后报 (15:30)
├── limit_stats → 今日概况
├── hot_sectors → 最强主线
├── market_leaders_pick → 龙头股
├── limit_up_ladder → 涨停梯队
├── board_break_analysis → 炸板池分析
└── capital_flow → 资金流

盘中轮询 (每小时)
├── limit_events → 涨停监控
├── limit_down → 跌停监控
├── anomaly_detection → 异常波动
└── (板块异动 - 无明确工具)
```

---

## 2. 技术架构评估

### 2.1 模块划分合理性

| 模块 | 路径 | 职责 | 评价 |
|------|------|------|------|
| `report_engine.py` | scripts/ | 主入口，参数解析，调用对应模块 | ⚠️ 单点故障风险（见 6.3） |
| `pre_market.py` | modules/reports/ | 盘前报数据组装 | ✅ 职责清晰 |
| `midday.py` | modules/reports/ | 午盘报数据组装 | ✅ 职责清晰 |
| `post_market.py` | modules/reports/ | 盘后报数据组装 | ⚠️ 依赖 6 个 MCP 工具，复杂度高 |
| `intraday_alert.py` | modules/reports/ | 盘中异动监控 | ⚠️ 缺少去重机制（见 P1） |
| `formatters.py` | modules/ | 消息格式化（Markdown） | ✅ 职责清晰 |
| `db.py` | modules/ | 数据库操作 | ⚠️ 与 reporters 混在一起，职责不够清晰 |

### 2.2 数据流分析

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

### 2.3 MCP 集成方式评估

- **当前设计**：report_engine.py 直接调用 wudao_aStock MCP 工具
- **风险**：MCP 工具的稳定性、频率限制、数据质量都无法保证
- **建议**：增加 MCP 客户端封装层，实现连接池、超时控制、重试机制

---

## 3. MCP 工具依赖分析（重点）

### 3.1 工具清单与调用链

| 汇报类型 | 依赖工具 | 串行/并行 | 预计耗时 |
|----------|----------|-----------|----------|
| 盘前报 | sector_analysis, smart_hotlist, limit_stats, auction_market_scan, official_announcements | 串行 | 500ms + 网络延迟 |
| 午盘报 | market_overview, concept_ranking, capital_flow, broken_limit_up, watchlist_list | 串行 | 500ms + 网络延迟 |
| 盘后报 | limit_stats, hot_sectors, market_leaders_pick, limit_up_ladder, board_break_analysis, capital_flow | 串行 | 600ms + 网络延迟 |
| 盘中轮询 | limit_events, limit_down, anomaly_detection | 串行 | 300ms + 网络延迟 |

### 3.2 频率限制风险评估

根据 findings.md：
- MCP 工具批量调用可能触发频率限制
- 建议间隔 100ms，失败重试最多 3 次，指数退避策略

**实际风险：**
- 盘后报需调用 6 个工具，仅工具调用就需 600ms+
- 加上网络延迟（假设 200ms/次），总耗时可能超过 1.8s
- 如果某个工具超时或失败，整个报告生成将失败

### 3.3 并发控制方案建议

**方案 A：串行调用 + 限流（当前设计）**
- 优点：实现简单
- 缺点：执行时间长，失败风险高

**方案 B：并行调用 + 依赖排序（推荐）**
- 对无依赖的工具并发执行（如 limit_stats 和 hot_sectors 可并行）
- 对有依赖的工具串行执行（如 limit_up_ladder 依赖 limit_stats）
- 优点：减少总耗时，提高成功率
- 缺点：实现复杂度增加

**方案 C：队列 + 限流 + 重试（最佳实践）**
- 实现请求队列，控制并发数（建议 ≤3）
- 每个工具调用前检查频率限制
- 失败后指数退避重试（最多 3 次）
- 优点：最稳定，可扩展
- 缺点：实现复杂度最高

### 3.4 降级策略设计

| 场景 | 降级方案 |
|------|----------|
| MCP 工具超时 | 标注"数据获取中"，跳过该模块，继续生成报告 |
| MCP 工具不可用 | 使用缓存数据（如有），或标注"数据暂不可用" |
| 全部 MCP 工具失败 | 返回空报告 + 告警通知 |

---

## 4. 数据库设计评审

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
);
```

**评价：**
- ✅ `UNIQUE KEY uk_date_type` 防止同一天同一类型重复报告
- ⚠️ `content` 用 JSON 存储完整报告——查询效率低，不利于历史分析
- ⚠️ 缺少 `content_hash` 字段，无法检测内容重复
- ⚠️ 缺少 `status` 字段（success/failed/partial），无法追踪报告生成状态

### 4.2 report_subscriptions 表

```sql
CREATE TABLE report_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     VARCHAR(50) NOT NULL COMMENT '用户 ID',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL,
    enabled     BOOLEAN DEFAULT TRUE,
    channel     VARCHAR(20) DEFAULT 'qq' COMMENT '推送渠道',
    notify_time TIME COMMENT '自定义通知时间（可选）',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_type (user_id, report_type),
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (enabled)
);
```

**评价：**
- ✅ `UNIQUE KEY uk_user_type` 防止重复订阅
- ⚠️ `user_id VARCHAR(50)` 过长，建议固定长度（如 CHAR(32)）
- ⚠️ 没有用户表关联，数据完整性存疑
- ⚠️ 缺少 `last_sent_at` 字段，无法追踪推送历史

### 4.3 intraday_alerts 表（重点问题）

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
);
```

**评价：**
- ❌ **缺少唯一约束**：同一股票同一时间段的重复告警可能被重复记录
- ⚠️ 缺少 `alert_source` 字段，无法追溯告警来源（哪个 MCP 工具触发）
- ⚠️ 缺少 `resolved` 字段，无法追踪告警处理状态

**建议修复：**
```sql
-- 增加唯一约束
UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time)),

-- 增加追溯字段
alert_source VARCHAR(50) COMMENT '告警来源工具',
resolved BOOLEAN DEFAULT FALSE COMMENT '是否已处理',
```

### 4.4 sector_filter_candidates/reports 表

- 这两个表属于独立功能（行业 ETF 成分股筛选），与汇报模块无直接关系
- **建议**：拆分到独立模块，避免与汇报模块耦合

---

## 5. Cron 任务注册方案评估

### 5.1 Cron 表达式验证

| 汇报类型 | Cron 表达式 | 问题 |
|----------|-------------|------|
| 盘前报 | `30 08 * * 1-5` | ✅ 基本正确，但节假日仍触发 |
| 午盘报 | `30 11 * * 1-5` | ✅ 基本正确，但节假日仍触发 |
| 盘后报 | `30 15 * * 1-5` | ✅ 基本正确，但节假日仍触发 |
| 盘中轮询 | `0 10,11,12,13,14 * * 1-5` | ⚠️ 与午盘报时间重叠（11:00 vs 11:30） |

### 5.2 节假日判断问题

**当前设计：**
- cron 表达式限定 `1-5`（周一至周五）
- **问题**：无法排除法定节假日和调休周末

**建议方案：**
1. **脚本内增加交易日判断逻辑**：
   - 使用 `tushare` 或 `akshare` 的交易日历 API
   - 缓存本地交易日历，减少 API 调用
2. **节假日配置表**（可选）：
   - 在数据库中维护节假日列表
   - 脚本启动时检查当天是否为交易日

### 5.3 任务执行状态监控建议

- **增加执行日志表**：记录每次 cron 任务的执行时间、状态、耗时
- **失败告警机制**：报告生成失败时，通过 QQ/邮件通知负责人
- **健康检查接口**：提供 HTTP 接口，监控各汇报类型的最近一次成功时间

---

## 6. 技术决策点汇总

### 6.1 数据源选择策略

| 决策点 | 当前设计 | 建议方案 | 依据 |
|--------|----------|----------|------|
| MCP 工具调用 | 无控制 | 队列 + 限流 + 重试（方案 C） | findings.md 已指出频率限制风险 |
| 数据源切换 | 纯 MCP | MCP 为主，PG 为辅 | 混合架构方向要求双轨策略 |
| 降级策略 | 缺失 | 标注"数据暂不可用"，继续生成报告 | 生产环境必需 |

### 6.2 消息推送机制

| 决策点 | 当前设计 | 建议方案 | 依据 |
|--------|----------|----------|------|
| QQ 消息长度 | 未定义 | 4000 字符阈值，自动分片 | QQBot API 限制 |
| 推送渠道 | 仅 QQ | 支持多渠道（微信/钉钉/Telegram） | 扩展方向第 5 条 |
| 推送频率 | 固定时间 | 支持自定义通知时间 | report_subscriptions.notify_time |

### 6.3 错误隔离与部分成功策略

**当前设计：**
- report_engine.py 作为单入口，所有汇报类型共用一个引擎
- 缺乏错误隔离机制

**建议方案：**
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

### 6.4 扩展性评估

| 场景 | 当前架构支撑能力 | 建议改进 |
|------|------------------|----------|
| 新增汇报类型（如周报、月报） | ⚠️ 需修改 report_engine.py | 使用插件化设计，新增 reporter 即可 |
| 新增 MCP 工具 | ⚠️ 需修改各 reporter | 抽象 MCP 客户端接口，统一调用 |
| 新增推送渠道 | ⚠️ 需修改 formatters.py | 抽象推送接口，支持多渠道 |

---

## 7. 风险与缓解措施（按优先级排序）

### P0：MCP 单点故障（无降级方案）

**问题描述：**
- MCP 工具的稳定性、频率限制、数据质量都无法保证
- 如果 MCP 不可用，整个新模块瘫痪

**影响范围：**
- 所有汇报类型（盘前报/午盘报/盘后报/盘中轮询）

**缓解措施：**
1. 实现请求队列 + 限流 + 指数退避重试（方案 C）
2. 增加降级策略：MCP 不可用时，标注"数据暂不可用"，继续生成报告
3. 监控 MCP 工具可用性，设置告警阈值（如连续失败 3 次触发告警）

**责任人：** tech-expert  
**预计工作量：** 2h

### P1：intraday_alerts 去重机制缺失

**问题描述：**
- intraday_alerts 表缺少唯一约束，同一异动可能被重复记录
- 每小时轮询可能产生重复告警

**影响范围：**
- 盘中轮询（intraday_alert）

**缓解措施：**
1. 增加唯一约束：`UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time))`
2. 增加 `alert_source` 字段，追溯告警来源
3. 增加 `resolved` 字段，追踪告警处理状态

**责任人：** tech-expert  
**预计工作量：** 0.5h

### P1：Cron 节假日判断缺失

**问题描述：**
- cron 表达式限定 `1-5`（周一至周五），但无法排除法定节假日和调休周末
- 脚本在节假日仍会触发，导致空跑或错误数据

**影响范围：**
- 所有汇报类型

**缓解措施：**
1. 脚本内增加交易日判断逻辑（使用 tushare/akshare 交易日历 API）
2. 缓存本地交易日历，减少 API 调用
3. 节假日配置表（可选）

**责任人：** tech-expert  
**预计工作量：** 1h

### P2：QQ 消息长度限制无拆分逻辑

**问题描述：**
- QQ 消息单条长度有限（约 4000 字符），长报告需拆分
- 当前设计未定义拆分策略

**影响范围：**
- 盘后报（内容最完整，可能超过 4000 字符）

**缓解措施：**
1. 设置每条消息最大 4000 字符
2. 超长内容分多条发送
3. 关键信息优先展示（如指数收盘点位、涨跌停统计）

**责任人：** tech-expert  
**预计工作量：** 0.5h

### P3：错误处理/重试机制缺失

**问题描述：**
- findings.md 提到了频率限制和重试策略，但技术设计中没有具体的实现方案
- 没有监控告警机制——报告生成失败无人知晓

**影响范围：**
- 所有汇报类型

**缓解措施：**
1. 实现指数退避重试（最多 3 次）
2. 增加执行日志表，记录每次 cron 任务的执行状态
3. 失败告警机制（QQ/邮件通知负责人）

**责任人：** tech-expert  
**预计工作量：** 1.5h

### P4：混合架构方向不符合

**问题描述：**
- 当前设计是纯脚本规则模式（report_engine.py → reporters → MCP）
- 缺少 AI 智能体介入点（如盘前报的智能摘要、情景假设）
- 与 CIA 倾向的"AI 智能体模式 + 脚本规则模式双轨"整合方向不符

**影响范围：**
- 盘前报/盘后报（需要 AI 增强）

**缓解措施：**
1. 在 report_engine.py 中增加 AI 增强层
2. 对关键汇报类型（盘前报/盘后报）调用 LLM 生成自然语言总结
3. 中期演进：新模块增加 AI 增强层，提升内容质量

**责任人：** tech-expert + system-architect  
**预计工作量：** 2h

---

## 8. 混合架构方向评估（CIA 特别关注）

### 8.1 当前设计与混合架构的匹配度

| 维度 | 当前设计 | 混合架构要求 | 匹配度 |
|------|----------|--------------|--------|
| AI 智能体模式 | ❌ 缺失 | 盘前报/盘后报需要 LLM 摘要 | 低 |
| 脚本规则模式 | ✅ 完整 | 午盘报/盘后报/盘中轮询适合脚本模式 | 高 |
| 数据源双轨策略 | ❌ 纯 MCP | 本地 PG 为主，MCP 为辅 | 低 |
| 共享基础设施 | ⚠️ 未定义 | QQ 推送通道、数据库、节假日判断逻辑 | 中 |

**结论：** 当前设计**不符合**"AI 智能体模式 + 脚本规则模式双轨"的整合方向。

### 8.2 调整建议

1. **增加 AI 增强层**：
   - 在 report_engine.py 中增加 `ai_enhancer.py` 模块
   - 对盘前报/盘后报调用 LLM 生成自然语言总结
   - 午盘报/盘中轮询保持脚本规则模式

2. **数据源双轨策略**：
   - 本地 PG 为主：index_quotes, etf_alpha_signals, risk_alerts 等现有表
   - MCP 为辅：concept_ranking, capital_flow, limit_up_ladder 等 PG 中不存在的数据
   - 按需切换：优先使用 PG 数据，PG 无数据时 fallback 到 MCP

3. **共享基础设施**：
   - QQ 推送通道：复用现有 QQBot 接口
   - 数据库：复用现有 investdb（新增 market_reports, report_subscriptions, intraday_alerts 表）
   - 节假日判断逻辑：复用现有交易日历 API

### 8.3 渐进式演进路径

| 阶段 | 时间 | 目标 | 触发条件 |
|------|------|------|----------|
| **阶段 1**（短期） | 0-2 周 | 方案 A：完全独立运行，共享 QQ 推送通道 | MCP 连续 30 天成功率 > 95% |
| **阶段 2**（中期） | 2-4 周 | 增加 AI 增强层，提升内容质量 | MCP 稳定性验证通过 |
| **阶段 3**（长期） | 4-8 周 | 方案 C：Morning Briefing 作为盘前报实现 | 数据一致性验证通过 |

---

## 9. 总结与建议

### 9.1 架构优势
1. **模块化设计**：report_engine.py + 模块化 reporters，职责清晰
2. **汇报体系完整**：覆盖盘前/午盘/盘后/盘中四种场景
3. **数据库设计合理**：market_reports, report_subscriptions, intraday_alerts 表结构基本合理

### 9.2 关键问题
1. **P0**：MCP 单点故障（无降级方案）
2. **P1**：intraday_alerts 去重机制缺失
3. **P1**：Cron 节假日判断缺失
4. **P2**：QQ 消息长度限制无拆分逻辑
5. **P3**：错误处理/重试机制缺失
6. **P4**：混合架构方向不符合

### 9.3 实施建议
1. **优先解决 P0-P1 问题**（MCP 并发控制、intraday_alerts 去重、Cron 节假日判断）
2. **中期增加 AI 增强层**，提升内容质量
3. **长期逐步迁移到方案 C**，实现 Morning Briefing 与新汇报模块的统一管理

### 9.4 工作量估算

| 任务 | 工作量 | 优先级 |
|------|--------|--------|
| MCP 并发控制 + 降级策略 | 2h | P0 |
| intraday_alerts 去重机制 | 0.5h | P1 |
| Cron 节假日判断 | 1h | P1 |
| QQ 消息拆分逻辑 | 0.5h | P2 |
| 错误处理 + 重试机制 | 1.5h | P3 |
| AI 增强层（中期） | 2h | P4 |
| **合计** | **7.5h** | - |

---

*本报告由 tech-expert 分析，2026-06-07*  
*协作方：system-architect（架构设计评审）*
