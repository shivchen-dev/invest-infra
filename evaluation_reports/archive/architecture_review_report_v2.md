# 综合市场汇报系统 — 架构评审报告 v2.0

**报告日期:** 2026-06-07  
**版本:** v2.0（统一报告引擎终态）  
**分析者:** system-architect（系统架构分析师）  
**协作方:** data-architect, tech-expert, CIA  
**参考文档:** 
- task_plan.md (v2.0 实施计划)
- technical_design.md (v2.0 技术设计)
- findings.md (审计发现 v2.0)
- integration_design.md (整合方案设计)
- new_report_module_analysis.md (新模块架构分析)
- existing_morning_briefing_architecture.md (现有 Morning Briefing 分析)

---

## 1. 执行摘要

### 1.1 核心变更（v1.0 → v2.0）

| 维度 | v1.0 | v2.0 |
|------|------|------|
| **架构终态** | 方案 A：完全独立运行 | 统一报告引擎（单一出口） |
| **整合路径** | 渐进式演进（4-8 周后评估） | 三阶段强制推进（0-8 周） |
| **数据源策略** | 双轨并行，各自独立 | 双轨并行 → 统一融合 → 单一引擎 |
| **总工作量** | 0h（短期）+ 15-20h（长期） | 22h（分三阶段） |
| **新增组件** | 无 | Morning Briefing 适配层、AI 增强层、数据融合仲裁规则 |

### 1.2 核心结论

**v2.0 架构终态：统一报告引擎作为演化终点，一次报告、一个出口。**

- ✅ Morning Briefing 数据（PG + RssCast）与新模块数据（wudao_aStock MCP）最终汇入统一报告引擎
- ✅ 三阶段路径确保平滑过渡，降低迁移风险
- ✅ 数据融合仲裁规则明确：数值用 MCP 实时数据，总结用 Morning Briefing AI 判断
- ⚠️ 总工作量从 v1.0 的预估 12.5h 增加到 22h（增加 9.5h 用于双轨运行和统一引擎）

### 1.3 推荐结论

**支持 v2.0 三阶段路径，但需关注以下风险：**
1. **MCP 单点故障**（P0）— 统一引擎内必须增加降级策略
2. **数据融合冲突**（P1）— 阶段 2 优先定义仲裁规则
3. **旧架构退役风险**（P2）— 保留退役脚本，阶段 3 演练回滚

---

## 2. 现有系统分析（Morning Briefing）

### 2.1 架构概览

```
┌─────────────────────────────────────────────┐
│              Morning Briefing               │
│  ┌───────────┐    ┌───────────┐             │
│  │ WOA Agent │ →  │   CIA     │             │
│  │ (策略分析) │    │ (综合研判) │             │
│  └───────────┘    └───────────┘             │
│         │                    │               │
│         ▼                    ▼               │
│  ┌──────────────┐  ┌──────────────────┐     │
│  │ PostgreSQL   │  │ RssCast MCP      │     │
│  │ (investdb)   │  │ (新闻/公告)       │     │
│  └──────────────┘  └──────────────────┘     │
│         │                    │               │
│         ▼                    ▼               │
│  ┌──────────────────────────────────┐        │
│  │      QQ Bot 推送                 │        │
│  └──────────────────────────────────┘        │
└─────────────────────────────────────────────┘
```

### 2.2 核心特点

| 维度 | 说明 |
|------|------|
| **执行模式** | AI 智能体模式（WOA → CIA 多 Agent 协作） |
| **数据源** | 本地 PG (investdb) + RssCast MCP |
| **汇报类型** | 盘前洞察（综合研判、跨维度推理、情景假设） |
| **触发方式** | 手动触发 / 定时任务 |
| **推送渠道** | QQ Bot |

### 2.3 已知风险点

| 风险 | 等级 | 说明 |
|------|------|------|
| MCP 依赖 | P1 | RssCast MCP 稳定性未知 |
| 数据覆盖 | P2 | 不采集 concept_ranking、capital_flow 等实时板块数据 |
| 推送渠道 | P3 | 仅支持 QQ Bot，不支持 QQ Channel |

### 2.4 与 v2.0 的兼容性评估

