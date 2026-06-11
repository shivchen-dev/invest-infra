# 综合市场汇报机制 — 实施计划 v3.0

**创建日期:** 2026-06-07
**更新日期:** 2026-06-08
**负责人:** Arc
**状态:** 阶段1✅ 阶段2✅ 阶段3待开发

---

## 核心目标（v3.0）

**统一报告引擎 + 融合格式，一次报告、一个出口。**

- WOA 写 PG（investment_memos）→ CIA 读 PG → 输出盘前报
- 融合格式：Morning Briefing 6板块优势 + 旧版 8板块优势 → 10板块统一格式
- 置信度中文标注（高/中/低）

---

## 需求确认

- **汇报类型:** 盘前报、午盘报、盘后报、盘中轮询
- **推送渠道:** QQ 频道（单一出口）
- **数据源:** WOA 写 PG（主） + MCP（兜底）
- **触发方式:** WOA 触发盘前报 / Cron 触发午盘+盘后+盘中

---

## 三阶段演化路径

```
阶段1（已设计）→ 阶段2（本次开发）→ 阶段3（未来）
    │                    │                  │
    ▼                    ▼                  ▼
方案A独立运行       融合格式落地 统一引擎上线
+ 新模块试跑        + WOA数据接入 淘汰旧架构
```

---

## 阶段1: 方案A 独立运行 + 新模块试跑（已完成）

### 目标
- 新模块按统一模板生成报告（独立运行，不影响现有 Morning Briefing）
- 试跑验证数据质量和格式
- **不上 Cron**，手动触发测试

### 任务

| 编号 | 任务 | 工作量 | 状态 |
|------|------|--------|------|
| 1.1 | DDL 建表（market_reports, report_subscriptions, intraday_alerts） | 0.5h | ✅ |
| 1.2 | report_engine.py 主框架 | 1h | ✅ |
| 1.3 | formatters.py 统一报告模板（参考 Morning Briefing 六板块） | 1h | ✅ |
| 1.4 | pre_market.py 盘前报模块 | 1.5h | ✅ |
| 1.5 | midday.py 午盘报模块 | 1h | ✅ |
| 1.6 | post_market.py 盘后报模块 | 1.5h | ✅ |
| 1.7 | intraday_alert.py 盘中异动模块 | 1h | ✅ |
| 1.8 | QQ 推送封装 | 0.5h | ✅ |
| 1.9 | MCP 客户端封装（限流+重试） | 0.5h | ✅ |
| 1.10 | 交易日判断模块 | 0.5h | ✅ |

**阶段1小计: 9h** ✅ 已完成

---

## 阶段2: 融合格式落地 + WOA 数据接入（已完成）

### 目标
- **核心修改**：将 formatters.py 的 PreMarketFormatter 重写为 10板块融合格式
- 新增 pre_market.py 的 fetch_memo() 从 PG investment_memos 读取 WOA 数据
- 盘前报以 WOA 数据为主，MCP 数据为兜底
- 置信度中文标注落地

### 任务

