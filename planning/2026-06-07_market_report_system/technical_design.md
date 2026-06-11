# 综合市场汇报机制设计 v3.0

**创建日期:** 2026-06-07
**更新日期:** 2026-06-08
**版本:** 3.0
**状态:** 方案已确认，待开发

---

## 一、背景与目标（v3.0）

### 演进路径

| 版本 | 架构 | 问题 |
|------|------|------|
| v1.0 | 两套独立系统各跑各的 | 用户收到两份报告，重复 |
| v2.0 | 统一报告引擎（双轨数据融合） | Morning Briefing 格式未固化 |
| **v3.0** | **WOA→PG→CIA单一数据流 + 融合格式** | **解决重复、提升结构化程度** |

### v3.0 核心变化

1. **数据流统一**：WOA 写 PG → CIA 读 PG → 输出单一报告
2. **格式融合**：Morning Briefing 6板块 + 旧版 8板块优势 → 10板块统一格式
3. **置信度标注**：所有数据字段带中文置信度（高/中/低）
4. **WOA 摘要头部**：每份报告带 WOA 工作状态表格

---

## 二、系统架构（v3.0）

### 2.1 核心数据流

```
┌─────────────────────────────────────────────────────────────┐
│ WOA 执行 │
│  ├─ 写 PG investment_memos（company_id=5233，5条 memo）     │
│  │    morning_collect / factor_calculation /               │
│  │    etf_alpha_signal / risk_monitoring / daily_report     │
│  ├─ 写 Redis cia_task_queue（带 prompt + woa_summary） │
│  └─ 发 QQ 消息给 CIA： │
│       「✅ Morning Briefing 完成 msg_id=xxx 请生成盘前洞察」 │
└─────────────────────────┬───────────────────────────────────┘
                          │ QQ 消息
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    CIA 接收处理 │
│  ├─ 解析 msg_id                                            │
│  ├─ 从 cia_task_queue 读 prompt                             │
│  ├─ 从 PG investment_memos 读今日数据（company_id=5233）     │
│  ├─ 按统一格式生成盘前报                                    │
│  ├─ 发 QQ 给用户 │
│  └─ XACK cia_task_queue                                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 报告生成引擎架构

```
                    ┌─────────────────────┐
                    │     QQ 用户 │
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
┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐
│ Morning Brief │  │   盘前报模块    │  │   盘后报模块    │
│ 适配层(PG)       │  │ (wudao_aStock) │  │ (wudao_aStock) │
│ ←核心数据源 │  │ ← 兜底数据源   │  │ ← 兜底数据源   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
         │                     │                     │
        └─────────────────────┼─────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   AI 增强层          │
                    │ (数据融合/仲裁)      │
                    └─────────────────────┘
```

### 2.3 数据源优先级

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| **主数据源** | PG investment_memos（WOA 写入） | 结构化程度高，格式统一 |
| **兜底数据源** | MCP 工具（wudao_aStock） | 主数据源缺失时回退 |
| **历史缓存** | DB 缓存表 | 全部不可用时降级 |

---

## 三、汇报体系（v3.0 统一模板）

### 3.1 盘前报格式（10 板块）

```
📊 盘前报 {date}
==================

【WOA 工作摘要】
（任务表格：任务 | 状态 | 置信度）
综合置信度：X | 风险：X | 建议关注：X

■ 今日市场概况
沪深300点位 + 涨跌幅 + 情绪 + 来源标注

■ 今日主线预判（≤2条）

■ 因子信号（5类因子表格）
因子 | 信号 | 置信度 | 数据状态

■ ETF 信号（Top5表格）
ETF名称 | 信号 | 综合评分 | 置信度

■ 盘前异动（集合竞价）
最强竞价3只 + 弱转强候选

■ 宏观/事件面（今日重要数据/事件）

■ 风险提示
风险等级 + 波动率 + VIX + 地缘风险星级

■ 情景假设
中性 / 悲观 / 乐观 三行

■ 今日操作参考
ETF溢价率阈值 + 观察方向

■ 今日关注（优先级列表）
· 明日关注点

⚠️ 只输出分析结论，不提供投资建议
```

### 3.2 午盘报格式

```
📊 午盘复盘 {date} 11:30

【上午走势】
指数表现（上证/深成/创业板）+ 涨跌家数

【板块异动】
涨幅前列板块 + 资金流入板块

【强势股跟踪】
持仓股/自选股表现 + 异动告警

【风险提示】
炸板股名单 + 高位股风险
```

### 3.3 盘后报格式（10 板块）

```
📊 盘后复盘 {date}

■ 今日市场概况
指数收盘点位 + 涨跌停统计 + 成交额 + 情绪 → 明日预期

■ 涨跌停统计
涨停家数 / 封板率 / 炸板率 / 跌停 / 续板 / 首板

■ 今日主线复盘（≤2条）
板块 + 今日表现 + 龙头 + 信号强度 + 明日预判

■ 涨停梯队
3连板+高标 / 2连板 / 首板

■ 断板与高标杀
昨涨停今断板 / {streak}连板断板 → 情绪退潮信号