**优势：**
- ✅ Morning Briefing 经过生产验证，运行稳定
- ✅ AI 智能体模式适合盘前报的【宏观环境】【强势行业】【情绪判断】板块
- ✅ PG 数据可作为统一引擎的历史数据源

**挑战：**
- ⚠️ 需要新增 `morning_briefing_adapter.py` 适配层读取 PG 数据
- ⚠️ 盘前报与 Morning Briefing 内容高度重叠，需明确分工
- ⚠️ 旧架构退役需在阶段 3 谨慎执行

---

## 3. 新模块分析（technical_design v2.0）

### 3.1 汇报体系

| 汇报类型 | 触发时间 | Cron 表达式 | MCP 工具依赖数 | 预计耗时 |
|----------|----------|-------------|----------------|----------|
| **盘前报** | 08:30 | `30 08 * * 1-5` | 5 | 500ms + 网络延迟 |
| **午盘报** | 11:30 | `30 11 * * 1-5` | 5 | 500ms + 网络延迟 |
| **盘后报** | 15:30 | `30 15 * * 1-5` | 6 | 600ms + 网络延迟 |
| **盘中轮询** | 每小时 | `0 10,11,12,13,14 * * 1-5` | 3 | 300ms + 网络延迟 |

### 3.2 统一报告引擎架构（v2.0）

```
                    ┌─────────────────────┐
                    │     QQ Channel      │
                    │   （单一出口）       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Report Engine     │
                    │   (统一报告引擎)     │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                    │
┌────────▼────────┐ ┌────────▼────────┐  ┌────────▼────────┐
│ Morning Brief │  │   盘前报模块    │  │   盘后报模块    │
│ 适配层(PG)      │  │ (wudao_aStock) │  │ (wudao_aStock) │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   AI 增强层          │
                    │ (数据融合/仲裁)      │
                    └─────────────────────┘
```

### 3.3 核心模块职责

| 模块 | 路径 | 职责 | v2.0 变更 |
|------|------|------|-----------|
| `report_engine.py` | `scripts/` | 统一报告引擎主入口 | ✅ 新增，替代独立运行 |
| `morning_briefing_adapter.py` | `modules/` | Morning Briefing 数据适配层 | ✅ **v2.0 新增** |
| `pre_market.py` | `modules/reports/` | 盘前报数据组装 | ⚠️ 需对接 AI 增强层 |
| `midday.py` | `modules/reports/` | 午盘报数据组装 | ✅ 保持不变 |
| `post_market.py` | `modules/reports/` | 盘后报数据组装 | ⚠️ 需对接 AI 增强层 |
| `intraday_alert.py` | `modules/reports/` | 盘中异动监控 | ⚠️ 需增加去重机制 |
| `formatters.py` | `modules/` | 统一消息格式化（六板块） | ✅ 对齐 Morning Briefing |
| `db.py` | `modules/` | 数据库操作 | ✅ 保持不变 |
| `mcp_client.py` | `modules/` | MCP 客户端封装（限流 + 重试） | ✅ **v2.0 新增** |

### 3.4 技术风险清单（按优先级）

#### P0：MCP 单点故障（无降级方案）

**问题描述：**
- 新汇报模块完全依赖 wudao_aStock MCP 工具，无降级方案
- 盘后报需串行调用 6 个工具，总延迟 > 3s，任一超时导致整报告失败

**v2.0 缓解措施：**
- 统一引擎内增加降级策略（标注"数据暂不可用"，继续生成报告）
- MCP 客户端封装层实现限流 + 重试（指数退避，最多 3 次）
- 监控 MCP 工具可用性，连续失败 3 次触发告警

**责任人：** tech-expert  
**预计工作量：** 2h

#### P1：intraday_alerts 去重机制缺失

**问题描述：**
- intraday_alerts 表缺少唯一约束，同一异动可能被重复记录
- 每小时轮询可能产生重复告警

**v2.0 修复方案：**
```sql
-- 增加唯一约束
UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time)),

-- 增加追溯字段
alert_source VARCHAR(50) COMMENT '告警来源工具',
resolved BOOLEAN DEFAULT FALSE COMMENT '是否已处理',
```

**责任人：** tech-expert  
**预计工作量：** 0.5h

#### P1：Cron 节假日判断缺失

**问题描述：**
- cron 表达式限定 `1-5`（周一至周五），但无法排除法定节假日和调休周末
- 脚本在节假日仍会触发，导致空跑或错误数据

