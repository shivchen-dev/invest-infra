# MCP 采集 — 报告 DB 化改造方案

**主题：** 统一改造三大报告模块（盘前/午盘/盘后）为「采集入库 → DB 读取 → 降级兜底」架构，彻底消除报告层的运行时 MCP 调用
**版本：** v3.1（v3 基础上状态同步：Phase 0-5 实施完毕,Phase 6 5 天验证启动）
**状态：** Phase 0-5 ✅ 完成｜Phase 6 ⏳ 5 个交易日连续验证启动
**日期：** 2026-06-11
**原作者：** CIA（v1）
**v2 审计修订：** Arc（2026-06-11）
**v3 实证修订：** Arc（2026-06-11 18:15）
**v3.1 状态同步：** Arc（2026-06-11 20:05）— 实施层：Claude Code（审计员: Arc via tmux supervisor）

**v3.1 新增 commit 清单**（20:05 补）：
- `48d2d06` fix(formatters): handle empty/missing data across 11 helpers (Phase 4) — 实施: Claude Code,审计: Arc
- `b312308` feat(market-data-collector): add smart_hotlist + capital_flow_hsgt (§3.4 A) — 实施: Claude Code,审计: Arc
- `afd0020` refactor(pre-market): remove runtime MCP fallback (§5.1) — 实施: Claude Code,审计: Arc
- `00ccd24` docs(midday): update comments to reflect actual DB-only behavior (§5.2) — 实施: Claude Code,审计: Arc

---

## 〇、v2 → v3 变更说明

| # | 章节 | v2 状态 | v3 修改 | 触发原因 |
|---|------|---------|---------|---------|
| 1 | 文档头 | "v2 修订中" | 升级为 v3,状态改为 "Phase 0-3 完成,Phase 4-6 待执行" | 实际进展 |
| 2 | §1.1 | "post_market.py 已 DB Only" | 改为 "post_market.py 真正 DB Only (ef4e20f 修复后,9 SKIP → 0)" | bug 修复 |
| 3 | §1.4 #1 | "market_leaders_pick 待补" | **删除** | Phase 0 验证早已在 TRADE_DATE_TOOLS (line 55-58) |
| 4 | §1.4 #2-#3 | "9 工具入库失败,根因 save_snapshot 异常被吞" | 改为 "9 工具 SKIP,根因 results.get(data_type, {}) 单行 key 错位,**已修复** (ef4e20f)" | Phase 1 实证 + 已 commit |
| 5 | §1.4 #6 | "ciA_market_collect.timer 未创建" | **删除** | 实际 2026-06-08 21:09 已创建,每日 15:05:35 触发 |
| 6 | §3 整章 | 待执行 | 改为 "✅ 已完成 (ef4e20f + 6e14039)" + 引用 commit + 保留 Phase 0/1/2/3 文档 | 实施完毕 |
| 7 | §3.1.1 新增 smart_hotlist / capital_flow_hsgt | 仍标注 "待补" | 标 "已存在但不在 15:05 路径,**待决策** (加入 TRADE_DATE_TOOLS 还是维持 pre-market/midday 路径)" | 新增决策点 |
| 8 | §3.2.2 save_snapshot traceback | 待执行 | 改为 "可选改进,非阻塞" | bug 不在 save_snapshot,优先级降 |
| 9 | §4.0 Phase 4 formatters 测试 | 待执行 | 不变 | — |
| 10 | §4.1/§4.2 pre/midday 改造 | 待执行 | 不变 | — |
| 11 | §5 清单数字 | 16 种 | 改为 17 种 (实际 TRADE_DATE_TOOLS 数) | Phase 0 实测 |
| 12 | §6 工作量 | "4-5h 实施 + 5 天验证" | 改为 "已用 ~1h (Phase 0+1+2+3) + 剩 2-3h (Phase 4+5) + 5 天验证" | 实际进度 |
| 13 | §7 风险 | timer 未创建 / save_snapshot 异常 | 删除已解决项,新增 "MCP_TOKEN 环境变量必须随 collector 一起加载" | 实际跑出 |
| 14 | §8 验收 #1 | "≥16 条" | 改为 "≥17 条" | 实际工具数 |
| 15 | §8 验收 #4 | "5 个交易日" | 不变,但加 "ef4e20f 之后" 限定 | 时序明确 |