■ 策略方向复盘（五大方向）
物理AI / 光模块 / PCB / CPO / 宽基ETF — 今日信号 + 明日预判

■ ETF套利信号复盘
溢价率异动统计 + 具体套利信号（溢价卖出/折价买入）

■ 风险信号复盘
跌停池 + 高标杀 + 炸板率 >20% + ST/退市异动

■ 今日操作参考（仅供观察，不构成建议）
主线方向 + 切换风险 + ETF阈值 + 断板高标

■ 今日小结
AI 生成的自然语言总结
```

---

## 四、格式融合对比（v3.0 核心）

### 4.1 融合前后对比

| 维度 | Format A（旧版 formatters.py） | Format B（pre_market_format.md） | 融合结果 |
|------|-------------------------------|--------------------------------|---------|
| 板块数 | 8个 | 6个 | **10个** |
| WOA摘要 | ❌ 无 | ✅ 任务表格+置信度 | **✅ 取B** |
| 市场概况 | 今日预判（大盘+情绪） | 今日市场概况 | **✅ 取B** |
| 因子信号 | ❌ 无（分散） | ✅ 5类因子表格 | **✅ 取B** |
| ETF信号 | ETF溢价率 | Top5综合评分 | **✅ 取B** |
| 盘前异动 | ✅ 集合竞价 |❌ 无 | **✅ 取A** |
| 宏观/事件面 | ✅ 有 | ❌ 无 | **✅ 取A** |
| 风险提示 | 分散各处 | ✅ 等级+VIX+地缘 | **✅ 取B** |
| 情景假设 | ❌ 无 | ✅ 中性/悲观/乐观 | **✅ 取B** |
| 操作参考 | ✅ 七条ETF阈值 | 分散各处 | **✅ 取A** |
| 今日关注 | 明日关注点 | 优先级列表 | **✅ 取B** |
| 禁止词 | 无 | ✅ 禁止词清单 | **✅ 取B** |

### 4.2 置信度标注规范

| 英文 | 中文 | 适用场景 |
|------|------|---------|
| HIGH | 高 | 数据完整、来源权威 |
| MEDIUM | 中 | 数据基本完整、有轻微缺失 |
| LOW | 低 | 数据缺失较多或来源不权威 |

### 4.3 来源标注格式

```
【来源：表名.字段名，数据日期】
例：【来源：investment_memos，数据2026-06-08】
```

---

## 五、核心模块（v3.0）

| 模块 | 路径 | 职责 |状态 |
|------|------|------|------|
| `formatters.py` | `src/reports/` | PreMarketFormatter 重写为10板块 | **待修改** |
| `pre_market.py` | `src/reports/modules/` | 新增 fetch_memo() 从 PG 读数据 | **待修改** |
| `woa_notify.py` | `scripts/` | WOA→CIA通知脚本 | 生效中 |
| `cron_morning_briefing.py` | `scripts/` | 旧版 Morning Briefing cron | 待废弃 |

### 5.1 PreMarketFormatter 修改清单

**render() 调用顺序（11个 add_section）：**

```python
self.add_section("WOA 工作摘要",        _format_woa_summary(woa))           # 1
self.add_section("今日市场概况",         _format_market_overview(overview))   # 2
self.add_section("今日主线预判（≤2条）", _format_main_lines(main_lines))     # 3
self.add_section("因子信号",             _format_factors(factors))           # 4
self.add_section("ETF 信号",             _format_etf_signals(etf_signals))   # 5
self.add_section("盘前异动（集合竞价）",  _format_auction(auction))           # 6
self.add_section("宏观/事件面（今日）",  _format_macro_events(macro_events)) # 7
self.add_section("风险提示",             _format_risks(risks))               # 8
self.add_section("情景假设",             _format_scenarios(scenarios))       # 9
self.add_section("今日关注",            _format_today_attention(attention))  # 10
self.add_section("今日操作参考",         _format_operation_ref(op_ref))      # 11
```

**新增方法（v3.0）：**

| 方法 | 功能 |
|------|------|
| `_format_woa_summary()` | WOA任务状态表格 + 综合置信度 + 风险 + 建议 |
| `_format_market_overview()` | 沪深300点位 + 涨跌幅 + 情绪 + 来源标注 |
| `_format_factors()` | 5类因子表格（动量/价值/质量/资金流/技术面） |
| `_format_etf_signals()` | Top5 ETF表格（名称/信号/综合评分/置信度） |
| `_format_risks()` | 风险等级 + 波动率 + VIX + 地缘风险星级 |
| `_format_scenarios()` | 中性/悲观/乐观三行概率条件预期 |
| `_format_today_attention()` | 今日关注列表（优先级1-4条，来源标注） |
| `_cn_conf()` | 置信度翻译（HIGH→高 / MEDIUM→中 / LOW→低） |
| `_source_tag()` | 来源标注统一格式化 `【来源：表.字段，日期】` |

**保留方法（Format A 优势）：**

| 方法 | 说明 |
|------|------|
| `_format_auction()` | 盘前异动（集合竞价） |
| `_format_macro_events()` | 宏观/事件面 |
| `_format_main_lines()` | 今日主线预判（≤2条，保留原逻辑） |
| `_format_operation_ref()` | 今日操作参考（ETF阈值 + WOA推导） |

**pre_market.py fetch_memo() → fetch() 数据流：**

`fetch_memo()` 从 PG `investment_memos` 读取5种memo，通过 `fetch()` 的 memo_data 合并到返回值：
- `woa_summary` → WOA任务表格（第1板块）
- `market_overview` → 沪深300+情绪（第2板块）
- `factors` → 因子信号（第4板块）
- `etf_signals` → ETF Top5（第5板块）
- `risks` → 风险提示（第8板块）
- `scenarios` → 情景假设（第9板块）
- `_build_operation_ref()` → 操作参考（从woa_summary+scenarios推导，第11板块）
- `_build_today_attention()` → 今日关注（第10板块）

### 5.2 pre_market.py fetch_memo() 方法

```python
def fetch_memo(self, trade_date: str) -> Dict[str, Any]:
    """从 PG investment_memos 读取 WOA 生成的结构化数据
    
    Args:
        trade_date: 交易日期（YYYY-MM-DD）
    
    Returns:
        {
            "woa_summary": {...},
            "market_overview": {...},
            "factors": [...],
            "etf_signals": [...],
            "risks": {...},
            "scenarios": [...],
        }
    """