**v2.0 缓解措施：**
- 脚本内增加交易日判断逻辑（使用 tushare/akshare 交易日历 API）
- 缓存本地交易日历，减少 API 调用
- 节假日配置表（可选）

**责任人：** tech-expert  
**预计工作量：** 1h

#### P2：QQ 消息长度限制无拆分逻辑

**问题描述：**
- QQ 消息单条长度有限（约 4000 字符），长报告需拆分
- 盘后报内容最完整，可能超过 4000 字符

**v2.0 缓解措施：**
- 设置每条消息最大 4000 字符
- 超长内容分多条发送
- 关键信息优先展示（指数收盘点位、涨跌停统计）

**责任人：** tech-expert  
**预计工作量：** 0.5h

#### P3：错误处理/重试机制缺失

**问题描述：**
- report_engine.py 作为单入口，缺乏错误隔离机制
- 没有监控告警机制——报告生成失败无人知晓

**v2.0 缓解措施：**
- 实现"部分成功"策略：某模块失败不影响其他模块
- 增加执行日志表，记录每次 cron 任务的执行状态
- 失败告警机制（QQ/邮件通知负责人）

**责任人：** tech-expert  
**预计工作量：** 1.5h

#### P4：混合架构方向不符合

**问题描述：**
- 当前设计是纯脚本规则模式（report_engine.py → reporters → MCP）
- 缺少 AI 智能体介入点（如盘前报的智能摘要、情景假设）
- 与 CIA 倾向的"AI 智能体模式 + 脚本规则模式双轨"整合方向不符

**v2.0 缓解措施：**
- 新增 `morning_briefing_adapter.py` 适配层，注入 Morning Briefing AI 判断
- 数据融合仲裁规则：数值用 MCP 实时数据，总结用 Morning Briefing AI 判断
- 阶段 2 重点任务

**责任人：** tech-expert + system-architect  
**预计工作量：** 2h

---

## 4. 整合方案推荐（v2.0 三阶段路径）

### 4.1 架构终态：统一报告引擎

**核心决策：** 从"两套独立系统"升级为"统一报告引擎作为终态"。

| 版本 | 架构 | 出口 | 数据源 |
|------|------|------|--------|
| v1.0 | 方案 A 完全独立，新 Morning Briefing 和旧系统各跑各的 | 两个出口 | 双轨并行，各自独立 |
| **v2.0** | **双轨并行 → 统一融合 → 单一引擎** | **一个出口** | **双轨并行，最终归一** |

### 4.2 三阶段路径详解

#### 阶段 1：方案 A 独立运行 + 新模块试跑（0-2 周）

**目标：**
- 新模块按统一模板生成报告（独立运行，不影响现有 Morning Briefing）
- 试跑验证数据质量和格式
- **不上 Cron**，手动触发测试

**任务清单：**

| 编号 | 任务 | 工作量 | 状态 |
|------|------|--------|------|
| 1.1 | DDL 建表（market_reports, report_subscriptions, intraday_alerts） | 0.5h | ⬜ |
| 1.2 | report_engine.py 主框架 | 1h | ⬜ |
| 1.3 | formatters.py 统一报告模板（参考 Morning Briefing 六板块） | 1h | ⬜ |
| 1.4 | pre_market.py 盘前报模块 | 1.5h | ⬜ |
| 1.5 | midday.py 午盘报模块 | 1h | ⬜ |
| 1.6 | post_market.py 盘后报模块 | 1.5h | ⬜ |
| 1.7 | intraday_alert.py 盘中异动模块 | 1h | ⬜ |
| 1.8 | QQ 推送封装 | 0.5h | ⬜ |
| 1.9 | MCP 客户端封装（限流 + 重试） | 0.5h | ⬜ |
| 1.10 | 交易日判断模块 | 0.5h | ⬜ |

**阶段 1 小计：9h**

**验收标准：**
- [ ] 4 种报告类型均可生成（手动触发）
- [ ] 报告格式与 Morning Briefing 对齐（六板块结构）
- [ ] QQ 推送成功
- [ ] 无 Cron 注册，纯试跑

#### 阶段 2：统一模板设计 + 数据源双轨试运行（2-4 周）