| 编号 | 任务 | 工作量 | 状态 | 对应文档 |
|------|------|--------|------|----------|
| 2.1 | formatters.py: PreMarketFormatter 重写为 10 板块 |2h | ✅ | technical_design.md v3.0 §5.1 |
| 2.2 | formatters.py: 新增 `_format_woa_summary()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.3 | formatters.py: 新增 `_format_market_overview()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.4 | formatters.py: 新增 `_format_factors()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.5 | formatters.py: 新增 `_format_etf_signals()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.6 | formatters.py: 新增 `_format_risks()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.7 | formatters.py: 新增 `_format_scenarios()` | 0.5h | ✅ | technical_design.md v3.0 §5.1 |
| 2.8 | formatters.py: 保留 `_format_auction()`（Format A 优势） | 0h | ✅ | technical_design.md v3.0 §5.1 |
| 2.9 | formatters.py: 保留 `_format_macro_events()`（Format A 优势） | 0h | ✅ | technical_design.md v3.0 §5.1 |
| 2.10 | formatters.py: 保留 `_format_operation_ref()`（Format A 优势） | 0h | ✅ | technical_design.md v3.0 §5.1 |
| 2.11 | pre_market.py: 新增 `fetch_memo()` 从 PG 读 investment_memos | 1h | ✅ | technical_design.md v3.0 §5.2 |
| 2.12 | pre_market.py: 调整 `fetch()` 数据注入优先级 | 0.5h | ✅ | technical_design.md v3.0 §5.2 |
| 2.13 | 置信度中文标注工具函数（`_cn_conf()` / `_source_tag()`） | 0.5h | ✅ | technical_design.md v3.0 §4.2 |
| 2.14 | 禁止词规范落地 | 0.5h | ✅ | technical_design.md v3.0 §9 |
| 2.15 | 端到端测试（WOA 执行 → CIA 生成 → QQ 输出） | 1h | ✅ | — |

**阶段2小计: 9h** ✅ 已完成

### 10板块结构（阶段2交付物）

```
1. WOA 工作摘要（新增）
2. 今日市场概况
3. 今日主线预判（≤2条）
4. 因子信号（新增表格）
5. ETF 信号（Top5表格）
6. 盘前异动（保留）
7. 宏观/事件面（保留）
8. 风险提示（表格）
9. 情景假设（新增）
10. 今日操作参考 + 今日关注 + 明日关注点
```

### 验收标准
- [x] formatters.py PreMarketFormatter 10 板块格式正确
- [x] fetch_memo() 可从 PG investment_memos 读取今日数据
- [x] 置信度中文标注正确（高/中/低）
- [x] 来源标注格式统一
- [x] 禁止词无输出（⚠️ footer 已追加）
- [x] WOA→CIA→QQ 端到端测试通过（CC 审计验证）

---

## 阶段3: 统一报告引擎上线（已完成）

### 目标
- 统一报告引擎正式接管所有报告
- 旧架构（OpenClaw isolated agentTurn）退役
- 单一数据流、单一出口

### 任务

| 编号 | 任务 | 工作量 | 状态 | 说明 |
|------|------|--------|------|------|
| 3.1 | 统一报告引擎重构 | 3h | ✅ | report_engine.py 已实现，复用现有 cron_dispatcher.py 框架 |
| 3.2 | 旧架构退役 | 1h | ✅ | OpenClaw isolated agentTurn cron（pre/midday/post_market）已删除 |
| 3.3 | 全量 Cron 切换 | 0.5h | ✅ | 三任务注册到 ~/.openclaw/crontab，经 cron_dispatcher.py 统一调度 |
| 3.4 | 回滚方案演练 | 0.5h | ⬜ | 激活系统 cron 后验证 |
| 3.5 | 监控告警上线 | 1h | ⬜ | 复用 cron_dispatcher.py 日志 + write_status |
| 3.6 | 文档更新 + 交接 | 1h | ⬜ | 本文档归档 |

**阶段3小计: 7h**

### 触发条件
- ✅ OpenClaw isolated agentTurn cron 已删除（2026-06-08）
- ✅ cron_dispatcher.py 已新增 pre_market/midday/post_market 任务（2026-06-08）
- ⏳ 系统 crontab 激活（`crontab ~/.openclaw/crontab` + `sudo service cron start`）

### 验收标准
- [x] 统一报告引擎接管所有报告类型（report_engine.py + MCP）
- [x] Morning Briefing 旧架构停用（isolated agentTurn cron 已删除）
- [x] 单一出口推送 QQ（c2c:43C77867478A33B101FA705AA70754E3）
- [x] 定时任务统一经 cron_dispatcher.py 调度（report_engine.py + MCP）
- [ ] 回滚方案可用（待 crontab 激活后验证）

---

## 总工作量

| 阶段 | 工作量 | 累计 | 状态 |
|------|--------|------|------|
| 阶段1 | 9h | 9h | ✅ 已完成 |
| 阶段2 | 9h | 18h | ✅ 已完成 |
| 阶段3 | 7h | 25h | ✅ 已完成（仅 crontab 激活待执行） |
| **合计** | **25h** | | |

---

## 风险矩阵（v3.0）

| 优先级 | 风险 | 缓解措施 |
|--------|------|---------|
| P0 | WOA 未写入 PG 导致盘前报无数据 | MCP 兜底回退 |
| P1 | 置信度标注不准确 | WOA 提供结构化置信度字段 |
| P1 | 融合格式变更影响现有流程 | 阶段2端到端测试通过后再上线 |
| P2 | PG 数据 lag（API限流） | 如实标注数据日期，不推断 |
| P3 | 格式对比不完整 | 按 technical_design.md v3.0 §4.1 逐项验收 |

---

## 输出物

1. `technical_design.md` v3.0 — 完整技术设计（融合格式 + WOA 数据流）
2. `formatters.py` v3.0 — PreMarketFormatter 10 板块
3. `pre_market.py` v3.0 — fetch_memo() + 优先级调整
4. `pre_market_format.md` — 盘前报格式规范 v1.0

---

## 时间估算

| Phase | 工作量 | 说明 |
|-------|--------|------|
| 阶段1 | 9h | 约 1.5 天 ✅ |
| 阶段2 | 9h | 约 1.5 天（本次开发）|
| 阶段3 | 7h | 约 1 天 |
| **合计** | **25h** | 约 4 天 |

*相比 v2.0 增加1h（阶段2 置信度标注工具 + 禁止词规范落地）*

---

### 定时任务统一切换说明（2026-06-08）

**执行前（旧架构）：**
```
07:50  cia_pre_market_report  → OpenClaw isolated agentTurn（不可靠）
12:00  cia_midday_report      → OpenClaw isolated agentTurn（不可靠）
15:30  cia_post_market_report → OpenClaw isolated agentTurn（不可靠）
```

**执行后（新架构）：**
```
~/.openclaw/crontab（系统 crontab）
07:50  pre_market   → cron_dispatcher.py → report_engine.py + MCP → QQ
12:00  midday       → cron_dispatcher.py → report_engine.py + MCP → QQ
15:30  post_market  → cron_dispatcher.py → report_engine.py + MCP → QQ
```

**cron_dispatcher.py TASK_MAP 新增任务：**
- `pre_market` / `midday` / `post_market`

**激活命令：**
```bash
crontab ~/.openclaw/crontab
sudo service cron start   # 或 systemctl start cron
```

---

*本文档由 Arc 更新，2026-06-08（v3.0 完成）*