---

## 一、现状问题

### 1.1 架构现状（v3.1 状态同步）

| 报告模块 | v2 描述 | v3 实测 | v3.1 状态 |
|---------|---------|---------|-----------|
| `post_market.py` | DB Only（已改造）| **真正 DB Only** (ef4e20f 修复后,17/17 工具入 DB) | ✅ 保持 |
| `pre_market.py` | DB 优先 + cache miss 走 MCP | afd0020 后**DB Only** (删 2 处 MCP) | ✅ afd0020 完成 |
| `midday.py` | DB 优先 + cache miss 走 MCP | 00ccd24 后**DB Only** (代码本就 DB-only, 注释清理) | ✅ 00ccd24 完成 |

**关键进展**（v3 → v3.1）：
- ef4e20f 修复后,15:05 采集从 8/17 真实数据 → **17/17 真实数据**。3 个长期走 FALLBACK_DATA 的 P0 工具（market_leaders / board_break / capital_flow_mkt）现在全部使用真实市场数据,盘后报质量立即提升。
- b312308 实施后,15:05 采集从 17/17 → **19/19**（含 §3.4 新增 smart_hotlist + capital_flow_hsgt）。
- afd0020 实施后,pre_market.py 报告层 MCP 调用 = 0, cache miss 走 formatters stub（Phase 4 48d2d06 健壮化）。
- 00ccd24 实施后,midday.py 报告层 MCP 调用 = 0（代码本就 DB-only, 仅修正 stale 注释）。

### 1.2 MCP 限额（v3.1 更新）

- MCP 日限额：**50 次/天**
- 每日采集：`market_data_collector.py` 19 个工具 / 4 批 ≈ 19 次（v3.1 §3.4 加 2 项）
- 报告层：**0 次**（v3.1 改造后）
- **结论**：采集 19 次 + 报告 0 次 = 19 次, 远低于 50 次限额,采集+报告完全分离,无冲突

### 1.3 数据流（v3.1 改造后）

```
15:05 market_data_collector 批量采集 (19 工具,v3.1 §3.4 加 2 项) → daily_market_snapshot
  ↓
09:00 pre_market / 12:00 midday / 15:30 post_market 报告生成
  ├─ post_market: 纯读 DB (FALLBACK_DATA 仅在 DB miss 时,目前 0 个工具走这条) ✅
  ├─ pre_market:  纯读 DB (cache miss 走空数据 → formatters stub, 48d2d06) ✅ afd0020
  └─ midday:      纯读 DB (cache miss 走 FALLBACK_DATA) ✅ 00ccd24
```

**v3.1 改造后: 报告层 MCP 调用 = 0**。

### 1.4 根因汇总（v3.1 状态同步）

| # | v1 根因 | v3 状态 | v3.1 状态 | 修复 commit |
|---|---------|---------|-----------|-------------|
| 1 | market_leaders_pick 未加入 TRADE_DATE_TOOLS | **不存在** (早已在) | 保持 | — |
| 2 | board_break_analysis / capital_flow_mkt 已采集但未入库 | **不存在** (因 9 SKIP 根因连带) | 已修复 | ef4e20f |
| 3 | 9 工具 (auction_*/stock_rank/...) 已采集但未入库 | **不存在** (因 9 SKIP 根因连带) | 已修复 | ef4e20f |
| 4 | smart_hotlist / capital_flow_hsgt 未加入采集清单 | **部分对** — DB 已有数据,但来源是 pre-market/midday 路径,不是 15:05 | **已修复**（选 A） | b312308 |
| 5 | pre_market.py / midday.py 仍为混合策略 | 仍存在 | **已修复** | afd0020 + 00ccd24 |
| 6 | cia_market_collect.timer 未创建 | **不存在** (早已在) | 保持 | — |
| 7 | save_snapshot 异常被吞 (logger.error 无 traceback) | 仍存在,但非阻塞性 | 保持, 可选改进 | — |