**目标：**
- 确定统一报告模板和数据融合规则
- Morning Briefing 数据接入新模块（作为 AI 增强层）
- 双轨并行运行，对比验证

**任务清单：**

| 编号 | 任务 | 工作量 | 状态 |
|------|------|--------|------|
| 2.1 | 统一报告模板定稿 | 1h | ⬜ |
| 2.2 | Morning Briefing 适配层（读取 PG 数据） | 1.5h | ⬜ |
| 2.3 | 数据融合逻辑（AI 增强层注入） | 1.5h | ⬜ |
| 2.4 | 数据冲突仲裁规则（优先级定义） | 0.5h | ⬜ |
| 2.5 | 双轨试运行（Cron 注册，不淘汰旧架构） | 1h | ⬜ |
| 2.6 | 数据质量对比验证（连续 2 周） | - | ⬜ |

**阶段 2 小计：6h**

**验收标准：**
- [ ] 统一模板定稿并文档化
- [ ] Morning Briefing 数据成功注入新模块报告
- [ ] 双轨并行运行 2 周无严重故障
- [ ] 用户确认报告质量达标

#### 阶段 3：统一报告引擎上线（4-8 周）

**目标：**
- 统一报告引擎正式接管所有报告
- Morning Briefing 旧架构退役
- 单一数据流、单一出口

**任务清单：**

| 编号 | 任务 | 工作量 | 状态 |
|------|------|--------|------|
| 3.1 | 统一报告引擎重构 | 3h | ⬜ |
| 3.2 | 旧架构适配/退役脚本 | 1h | ⬜ |
| 3.3 | 全量 Cron 切换 | 0.5h | ⬜ |
| 3.4 | 回滚方案演练 | 0.5h | ⬜ |
| 3.5 | 监控告警上线 | 1h | ⬜ |
| 3.6 | 文档更新 + 交接 | 1h | ⬜ |

**阶段 3 小计：7h**

**触发条件：**
- MCP 连续 30 天成功率 > 95%
- 新模块稳定运行 2 周无严重故障
- 用户反馈良好（活跃率 > 80%）

**验收标准：**
- [ ] 统一报告引擎接管所有报告类型
- [ ] Morning Briefing 旧架构停用
- [ ] 单一出口推送 QQ
- [ ] 回滚方案可用

### 4.3 数据融合仲裁规则（v2.0 新增）

| 场景 | 仲裁规则 |
|------|----------|
| **数值冲突**（如涨停家数） | MCP 实时数据优先 |
| **情绪判断冲突** | Morning Briefing AI 总结优先 |
| **数据缺失** | 降级使用缓存 + 标注"数据暂不可用" |
| **全部数据不可用** | 返回告警报告 + 跳过该模块 |

### 4.4 三阶段路径对比（v1.0 vs v2.0）

| 维度 | v1.0 渐进式演进 | v2.0 三阶段强制推进 |
|------|-----------------|---------------------|
| **架构终态** | 方案 A 独立运行（长期） | 统一报告引擎（4-8 周） |
| **总工作量** | 0h + 15-20h（不确定） | 22h（明确分阶段） |
| **数据融合** | 无明确规则 | 仲裁规则明确（数值用 MCP，总结用 MB） |
| **Morning Briefing 适配层** | 无 | 阶段 2 重点任务 |
| **风险等级** | 低（隔离好） | 中（耦合增加） |
| **推荐指数** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 5. 技术实施路径（22h 版本）

### 5.1 Phase 分解与甘特图

```
时间轴：0-2 周          2-4 周              4-8 周
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
Phase 1 │ 独立试跑     │                 │              │
(9h)    │ DDL + 引擎   │                 │              │
        │ + 4 模块     │                 │              │
        ├──────────────┤                 │              │
Phase 2 │              │ 统一模板        │              │
(6h)    │              │ + MB 适配层     │              │
        │              │ + 双轨试运行    │              │
        ├──────────────┼───────────────┤              │
Phase 3 │              │               │ 统一引擎上线  │
(7h)    │              │               │ + 旧架构退役  │
        └──────────────┴───────────────┴──────────────┘
```

### 5.2 依赖关系分析

**串行依赖（必须按顺序执行）：**
- Phase 1 → Phase 2：新模块需先试跑验证，才能接入 Morning Briefing 数据
- Phase 2 → Phase 3：双轨运行需验证 2 周无故障，才能退役旧架构

