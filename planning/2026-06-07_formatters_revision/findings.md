# findings.md — formatters.py 修订方案细节

**创建日期:** 2026-06-07
**更新日期:** 2026-06-07

---

## F-01: 盘前报新增「策略五大方向信号」板块

**当前代码:** 无此板块

**修复要求:**
- 在 `PreMarketFormatter._format_sectors()` 之后新增 `_format_strategy_signals()` 方法
- 板块标题: `策略方向跟踪`
- 数据结构: `data.strategy_signals` → `{phys_ai: {...}, optical: {...}, pcb: {...}, cpo: {...}, etf_broad: {...}}`
- 每个方向输出: 信号强度 + 昨日表现
- 信号强度定义: 强/中/弱/无

**CIA模板参考:**
```
■ 物理AI     信号：【强/中/弱/无】昨日表现：[描述]
■ 光模块     信号：【强/中/弱/无】 昨日表现：[描述]
■ PCB 信号：【强/中/弱/无】  昨日表现：[描述]
■ CPO        信号：【强/中/弱/无】  昨日表现：[描述]
■ 宽基ETF    信号：【强/中/弱/无】  昨日表现：[描述]
```

---

## F-02: 盘前报新增「ETF溢价率」专项板块

**当前代码:** 无此板块

**修复要求:**
- 新增 `_format_etf_premarket()` 方法
- 板块标题: `ETF盘前信号（溢价率）`
- 数据结构: `data.etf_premarket` → `{broad: {...}, industry: {...}, qdii: {...}}`
- 格式: `[name(code)](url) 溢价率 +[X]%`

**CIA 模板参考:**
```
■ ETF盘前信号（溢价率）
━━━━━━━━━━━━━━━━━
【宽基 ETF】沪深300 ETF 昨溢价率 [X]% → 今日注意
【行业 ETF】溢价率异动：[name(code)](url) [X]%
【QDII ETF】  溢价率异动：[name(code)](url) [X]%
```

---

## F-03: 盘中追踪新增「策略方向实时信号」板块

**当前代码:** `MiddayFormatter` 缺少策略方向信号

**修复要求:**
- 在 `MiddayFormatter` 新增 `_format_strategy_realtime()` 方法
- 板块标题: `策略方向实时信号`
- 数据结构: `data.strategy_realtime` → 同 F-01
- 每方向额外显示: 龙头股票名称/代码/涨跌幅

---

## F-04: 盘中追踪新增「ETF盘中溢价率监控」板块

**当前代码:** `MiddayFormatter` 缺少 ETF 溢价率监控

**修复要求:**
- 新增 `_format_etf_intraday()` 方法
- 板块标题: `ETF盘中溢价率监控`
- 告警格式: `⚠️ [name(code)](url) 溢价率 +[X]% [超过阈值描述]`

---

## F-05: 盘后复盘新增「策略方向复盘」板块

**当前代码:** `PostMarketFormatter` 只有 `今日概况/最强主线/涨跌停分析/资金流/明日展望`

**修复要求:**
- 新增 `_format_strategy_review()` 方法
- 板块标题: `策略方向复盘（五大方向）`
- 数据结构: `data.strategy_review` → 五大方向各自含:今日信号/板块表现/核心数据/明日信号预判
- 每个方向分四行输出

---

## F-06: 盘后复盘新增「ETF套利信号」专项板块

**当前代码:** `PostMarketFormatter._format_capital_flow()` 包含资金流，无 ETF 套利

**修复要求:**
- 新增 `_format_etf_arbitrage()` 方法
- 板块标题: `ETF 套利信号复盘`
- 数据结构: `data.etf_arbitrage` → `{broad: [...], industry: [...], qdii: [...]}`
- 输出: 溢价卖出信号 + 折价买入信号（带⚠️ 标记）

---

## F-07: 盘前报新增「集合竞价」数据接口

**当前代码:** 无此接口

**修复要求:**
- 新增 `_format_auction()` 方法
- 板块标题: `盘前异动（集合竞价）`
- 子板块: 【最强竞价】【弱转强候选】【需观察】
- 数据结构: `data.auction` → `{strongest: [...], weak_to_strong: [...], observe: [...]}`

---

## F-08: 盘前报新增「宏观事件」数据接口

**当前代码:** 无此接口

**修复要求:**
- 新增 `_format_macro_events()` 方法
- 板块标题: `宏观/事件面（今日）`
- 数据结构: `data.macro_events` → `[{event, description, time, impact_direction}]`
- 格式: `[重要数据/事件]：[描述] [时间] → 注意影响板块：[方向]`

---

## F-09: 盘后复盘新增「断板与高标杀」板块

**当前代码:** `PostMarketFormatter` 无此板块

**修复要求:**
- 新增 `_format_board_break()` 方法
- 板块标题: `断板与高标杀`
- 子板块: 【断板】【高标杀】
- 数据结构: `data.board_break` → `{broken: [...], high_board_broken: [...]}`
- 高标杀带⚠️ 标记

---

## 共用约束

1. **不改变函数签名** — `render(data)` 入参结构保持兼容（只新增可选字段）
2. **不修改其他 Formatter 类** — 各自独立修改
3. **保持 `split_messages()` 逻辑** — 消息拆分不变
4. **MAX_MSG_LENGTH = 4000** — 保持不变
5. **板块标题格式** — 使用 `■板块名` 或 `【板块名】`，与 CIA 模板对齐
6. **每修复一个板块后** — `python3 -m py_compile` 验证语法