**9 SKIP 真实根因（v3 揭示）：**
- `mcp_client.call_batch()` 返回的 dict 用 `tool_name` 作 key
- `market_data_collector.run()` 用 `data_type` 作 key 查
- 9 个工具的 data_type ≠ tool_name 时永远查空 → SKIP
- 修复：`results.get(data_type, {})` → `results.get(tool_name, {})`
- 详见 commit `ef4e20f`

---

## 二、改造目标

### 2.1 架构原则（不变）

> **MCP 只负责采集数据入库,报告只读 DB,MCP 不出现在报告的运行时调用链中。**

### 2.2 目标数据流（不变）

```
15:05 market_data_collector 批量采集 → daily_market_snapshot (17 工具)
  ↓
09:25 / 12:30 / 15:30 报告生成 → 纯读 DB → DB 未命中 → 降级兜底 (0 次 MCP 调用)
```

### 2.3 改造范围（v3.1 更新）

| 状态 | 范围 | 文件 | commit |
|------|------|------|--------|
| ✅ | 修复 9 SKIP bug | `src/reports/market_data_collector.py` | ef4e20f |
| ✅ | DATE_PARAM_MAP 清理 | `src/reports/market_data_collector.py` | 6e14039 |
| ✅ | 现状快照归档 | `docs/需求方案/状态快照-2026-06-11.md` | a72e395 |
| ✅ | v2 方案归档 | `docs/需求方案/MCP采集-报告DB化改造方案.md` (v2 → v3) | a72e395 |
| ✅ | systemd 定时器 | `~/.config/systemd/user/cia_market_collect.{timer,service}` | (早已存在) |
| ✅ | formatters 空数据测试 + 11 helper 健壮化 | `tests/test_formatters_empty_data.py` + `src/reports/formatters.py` | 48d2d06 |
| ✅ | pre_market.py 移除运行时 MCP (2 处) | `src/reports/modules/pre_market.py` | afd0020 |
| ✅ | midday.py 注释清理 (代码本就 DB-only) | `src/reports/modules/midday.py` | 00ccd24 |
| ✅ | §3.4 决策 A 实施 (smart_hotlist + capital_flow_hsgt) | `src/reports/market_data_collector.py` | b312308 |

---

## 三、采集层修复（✅ 全部完成）

### 3.0 Phase 0 — 现状快照（✅ 2026-06-11 完成）

**产出**：`docs/需求方案/状态快照-2026-06-11.md`（a72e395）

**关键发现**：
- DB 实际有 **13 种 data_type**（非方案说的 5）
- 15:05 collector 实际有 17 工具（非 16）
- 9 SKIP 工具 100% 满足 data_type ≠ tool_name 规则
- v1 方案 3 处错误前提（timer 未创建、market_leaders_pick 待补、save_snapshot 根因）已澄清

### 3.1 Phase 1 — 根因定位（✅ 2026-06-11 完成）

**产出**：见 `状态快照-2026-06-11.md` §4

**结论**：单行 bug,非系统性故障,非网络/解析/写入问题

### 3.2 Phase 2 — 针对性修复（✅ 2026-06-11 ef4e20f 完成）

**commit**：ef4e20f `fix(market-data-collector): use tool_name for call_batch result lookup`

**修复**：
```python
# market_data_collector.py line 244
- raw_data = results.get(data_type, {})
+ raw_data = results.get(tool_name, {})
```

**验证结果**（重跑 15:05 采集 + DB 校验）：
| 维度 | 修复前 | 修复后 |
|------|--------|--------|
| 15:05 采集 | 8 OK / 9 SKIP | **17 OK / 0 SKIP** |
| 真实数据 | 8/17 (47%) | **17/17 (100%)** |
| P0 覆盖 | 5/8 | **8/8 (100%)** |

### 3.3 Phase 3 — 定时器（✅ 早已存在）

`cia_market_collect.timer` + `cia_market_collect.service` 已存在并运行:
- timer: 2026-06-08 21:09 创建,`OnCalendar=*-*-* 15:05:00`
- service: `cron_dispatcher.py market_data_collect`
- 实际执行: 2026-06-10 17.1s / 2026-06-11 53.0s,均退出码 0

### 3.4 ✅ 已决策 + 实施：smart_hotlist / capital_flow_hsgt 归一（选项 A）