**并行机会（可在 Phase 内并行）：**
- Phase 1 中：4 个 reporter 模块可并行开发（pre/midday/post/intraday）
- Phase 2 中：统一模板定稿与 Morning Briefing 适配层可部分并行

### 5.3 工作量估算汇总

| Phase | 核心任务 | 工作量 | 累计 |
|-------|----------|--------|------|
| **Phase 1** | DDL + report_engine + 4 模块 + MCP 客户端 + QQ 推送 | 9h | 9h |
| **Phase 2** | 统一模板 + MB 适配层 + 数据融合 + 双轨试运行 | 6h | 15h |
| **Phase 3** | 统一引擎重构 + 旧架构退役 + Cron 切换 + 监控告警 | 7h | 22h |
| **合计** | - | **22h** | - |

*相比原计划 12.5h，增加 9.5h 用于双轨运行和统一引擎*

### 5.4 技术决策点

| 决策点 | 方案 | 依据 |
|--------|------|------|
| **数据库设计** | 新建专用表（market_reports, report_subscriptions, intraday_alerts） | 不混用现有 investdb 表，避免耦合 |
| **MCP 工具调用策略** | 队列 + 限流 + 重试（指数退避，最多 3 次） | findings.md 已指出频率限制风险 |
| **QQ 推送接口封装** | 复用现有 QQBot 逻辑，新增 QQ Channel 支持 | 统一出口需求 |
| **数据融合仲裁** | 数值用 MCP，总结用 Morning Briefing | v2.0 新增规则 |
| **旧架构退役** | 阶段 3 执行，保留退役脚本和回滚方案 | 降低迁移风险 |

### 5.5 测试策略

| 测试类型 | Phase | 测试内容 | 验收标准 |
|----------|-------|----------|----------|
| **单元测试** | Phase 1 | MCP 客户端、formatters、db 模块 | 覆盖率 > 80% |
| **集成测试** | Phase 1 | report_engine + 4 个 reporter 模块 | 手动触发 4 种报告均成功 |
| **端到端测试** | Phase 2 | 双轨并行运行，对比数据一致性 | 连续 2 周无严重故障 |
| **回滚演练** | Phase 3 | 模拟统一引擎故障，回退到旧架构 | 回滚时间 < 30 分钟 |

---

## 6. 数据库架构分析

### 6.1 DDL 审查（v2.0）

#### market_reports 表

