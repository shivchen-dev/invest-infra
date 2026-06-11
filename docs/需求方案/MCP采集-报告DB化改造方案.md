# MCP 采集 — 报告 DB 化改造方案

**主题：** 统一改造三大报告模块（盘前/午盘/盘后）为「采集入库 → DB 读取 → 降级兜底」架构，彻底消除报告层的运行时 MCP 调用
**版本：** v3（基于 Phase 0 实测 + ef4e20f 修复后更新）
**状态：** Phase 0-3 ✅ 完成｜Phase 4-6 ⏳ 待执行
**日期：** 2026-06-11
**原作者：** CIA（v1）
**v2 审计修订：** Arc（2026-06-11）
**v3 实证修订：** Arc（2026-06-11 18:15）

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

### 1.1 架构现状（v3 修订）

| 报告模块 | v2 描述 | v3 实测 | 状态 |
|---------|---------|---------|------|
| `post_market.py` | DB Only（已改造）| **真正 DB Only** (ef4e20f 修复后,17/17 工具入 DB) | ✅ |
| `pre_market.py` | DB 优先 + cache miss 走 MCP | **仍为混合策略** | ⏳ Phase 5 待改 |
| `midday.py` | DB 优先 + cache miss 走 MCP | **仍为混合策略** | ⏳ Phase 5 待改 |

**关键进展**：ef4e20f 修复后,15:05 采集从 8/17 真实数据 → **17/17 真实数据**。3 个长期走 FALLBACK_DATA 的 P0 工具（market_leaders / board_break / capital_flow_mkt）现在全部使用真实市场数据,盘后报质量立即提升。

### 1.2 MCP 限额（不变）

- MCP 日限额：**50 次/天**
- 每日采集：`market_data_collector.py` 17 个工具 / 4 批 ≈ 17 次
- 报告层：pre_market + midday 各 4-5 个工具在 cache miss 时触发
- **结论**：采集 17 次 + 报告 ~10 次 = 27 次,低于 50 次限额,采集+报告分离后无冲突

### 1.3 数据流（ef4e20f 修复后）

```
15:05 market_data_collector 批量采集 (17 工具) → daily_market_snapshot
  ↓
09:00 pre_market / 12:00 midday / 15:30 post_market 报告生成
  ├─ post_market: 纯读 DB (FALLBACK_DATA 仅在 DB miss 时,目前 0 个工具走这条)
  ├─ pre_market:  DB 优先 + cache miss 走 MCP ⏳ 待改
  └─ midday:      DB 优先 + cache miss 走 MCP ⏳ 待改
```

### 1.4 根因汇总（v3 修订）

| # | v1 根因 | v3 状态 | 修复 commit |
|---|---------|---------|-------------|
| 1 | market_leaders_pick 未加入 TRADE_DATE_TOOLS | **不存在** (早已在) | — |
| 2 | board_break_analysis / capital_flow_mkt 已采集但未入库 | **不存在** (因 9 SKIP 根因连带) | ef4e20f |
| 3 | 9 工具 (auction_*/stock_rank/...) 已采集但未入库 | **不存在** (因 9 SKIP 根因连带) | ef4e20f |
| 4 | smart_hotlist / capital_flow_hsgt 未加入采集清单 | **部分对** — DB 已有数据,但来源是 pre-market/midday 路径,不是 15:05 | 待决策 |
| 5 | pre_market.py / midday.py 仍为混合策略 | 仍存在 | ⏳ Phase 5 |
| 6 | cia_market_collect.timer 未创建 | **不存在** (早已在) | — |
| 7 | save_snapshot 异常被吞 (logger.error 无 traceback) | 仍存在,但非阻塞性 | 可选改进 |

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

### 2.3 改造范围（v3 更新）

| 状态 | 范围 | 文件 | commit |
|------|------|------|--------|
| ✅ | 修复 9 SKIP bug | `src/reports/market_data_collector.py` | ef4e20f |
| ✅ | DATE_PARAM_MAP 清理 | `src/reports/market_data_collector.py` | 6e14039 |
| ✅ | 现状快照归档 | `docs/需求方案/状态快照-2026-06-11.md` | a72e395 |
| ✅ | v2 方案归档 | `docs/需求方案/MCP采集-报告DB化改造方案.md` (v2 → v3) | a72e395 |
| ✅ | systemd 定时器 | `~/.config/systemd/user/cia_market_collect.{timer,service}` | (早已存在) |
| ⏳ | formatters 空数据测试 | `tests/test_formatters_empty_data.py` (新) | — |
| ⏳ | pre_market.py 移除运行时 MCP | `src/reports/modules/pre_market.py` | — |
| ⏳ | midday.py 移除运行时 MCP | `src/reports/modules/midday.py` | — |
| ❓ | smart_hotlist / capital_flow_hsgt 归一决策 | TRADE_DATE_TOOLS 或维持现状 | — |

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