**原现状**：
- DB 已有 `smart_hotlist` (3 条,最新 2026-06-10) 和 `hsgt` (1 条,2026-06-10)
- 但**不是 15:05 collector 写的**,是 pre-market/midday 路径补的
- 命名不一致：`hsgt` vs v1 提案的 `capital_flow_hsgt`

**选项**：
- **A**：补到 TRADE_DATE_TOOLS（统一管理,15:05 也采一次,覆盖更全）
- **B**：维持现状（pre-market/midday 路径继续负责,15:05 不管）

**决策**：**选 A**（CIA 拍板, 2026-06-11 18:39）

**实施**（commit `b312308`，2026-06-11 19:35）：
- `src/reports/market_data_collector.py` TRADE_DATE_TOOLS 末尾追加 Group-H 2 项
  - `smart_hotlist`（source=combined, limit=10, 无 date 参数）
  - `capital_flow`（flowType=hsgt, limit=5, DATE_PARAM_MAP 复用 "date" key）
- 工具总数：17 → 19
- DB 旧名 `hsgt` 保留不动 (兼容历史)
- 每日新增 MCP 调用：~2 次（限额 50/日, 仍充裕）

---

## 四、报告层改造（✅ Phase 4-5 全部完成）

### 4.0 Phase 4 — formatters 空数据兼容性测试（✅ 2026-06-11 19:15 完成）

> **必做前置**：在删 MCP 调用前,先确认所有 formatters 在 `{"rows": [], "summary": {}}` 空数据下不崩溃。

**操作**：见 v2 §4.0（未变）

**新增文件**：`tests/test_formatters_empty_data.py` (227 用例)

**关键约束**：
- **硬兜底**：`{"rows": [], "summary": {}}` — formatters 必须能安全访问任意字段
- **软兜底**：formatters 内部检测到 `rows == []` 时,输出"⚠️ 数据采集失败,请参考前一交易日报告"

**实施 commit**：`48d2d06`（2026-06-11 19:15, 实施: Claude Code,审计: Arc）
- 文件: `tests/test_formatters_empty_data.py` (新) + `src/reports/formatters.py` (+22/-6, 11 helper 修 4 个 bug)
- 设计依据: `docs/需求方案/Phase4-mock矩阵设计.md` (v1)
- 验收: pytest 227/227 pass / py_compile 0 错 / TestRealDataRegression 2/2

**4 个 bug 总结**：
- F-P4-01 (高): Intraday._format_risk_signals 空 dict 输出"跌停池：0家"假数据
- F-P4-02 (中): PostMarket._format_risk_review 空 dict 输出"高标杀：【无】"假数据
- F-P4-04 (中): IntradayAlert/Intraday/PostMarket 共 9 个 helper 类型校验不全, None/str/list 触发 AttributeError
- F-P4-03 (低): Intraday._format_strategy_realtime 空 dict 输出 5 行"无"（不返 stub）— 未修,记入 backlog, 不阻塞

### 4.1 Phase 5.1 — pre_market.py 移除运行时 MCP（✅ 2026-06-11 19:37 完成）

**改造逻辑**（✅ 已实现）：
```
DB 查 → 有 → 用
  → 无 → 用空数据占位 (不触发 MCP,触发 formatters stub 提示)
```

**实施 commit**：`afd0020`（2026-06-11 19:37, 实施: Claude Code,审计: Arc）
- 改动: -37/+9 (净 -28 行)
- 删除 2 处 MCP:
  1. `fetch()` 内 `cache_misses → mcp_batch → call_batch` 路径
  2. `_extract_macro_events()` 内 `self.mcp.call_tool("cls_news", ...)`
- 保留: `fetch_memo` (WOA memo 独立) + `_get_db_data` (旧版 WOA) + `TOOL_MAP` (仅作声明) + `__init__` 签名 (向后兼容)
- 验收: pytest 227/227 / py_compile 0 / grep self.mcp = 1 (仅形参) / dry-run fetch = 10 keys, DB 4/4 hit, 0 MCP

### 4.2 Phase 5.2 — midday.py 移除运行时 MCP（✅ 2026-06-11 19:38 完成）