```sql
CREATE TABLE market_reports (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL,
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL,
    content     JSON COMMENT '完整报告内容',
    summary     JSON COMMENT '汇总数据（用于快速查询）',
    source      ENUM('morning_briefing', 'new_module', 'unified') DEFAULT 'unified' COMMENT '数据来源',
    status      ENUM('success', 'failed', 'partial') DEFAULT 'success' COMMENT '生成状态',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_date_type (trade_date, report_type),
    INDEX idx_trade_date (trade_date),
    INDEX idx_report_type (report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评价：**
- ✅ `UNIQUE KEY uk_date_type` 防止同一天同一类型重复报告
- ✅ `source` 字段支持追踪数据来源（morning_briefing/new_module/unified）
- ✅ `status` 字段支持追踪生成状态（success/failed/partial）
- ⚠️ `content` 用 JSON 存储完整报告——查询效率低，不利于历史分析
- ⚠️ 缺少 `content_hash` 字段，无法检测内容重复

#### report_subscriptions 表

```sql
CREATE TABLE report_subscriptions (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id     CHAR(32) NOT NULL COMMENT '用户 ID',
    report_type ENUM('pre_market', 'midday', 'post_market', 'intraday_alert') NOT NULL,
    enabled     BOOLEAN DEFAULT TRUE,
    channel     VARCHAR(20) DEFAULT 'qq' COMMENT '推送渠道',
    notify_time TIME COMMENT '自定义通知时间（可选）',
    last_sent_at DATETIME COMMENT '最后推送时间',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_user_type (user_id, report_type),
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评价：**
- ✅ `UNIQUE KEY uk_user_type` 防止重复订阅
- ✅ `last_sent_at` 字段支持追踪推送历史
- ⚠️ 没有用户表关联，数据完整性存疑（但当前单用户场景可接受）

#### intraday_alerts 表（v2.0 已修复）

```sql
CREATE TABLE intraday_alerts (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    trade_date  DATE NOT NULL,
    alert_time  DATETIME NOT NULL,
    alert_type  ENUM('limit_up', 'limit_down', 'break_seal', 'anomaly') NOT NULL,
    stock_code  VARCHAR(10),
    stock_name  VARCHAR(50),
    detail      JSON COMMENT '异动详情',
    alert_source VARCHAR(50) COMMENT '告警来源工具',
    notified    BOOLEAN DEFAULT FALSE,
    resolved BOOLEAN DEFAULT FALSE COMMENT '是否已处理',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time)),
    INDEX idx_trade_date (trade_date),
    INDEX idx_alert_type (alert_type),
    INDEX idx_notified (notified)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**评价：**
- ✅ `UNIQUE KEY uk_stock_time` 防止重复告警（v2.0 已修复）
- ✅ `alert_source` 字段支持追溯告警来源（v2.0 已新增）
- ✅ `resolved` 字段支持追踪告警处理状态（v2.0 已新增）

### 6.2 JSON 字段索引优化建议

**问题：** `content`、`summary`、`detail` 等 JSON 字段缺少 GIN 索引，查询性能受限。

**建议方案：**
```sql
-- 为常用查询字段添加 GIN 索引
ALTER TABLE market_reports ADD INDEX idx_summary (summary(1024));
ALTER TABLE intraday_alerts ADD INDEX idx_detail (detail(1024));
```

**注意：** MySQL 5.7+ 支持 JSON 列的虚拟生成列 + 索引，可进一步提升查询性能。

### 6.3 审计字段补充建议

**问题：** 当前表缺少 `updated_at`（除 report_subscriptions 外）、`created_by`、`deleted_at` 等审计字段。

**建议方案：**
```sql
-- market_reports 表补充
ALTER TABLE market_reports 
    ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ADD COLUMN created_by VARCHAR(50) DEFAULT 'report_engine',
    ADD COLUMN deleted_at DATETIME DEFAULT NULL;

-- intraday_alerts 表补充
ALTER TABLE intraday_alerts 
    ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ADD COLUMN resolved_by VARCHAR(50) DEFAULT NULL;
```

---

## 7. 风险评估与缓解措施

### 7.1 风险矩阵（v2.0）

| 优先级 | 风险 | 影响范围 | 缓解措施 | 责任人 | 预计工作量 |
|--------|------|----------|----------|--------|------------|
| **P0** | MCP 单点故障无降级 | 所有汇报类型 | 统一引擎内增加降级策略（标注"数据暂不可用"，继续生成报告） | tech-expert | 2h |
| **P1** | 数据融合冲突无仲裁规则 | 阶段 2 双轨运行 | 阶段 2 优先定义仲裁规则（数值用 MCP，总结用 MB） | tech-expert + system-architect | 0.5h |
| **P1** | intraday_alerts 去重缺失 | 盘中轮询 | UNIQUE KEY uk_stock_time (stock_code, alert_type, DATE(alert_time)) | tech-expert | 0.5h |
| **P1** | Cron 节假日误触发 | 所有汇报类型 | 脚本内增加交易日判断逻辑（tushare/akshare 交易日历 API） | tech-expert | 1h |
| **P2** | 统一模板变更影响 MB 兼容性 | 阶段 2 双轨运行 | 阶段 1 先对齐格式，确保六板块结构一致 | tech-expert | 0.5h |
| **P2** | 旧架构退役后无法快速回滚 | 阶段 3 | 保留退役脚本，阶段 3 演练回滚方案 | tech-expert | 0.5h |
| **P3** | 双轨运行期间用户收到两份报告 | 阶段 2 | 阶段 2 只推一份（新模块），验证后替换 | tech-expert | 0h |
| **P4** | JSON 查询性能受限 | 历史数据分析 | GIN 索引 + 虚拟生成列 | tech-expert | 0.5h |

### 7.2 架构约束

| 约束 | 说明 | 影响 |
|------|------|------|
| **混合架构方向** | CIA 要求"AI 智能体模式 + 脚本规则模式双轨" | 阶段 2 必须增加 AI 增强层（morning_briefing_adapter.py） |
| **数据源双轨策略** | 本地 PG 为主，MCP 为辅 | 新模块需实现 PG/MCP 切换逻辑 |
| **统一出口需求** | 用户只收到一份报告，不重复 | 阶段 3 必须退役 Morning Briefing 旧架构 |

### 7.3 实施约束

| 约束 | 说明 | 影响 |
|------|------|------|
| **现有 Morning Briefing 稳定性** | 不宜大改 | 阶段 1-2 保持独立运行，阶段 3 再退役 |
| **MCP 工具可用性** | wudao_aStock 稳定性未知 | 需验证 MCP 连续 30 天成功率 > 95%（阶段 3 触发条件） |
| **数据一致性验证** | 两个系统数据可能矛盾 | 需建立数据一致性监控机制（阶段 2 双轨运行期间） |

---

## 8. 最终建议

### 8.1 立即执行项（Phase 1，0-2 周）

1. **DDL 建表** — market_reports、report_subscriptions、intraday_alerts
2. **report_engine.py 主框架** — 统一报告引擎入口
3. **4 个 reporter 模块** — pre_market、midday、post_market、intraday_alert
4. **MCP 客户端封装** — 限流 + 重试（指数退避，最多 3 次）
5. **QQ 推送封装** — 复用现有 QQBot 逻辑，新增 QQ Channel 支持
6. **交易日判断模块** — 避免节假日空跑

### 8.2 中期优化项（Phase 2，2-4 周）

1. **统一报告模板定稿** — 对齐 Morning Briefing 六板块结构
2. **Morning Briefing 适配层** — morning_briefing_adapter.py 读取 PG 数据
3. **数据融合逻辑** — AI 增强层注入（数值用 MCP，总结用 MB）
4. **数据冲突仲裁规则** — 优先级定义（见 4.3 节）
5. **双轨试运行** — Cron 注册，不淘汰旧架构，连续 2 周验证

### 8.3 长期演进项（Phase 3，4-8 周）

1. **统一报告引擎重构** — 接管所有报告类型
2. **旧架构退役脚本** — Morning Briefing 停用，保留回滚方案
3. **全量 Cron 切换** — 单一出口推送 QQ
4. **监控告警上线** — 执行日志表 + 失败告警机制
5. **文档更新 + 交接** — 技术文档、运维手册

### 8.4 可行性评估结论

| 维度 | 评估结果 | 说明 |
|------|----------|------|
| **技术可行性** | ✅ 高 | 架构清晰，模块职责明确，有成熟的技术栈支撑 |
| **实施风险** | ⚠️ 中 | MCP 稳定性未知，双轨运行期间需密切监控 |
| **工作量估算** | ✅ 合理 | 22h 分三阶段，每阶段目标明确，验收标准清晰 |
| **回滚可行性** | ✅ 高 | 阶段 1-2 保持独立运行，阶段 3 退役前演练回滚 |
| **长期可维护性** | ✅ 高 | 统一引擎架构支持后续扩展（AI 增强、多渠道推送等） |

**总体结论：v2.0 三阶段路径可行，推荐执行。**

---

## 附录 A：参考文档清单

| 文档 | 作者 | 日期 |
|------|------|------|
| task_plan.md (v2.0) | Arc | 2026-06-07 |
| technical_design.md (v2.0) | Arc | 2026-06-07 |
| findings.md (审计发现 v2.0) | Arc | 2026-06-07 |
| integration_design.md | system-architect | 2026-06-07 |
| new_report_module_analysis.md | tech-expert | 2026-06-07 |
| existing_morning_briefing_architecture.md | data-architect | 2026-06-07 |

## 附录 B：术语表

| 术语 | 说明 |
|------|------|
| **MCP** | Model Context Protocol，wudao_aStock 工具调用协议 |
| **PG** | PostgreSQL，本地数据库 investdb |
| **MB** | Morning Briefing，现有盘前洞察系统 |
| **AI 增强层** | morning_briefing_adapter.py + 数据融合仲裁规则 |
| **统一报告引擎** | report_engine.py，v2.0 架构终态 |

---

*本报告由 system-architect 分析，2026-06-07（v2.0）*  
*协作方：data-architect（现有架构分析）、tech-expert（新模块技术评估）、CIA（架构方向指导）*