```

---

## 六、数据融合规则（v3.0）

### 6.1 数据源优先级

| 优先级 | 数据源 | 适用场景 |
|--------|--------|---------|
| 主数据源 | PG investment_memos（WOA 写入） | 盘前报 |
| 兜底数据源 | MCP 工具 + 旧版DB | 盘前报回退、午盘/盘后报 |
| 缓存 | DB 缓存表 | 全部不可用时降级 |

### 6.2 冲突仲裁规则

| 场景 | 仲裁规则 |
|------|---------|
| 数值冲突（如涨停家数） | MCP 实时数据优先 |
| 情绪判断冲突 | WOA AI 总结优先 |
| 数据缺失 | 降级使用缓存 + 标注"数据暂不可用" |
| 全部数据不可用 | 返回告警报告 + 跳过该模块 |

---

## 七、触发流程（v3.0）

### 7.1 盘前报触发

```
WOA 执行（每日 07:50）
  ├─ 写 PG investment_memos（5条 memo）
  ├─ 写 cia_task_queue（带 prompt + woa_summary）
  └─ 发 QQ 消息给 CIA：
       「✅ Morning Briefing 完成 msg_id={cia_msg_id} 请生成盘前洞察」

CIA 收到消息
  ├─ 解析 msg_id
  ├─ 从 cia_task_queue 读 prompt
  ├─ 从 PG investment_memos 读今日数据
  ├─ 按10板块统一格式生成盘前报
  ├─ 发 QQ 给用户
  └─ XACK cia_task_queue
```

### 7.2 午盘/盘后报触发（兜底）

```
Cron 触发（午盘 11:30 / 盘后 15:30）
  ├─ 直接走 MCP 工具获取实时数据
  ├─ 按统一格式渲染
  └─ 发 QQ 给用户
```

---

## 八、Cron 任务（v3.0）

```bash
# 盘前报 - WOA 执行（WOA cron → PG+QQ → CIA 处理）
# 无需 CIA cron，盘前报由 WOA 触发

# 午盘报 - 每个交易日上午 11:30
30 11 * * 1-5 cd /home/claw/invest-infra && \
  .venv/bin/python scripts/report_engine.py --type midday

# 盘后报 - 每个交易日下午 15:30
30 15 * * 1-5 cd /home/claw/invest-infra && \
  .venv/bin/python scripts/report_engine.py --type post_market

# 盘中轮询 - 每个交易日 10:00-14:00 每小时一次
0 10,11,12,13,14 * * 1-5 cd /home/claw/invest-infra && \
  .venv/bin/python scripts/report_engine.py --type intraday_alert
```

---

## 九、禁止词规范（v3.0 新增）

| 禁止词 | 替代词 |
|--------|--------|
| 买 / 卖 / 持有 / 做多 / 做空 / 推荐 / 建议买入 / 建议卖出 | 监控 / 关注 / 复核 / 进一步分析 |

---

## 十、扩展方向

1. **AI 增强层扩展** — 引入 LLM 生成自然语言总结
2. **自定义汇报** — 用户订阅特定板块/自选股的定向汇报
3. **对比分析** — 与历史同期对比（同比/环比）
4. **预警推送** — 价格达到目标位/止损位时主动推送
5. **多渠道分发** — 支持微信/钉钉/Telegram 等

---

## 十一、风险与约束

1. **MCP 工具频率限制** — 批量调用需控频，建议间隔 100ms
2. **A股交易时间** — 非交易时间（周末/节假日）不推送
3. **数据延迟** — 盘中数据可能有 15 分钟延迟
4. **长文本限制** — QQ 消息有长度限制，需拆分或压缩
5. **数据融合冲突** — 需明确的仲裁规则（见 6.2 节）

---

*本文档由 Arc 更新，2026-06-08（v3.0）*