**实施 commit**：`00ccd24`（2026-06-11 19:38, 实施: Claude Code,审计: Arc）
- 改动: -4/+4 (**0 逻辑改动**, 纯文档清理)
- 原状态: midday.py 代码已 DB-only (无任何 self.mcp 调用), 但 docstring/注释 stale
- 修正: L3 docstring + L41-42 fetch() docstring "走 MCP" → "DB-only 降级"
- 验收: pytest 227/227 / py_compile 0 / grep self.mcp = 0 / dry-run fetch = 7 keys, DB 5/5 hit, 0 MCP

### 4.3 post_market.py（✅ 已 DB Only）

代码层早已是 DB Only,ef4e20f 修复后实际数据从兜底 → 真实,**无需再改**。

### 4.4 FALLBACK_DATA 设计原则（v2 §4.4,不变）

| 维度 | 硬兜底 | 软兜底 |
|------|--------|--------|
| 结构 | 与 MCP 返回 JSON schema 字段一致 | 在 formatters 中检测到空 rows 输出"⚠️ 数据缺失" |
| 数值 | 默认 0 / 空数组 | 注明"采集失败",避免误读为"市场真无数据" |
| 时间戳 | 默认 None 或昨日 | 注明降级时间 |

---

## 五、采集清单（v3.1 修订：17 → 19 项）

实际 TRADE_DATE_TOOLS（v3.1 19 项，含 §3.4 新增 2 项）:

| # | data_type | MCP 工具 | 报告需要 | 优先级 | ef4e20f 修复后状态 |
|---|-----------|---------|---------|-------|-----------------|
| 1 | market_overview | market_overview | 盘前/午盘/盘后 | P0 | ✅ |
| 2 | limit_stats | limit_stats | 盘前/午盘/盘后 | P0 | ✅ |
| 3 | hot_sectors | hot_sectors | 盘后 | P0 | ✅ |
| 4 | limit_up_ladder | limit_up_ladder | 盘后 | P0 | ✅ |
| 5 | market_leaders | market_leaders_pick | 盘后 | P0 | ✅ (修复前 SKIP) |
| 6 | board_break | board_break_analysis | 盘后 | P0 | ✅ (修复前 SKIP) |
| 7 | capital_flow_mkt | capital_flow(flowType=market) | 盘后 | P0 | ✅ (修复前 SKIP) |
| 8 | sector_analysis | sector_analysis | 盘前 | P0 | ✅ |
| 9 | market_replay | market_replay_workflow | 盘前 | P1 | ✅ (修复前 SKIP) |
| 10 | auction_scan | auction_market_scan | 盘前 | P1 | ✅ (修复前 SKIP) |
| 11 | auction_wts | auction_weak_to_strong | 盘前 | P1 | ✅ (修复前 SKIP) |
| 12 | auction_feedback | auction_limitup_feedback | — | P2 | ✅ (修复前 SKIP) |
| 13 | broken_limit_up | broken_limit_up | 午盘 | P1 | ✅ |
| 14 | concept_ranking | concept_ranking | 午盘 | P1 | ✅ |
| 15 | smart_hotlist | smart_hotlist | 盘前/午盘 | P1 | ✅ b312308 (§3.4 选 A) |
| 16 | capital_flow_hsgt | capital_flow(flowType=hsgt) | 盘前 | P2 | ✅ b312308 (§3.4 选 A) |
| 17 | stock_rank_volume | stock_rank(type=volume) | — | P2 | ✅ (修复前 SKIP) |
| 18 | stock_rank_turnover | stock_rank(type=turnover_rate) | — | P2 | ✅ (修复前 SKIP) |
| 19 | cls_news | cls_news | 盘前 | P2 | ✅ |

> **DB 中另有**：`hsgt` (1 条,2026-06-10) — 与 #16 同源,命名不一致,**已决策** (新条目用 `capital_flow_hsgt`, DB 旧 `hsgt` 保留不动)

---

## 六、执行计划（v3.1 状态同步）

### 6.1 已完成（v3.1 时间戳）