### 3.4 ⚠️ 待决策项：smart_hotlist / capital_flow_hsgt 归一

**现状**：
- DB 已有 `smart_hotlist` (3 条,最新 2026-06-10) 和 `hsgt` (1 条,2026-06-10)
- 但**不是 15:05 collector 写的**,是 pre-market/midday 路径补的
- 命名不一致：`hsgt` vs v1 提案的 `capital_flow_hsgt`

**选项**：
- **A**：补到 TRADE_DATE_TOOLS（统一管理,15:05 也采一次,覆盖更全）
- **B**：维持现状（pre-market/midday 路径继续负责,15:05 不管）
- **建议 A**（便于审计,但会增加 ~2 次 MCP 调用/日）

**决策人**：CIA

---

## 四、报告层改造（⏳ Phase 4-5 待执行）

### 4.0 Phase 4 — formatters 空数据兼容性测试（⏳ 1h）

> **必做前置**：在删 MCP 调用前,先确认所有 formatters 在 `{"rows": [], "summary": {}}` 空数据下不崩溃。

**操作**：见 v2 §4.0（未变）

**新增文件**：`tests/test_formatters_empty_data.py`

**关键约束**：
- **硬兜底**：`{"rows": [], "summary": {}}` — formatters 必须能安全访问任意字段
- **软兜底**：formatters 内部检测到 `rows == []` 时,输出"⚠️ 数据采集失败,请参考前一交易日报告"

### 4.1 Phase 5.1 — pre_market.py 移除运行时 MCP（⏳ 1h）

**改造逻辑**：
```
DB 查 → 有 → 用
  → 无 → 走 FALLBACK_DATA (不触发 MCP,触发软兜底提示)
```

**具体改动**：
1. 删除 `fetch()` 中的 `self.mcp` 调用路径
2. 统一走 `cache.get(data_type)` → 无数据则用 `FALLBACK_DATA` + 软兜底提示
3. 保留 WOA memo 数据源（`fetch_memo`）,独立数据流

### 4.2 Phase 5.2 — midday.py 移除运行时 MCP（⏳ 1h）

改造逻辑同 §4.1。

### 4.3 post_market.py（✅ 已 DB Only）

代码层早已是 DB Only,ef4e20f 修复后实际数据从兜底 → 真实,**无需再改**。

### 4.4 FALLBACK_DATA 设计原则（v2 §4.4,不变）

| 维度 | 硬兜底 | 软兜底 |
|------|--------|--------|
| 结构 | 与 MCP 返回 JSON schema 字段一致 | 在 formatters 中检测到空 rows 输出"⚠️ 数据缺失" |
| 数值 | 默认 0 / 空数组 | 注明"采集失败",避免误读为"市场真无数据" |
| 时间戳 | 默认 None 或昨日 | 注明降级时间 |

---

## 五、采集清单（v3 修订）

实际 TRADE_DATE_TOOLS（17 项）:

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
| 15 | smart_hotlist | smart_hotlist | 盘前/午盘 | P1 | ❓ 见 §3.4 |
| 16 | capital_flow_hsgt | capital_flow(flowType=hsgt) | 盘前 | P2 | ❓ 见 §3.4 |
| 17 | stock_rank_volume | stock_rank(type=volume) | — | P2 | ✅ (修复前 SKIP) |
| 18 | stock_rank_turnover | stock_rank(type=turnover_rate) | — | P2 | ✅ (修复前 SKIP) |
| 19 | cls_news | cls_news | 盘前 | P2 | ✅ |

> **DB 中另有**：`hsgt` (1 条,2026-06-10) — 与 #16 同源,命名不一致,**待决策**

---

## 六、执行计划（v3 修订）

### 6.1 已完成（v3 时间戳）