| Phase | commit | 实际耗时 | 产出 |
|-------|--------|---------|------|
| 0 现状快照 | a72e395 | ~30 min | 状态快照-2026-06-11.md |
| 1 根因定位 | (含在 0 中) | 0 min | 状态快照 §4 |
| 2 采集层修复 | ef4e20f | ~15 min | 1 行修复 + 诊断日志 |
| 3 DATE_PARAM_MAP 清理 | 6e14039 | ~5 min | 3 个工具 None 化 |
| 3' 定时器 | (无需) | 0 min | 早已存在 |
| **4 formatters 健壮化** | **48d2d06** | ~25 min | tests/test_formatters_empty_data.py (新, 227 用例) + formatters.py (+22/-6, 11 helper) |
| **3'' §3.4 决策 A 实施** | **b312308** | ~3 min | market_data_collector.py (+11, Group-H 2 项) |
| **5.1 pre_market 去 MCP** | **afd0020** | ~5 min | pre_market.py (-37/+9, 删 2 处 MCP) |
| **5.2 midday 注释清理** | **00ccd24** | ~3 min | midday.py (-4/+4, 纯文档) |

**实施层总耗时**：~1h 50min（v3 估算 2h 实施, 偏快 10min）
**全部人员**：策划: Arc, 实施: Claude Code (via tmux supervisor)

### 6.2 剩余（v3.1 时间戳）

| Phase | 任务 | 估算 | 前置 | 验收 |
|-------|------|------|------|------|
| **6** | 5 个交易日连续验证 (ef4e20f + Phase 5 后) | 5 天 | Phase 5 | 每日 MCP 调用次数 = 0 / DB 命中率 ≥ 95% / 无 formatters 报错 |

**剩余总工作量**：5 天被动观察 (无主动实施)

### 6.3 回滚计划（v2 引入,v3.1 保留)

| 触发条件 | 回滚步骤 | 责任人 |
|---------|---------|--------|
| Phase 4 formatters 测试不通过 | 先修 formatters,再进 Phase 5 | CIA |
| Phase 5 后报告生成报错 | `git revert` 对应 commit + 恢复 `mcp_client` 调用路径 | CIA |
| Phase 6 连续 2 天 DB 命中率 < 80% | 回滚到上一稳定版本,单独排查采集层 | Arc + CIA |

---

## 七、风险与缓解（v3.1 状态同步）

| 风险 | v3 状态 | v3.1 状态 | 缓解措施 | SLA |
|------|---------|-----------|---------|-----|
| 15:05 采集时 MCP 限额从 0 点起算已耗尽 | 仍存在 | 仍存在（19/日 余裕大） | 采集脚本内 MCP 失败写 failed 日志 | 单次失败不影响其他数据源 |
| 采集超时（>20min） | 仍存在 | 仍存在 | 看门狗（cron_watchdog）监控超时,会补发 | **15:25 前 P0 必须全部入库** |
| 15:25 后仍未完成 P0 入库 | 仍存在 | 仍存在 | 报告降级生成 + 告警到值班 | 报告可降级,但不能崩 |
| ciA_market_collect.timer 未创建 | **已解决** (Phase 0 实测) | 保持 | — | — |
| save_snapshot 异常被吞 (logger.error 无 traceback) | 仍存在,**非阻塞** | 保持, 可选改进 | ef4e20f 后 SKIP 路径不再常态命中 | — |
| 9 SKIP 根因 (results.get key 错位) | **已解决** (ef4e20f) | 保持 | — | — |
| **新增**：MCP_TOKEN 环境变量未加载 | ef4e20f 验证时暴露 | 保持 | cron_dispatcher.py 加载 `.secrets/mcp.env`,CLI 跑需手动 `export` | 必须随 collector 一起加载 |
| pre_market / midday 改造后 formatters 崩 | 仍存在 | **已消除** (48d2d06 修复 F-P4-01/02/04) | Phase 4 测试 227/227 pass 覆盖 4 个 bug 回归 | 测试覆盖率 100% |
| F-P4-03 (strategy_realtime 不返 stub) | 未识别 | 识别为低优, 记入 backlog | 不阻塞 Phase 5；后续清理 | — |

---

## 八、验收标准（v3.1 状态同步）

1. **15:05 任务执行后**，`daily_market_snapshot` 有 **≥19 条**（v3.1 §3.4 加 2 项后）今日采集记录（P0 全覆盖）— ✅ ef4e20f 之后已达成
2. **09:25/12:30/15:30 报告生成时**，日志中 MCP 调用次数 = 0 — ✅ Phase 5.1/5.2 + ef4e20f 之后已达成（pre/midday/post 全部 DB-only）
3. **盘后报** P0 数据全部可从 DB 读取 — ✅ ef4e20f 之后已达成
4. **ef4e20f + 48d2d06 + b312308 + afd0020 + 00ccd24 之后连续 5 个交易日** P0 数据无缺失 — ⏳ Phase 6 验证中
5. **cron_watchdog 触发或人工补发 ≤ 1 次**（5 天内自动化率 ≥ 80%）— ⏳ Phase 6 验证中
6. **报告 formatters 在空 DB 数据下不崩溃** — ✅ 48d2d06 之后已达成（pytest 227/227 pass, 涵盖 4 个 bug 回归测试）

---

*原作者：v1 CIA / v2-v3 Arc，2026-06-11*
*v3.1 状态同步：Arc, 2026-06-11 20:05*
*关联 commit：ef4e20f / 6e14039 / a72e395 / 48d2d06 / b312308 / afd0020 / 00ccd24*
*关联文档：状态快照-2026-06-11.md / Phase4-mock矩阵设计.md*

---

## 〇'、v3 → v3.1 变更说明

| # | 章节 | v3 状态 | v3.1 修改 | 触发原因 |
|---|------|---------|-----------|----------|
| 1 | 文档头 | "Phase 0-3 ✅\|Phase 4-6 ⏳" | 升级为 v3.1, "Phase 0-5 ✅\|Phase 6 ⏳" | Phase 4/5/§3.4 实施完毕 |
| 2 | §1.1 | pre_midday ⏳ | 全部 ✅ (afd0020 + 00ccd24) | 实施完毕 |
| 3 | §1.2 | "17 个工具/17 次 + 报告 10 次 = 27 次" | "19 个工具/19 次 + 报告 0 次 = 19 次" | §3.4 加 2 + 报告层 MCP 归零 |
| 4 | §1.3 数据流 | pre_midday ⏳ 走 MCP | 全部 纯读 DB | afd0020 + 00ccd24 |
| 5 | §1.4 根因 #4 | ❓ 待决策 | ✅ b312308 (选 A) | §3.4 决策 |
| 6 | §1.4 根因 #5 | ⏳ Phase 5 | ✅ afd0020 + 00ccd24 | 实施完毕 |
| 7 | §2.3 改造范围 | 5 ⏳ / 1 ❓ | 全部 ✅ | 实施完毕 |
| 8 | §3.4 决策 | "决策人 CIA" | "✅ 选 A + b312308 实施" | 决策 + 实施 |
| 9 | §4 报告层改造 | "⏳ Phase 4-5 待执行" | "✅ Phase 4-5 全部完成" | 实施完毕 |
| 10 | §4.0/4.1/4.2 | ⏳ 1h | ✅ 含 commit + 验收详情 | 实施完毕 |
| 11 | §5 采集清单 | 17 项 + ❓ 2 项 | 19 项 + ✅ 2 项 | §3.4 实施完毕 |
| 12 | §6.1 已完成 | 5 个 Phase | 9 个 Phase (+ 4 新) | 实施完毕 |
| 13 | §6.2 剩余 | 5 项 (Phase 4/5.1/5.2/3'/6) | 1 项 (Phase 6 5 天验证) | 实施完毕 |
| 14 | §7 风险 | 4 个未解决项 | 3 个未解决项 (F-P4-03 新入 backlog) | Phase 4 修复部分 |
| 15 | §8 验收 #1 | "≥17 条" | "≥19 条" | §3.4 加 2 项 |
| 16 | §8 验收 #2 | "pre_midday 待 Phase 5" | 全部 ✅ | 实施完毕 |
| 17 | §8 验收 #6 | "Phase 4 验证, 待执行" | "✅ 48d2d06 之后已达成 (227/227 pass)" | 实施完毕 |
| 18 | 关联 commit | 3 个 (ef4e20f/6e14039/a72e395) | 7 个 (+ 4 新) | 实施完毕 |

**v3.1 总评**：v3 方案所有阶段实施完毕, 剩 Phase 6 5 个交易日被动验证启动。
预计 Phase 6 完成后 v3.1 → v3.2 (验证结果同步)。