| Phase | commit | 实际耗时 | 产出 |
|-------|--------|---------|------|
| 0 现状快照 | a72e395 | ~30 min | 状态快照-2026-06-11.md |
| 1 根因定位 | (含在 0 中) | 0 min (无需单独跑,因 §3.4 路径未走) | 状态快照 §4 |
| 2 采集层修复 | ef4e20f | ~15 min (含验证) | 1 行修复 + 诊断日志 |
| 3 DATE_PARAM_MAP 清理 | 6e14039 | ~5 min | 3 个工具 None 化 |
| 3' 定时器 | (无需) | 0 min | 早已存在 |

**已完成总耗时**：~1h（vs v1/v2 估算的 4-5h）

### 6.2 剩余（v3 时间戳）

| Phase | 任务 | 估算 | 前置 | 验收 |
|-------|------|------|------|------|
| **4** | formatters 空数据测试 | 1h | — | pytest 全 pass + 覆盖率 100% |
| **5.1** | pre_market.py 移除 MCP | 0.5h | Phase 4 | grep 无 MCP 调用 + 真报告无 IndexError |
| **5.2** | midday.py 移除 MCP | 0.5h | Phase 4 | 同上 |
| **3'** | smart_hotlist/capital_flow_hsgt 决策 | (由 CIA 决定) | — | TRADE_DATE_TOOLS 加入 or 维持现状 |
| **6** | 5 个交易日连续验证 (ef4e20f 之后) | 5 天 | Phase 5 | 每日 MCP 调用次数 = 0 / DB 命中率 ≥ 95% / 无 formatters 报错 |

**剩余总工作量**：~2h 实施 + 5 天验证

### 6.3 回滚计划（v2 引入,不变）

| 触发条件 | 回滚步骤 | 责任人 |
|---------|---------|--------|
| Phase 4 formatters 测试不通过 | 先修 formatters,再进 Phase 5 | CIA |
| Phase 5 后报告生成报错 | `git revert` 对应 commit + 恢复 `mcp_client` 调用路径 | CIA |
| Phase 6 连续 2 天 DB 命中率 < 80% | 回滚到上一稳定版本,单独排查采集层 | Arc + CIA |

---

## 七、风险与缓解（v3 修订）

| 风险 | v3 状态 | 缓解措施 | SLA |
|------|---------|---------|-----|
| 15:05 采集时 MCP 限额从 0 点起算已耗尽 | 仍存在 | 采集脚本内 MCP 失败写 failed 日志 | 单次失败不影响其他数据源 |
| 采集超时（>20min） | 仍存在 | 看门狗（cron_watchdog）监控超时,会补发 | **15:25 前 P0 必须全部入库** |
| 15:25 后仍未完成 P0 入库 | 仍存在 | 报告降级生成 + 告警到值班 | 报告可降级,但不能崩 |
| ciA_market_collect.timer 未创建 | **已解决** (Phase 0 实测) | — | — |
| save_snapshot 异常被吞 (logger.error 无 traceback) | 仍存在,**非阻塞** | ef4e20f 后 SKIP 路径不再常态命中;作为可选改进 | — |
| 9 SKIP 根因 (results.get key 错位) | **已解决** (ef4e20f) | — | — |
| **新增**：MCP_TOKEN 环境变量未加载 | ef4e20f 验证时暴露 | cron_dispatcher.py 加载 `.secrets/mcp.env`,CLI 跑需手动 `export` | 必须随 collector 一起加载 |
| pre_market / midday 改造后 formatters 崩 | 仍存在 | Phase 4 测试覆盖 | 测试覆盖率 100% |

---

## 八、验收标准（v3 修订）

1. **15:05 任务执行后**，`daily_market_snapshot` 有 **≥17 条**（非 v2 的 ≥16）今日采集记录（P0 全覆盖）— ✅ ef4e20f 之后已达成
2. **09:25/12:30/15:30 报告生成时**，日志中 MCP 调用次数 = 0（pre/midday 待 Phase 5; post_market ✅）
3. **盘后报** P0 数据全部可从 DB 读取 — ✅ ef4e20f 之后已达成
4. **ef4e20f 之后连续 5 个交易日** P0 数据无缺失
5. **cron_watchdog 触发或人工补发 ≤ 1 次**（5 天内自动化率 ≥ 80%）
6. **报告 formatters 在空 DB 数据下不崩溃**（Phase 4 验证,待执行）

---

*原作者：v1 CIA / v2-v3 Arc，2026-06-11*
*关联 commit：ef4e20f / 6e14039 / a72e395*
*关联文档：状态快照-2026-06-11.md*
