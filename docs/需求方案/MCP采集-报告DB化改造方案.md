# MCP 采集 — 报告 DB 化改造方案

**主题：** 统一改造三大报告模块（盘前/午盘/盘后）为「采集入库 → DB 读取 → 降级兜底」架构，彻底消除报告层的运行时 MCP 调用
**状态：** 待评审（v2 修订中）
**日期：** 2026-06-11
**原作者：** CIA
**审计/修订：** Arc（基于 2026-06-11 评审反馈）

---

## 〇、v2 变更说明

| # | v1 章节 | v2 修改 | 触发原因 |
|---|---------|---------|---------|
| 1 | §3.1.2/§3.1.3 | 拆为 §3.0 现状快照 + §3.1 根因定位两个独立阶段 | v1 根因分析是"列举"不是"分析"，11 个工具可能是同一个根因 |
| 2 | §4.1/§4.2 | 新增 §4.0 formatters 空数据兼容性测试作为前置条件 | v1 未评估 FALLBACK_DATA 空结构对 formatters 的影响 |
| 3 | §5 | 删除重复的 `concept_ranking` 条目 | v1 行 14 和行 20 重复 |
| 4 | §6 | 重构为 6 阶段，每阶段明确时长和验收 | v1 只有任务清单，没有阶段边界和验收标准 |
| 5 | §7 | 新增数据新鲜度 SLA | v1 缺 15:25 截止时间约束 |
| 6 | §8 | 验收标准从 3 个交易日改为 5 个交易日 | v1 验证窗口太短 |
| 7 | 新增 | §六回滚计划 | v1 完全缺 |
| 8 | 新增 | §四.4 FALLBACK_DATA 硬/软分级 | v1 全是硬兜底，报告内容会"空白化" |

---

## 一、现状问题

### 1.1 架构缺陷：三套数据策略并存

| 报告模块 | 当前策略 | 问题 |
|---------|---------|------|
| `post_market.py` | DB Only（已改造） | ⚠️ 仅 5/16 工具实际入库，剩余 11 个 DB miss 时走 FALLBACK_DATA 降级（数据实际为兜底值） |
| `pre_market.py` | DB 优先 + cache miss 走 MCP | ❌ 运行时 MCP 调用，限额耗尽 |
| `midday.py` | DB 优先 + cache miss 走 MCP | ❌ 同上 |

> **注：** `post_market.py` 虽标注"DB Only"，但因实际入库工具仅 5/16，**实际运行中大部分数据走的是 FALLBACK_DATA 降级路径**。从数据真实性角度看，三份报告当前都未达到"真 DB 化"标准。

### 1.2 MCP 限额现状

- MCP 日限额：**50 次/天**
- 每日采集：`market_data_collector.py` 16 个工具 × 3-4 批 ≈ 16 次
- 报告层：`pre_market.py` + `midday.py` 各 4-5 个工具在 cache miss 时触发
- **结论：** 采集 + 报告混合使用，限额经常在 15:30 盘后报时段耗尽，导致盘后报告部分数据降级

### 1.3 数据流现状（改造前）

```
15:05 market_data_collector → 16 工具分批采集 → 写入 daily_market_snapshot
     ↓（实际：只有 5 个工具确认入库，其余 11 个未入库或入库失败）

09:25 / 12:30 / 15:30 报告生成
  ├─ cache.get(data_type) → DB 有 → 用
  ├─ DB 无 → pre_market/midday: 触发 MCP（运行时）
  └─ post_market: 走 FALLBACK_DATA（不触发 MCP，但数据实际是降级的）
```

### 1.4 根因汇总

| # | 根因 | 影响 |
|---|------|------|
| 1 | 部分工具未加入 `TRADE_DATE_TOOLS`（如 `market_leaders_pick` 状态待确认） | 盘后报缺 P0 数据 |
| 2 | `board_break_analysis` / `capital_flow_mkt` 已加入采集但未入库 | 盘后报缺 P0 数据 |
| 3 | 其余 9 个工具已加入采集但未入库（`auction_*` / `concept_ranking` / `cls_news` 等） | 盘前/午盘报缺数据 |
| 4 | `smart_hotlist` / `capital_flow(flowType=hsgt)` 未加入采集清单 | 盘前报缺数据 |
| 5 | `pre_market.py` 和 `midday.py` 仍为混合策略，cache miss 时走 MCP | 限额消耗/数据不稳定 |
| 6 | 采集任务 `ciA_market_collect.timer` 未创建 | 无定时触发 |
| 7 | `save_snapshot` 异常被 `try/except` 吞掉仅 log warning | 根因 2/3 难以定位 |

> **注 1-4 项为待确认项**，执行前需通过 §3.0 现状快照精确核对，避免重复修复或漏修。

---

## 二、改造目标

### 2.1 架构原则

> **MCP 只负责采集数据入库，报告只读 DB，MCP 不出现在报告的运行时调用链中。**

### 2.2 目标数据流

```
15:05 market_data_collector 批量采集 → daily_market_snapshot（≥16 工具）
  ↓
09:25 / 12:30 / 15:30 报告生成 → 纯读 DB → DB 未命中 → 降级兜底（0 次 MCP 调用）
```

### 2.3 改造范围

| 范围 | 文件 | 操作 |
|------|------|------|
| 采集层修复 | `src/reports/market_data_collector.py` | 补全缺失工具 + 修复入库 + 增强日志 |
| 采集层新增 | `scripts/cron_dispatcher.py` | 注册 market_data_collect 任务 |
| 采集层新增 | `~/.config/systemd/user/ciA_market_collect.{timer,service}` | 定时触发 |
| 报告层前置 | `tests/test_formatters_empty_data.py`（新） | formatters 空数据兼容性测试 |
| 报告层改造 | `src/reports/modules/pre_market.py` | 移除运行时 MCP |
| 报告层改造 | `src/reports/modules/midday.py` | 移除运行时 MCP |
| 报告层已有 | `src/reports/modules/post_market.py` | 已 DB Only，无需改动 |

---

## 三、采集层修复（分 4 阶段）

### 3.0 Phase 0 — 现状快照（30 min，前置必做）

> **目的**：在动手改任何代码前，精确量化"5/16 工具实际入库"中"5"是哪 5 个、缺的是哪 11 个、以及每条的失败原因。

**操作：**

```bash
# 1. DB 实际入库快照（最近 5 个交易日）
cd /home/claw/invest-infra/data-pipeline && \
.venv/bin/python -c "
import pymysql
conn = pymysql.connect(host='127.0.0.1', user='xxx', password='xxx', db='invest')
with conn.cursor() as cur:
    cur.execute('''
        SELECT data_type, COUNT(*) cnt, MAX(trade_date) latest
        FROM daily_market_snapshot
        WHERE trade_date >= CURRENT_DATE - INTERVAL 5 DAY
        GROUP BY data_type
        ORDER BY data_type
    ''')
    for row in cur.fetchall(): print(row)
"

# 2. 采集清单与参数映射当前状态
grep -nE '"name":|TRADE_DATE_TOOLS|DATE_PARAM_MAP' src/reports/market_data_collector.py | head -80

# 3. systemd 定时器状态
systemctl --user list-timers --all | grep -E 'collect|report' || echo "无相关 timer"
```

**输出（归档至 `docs/需求方案/状态快照-2026-06-11.md`）：**

| 维度 | 数据 |
|------|------|
| 当前入库工具数 | TBD（填入） |
| 缺哪些 data_type | TBD |
| 哪些工具在 TRADE_DATE_TOOLS 但未入库 | TBD |
| 哪些工具不在 TRADE_DATE_TOOLS | TBD |
| 定时器状态 | TBD |

> **未完成 Phase 0，禁止进入 Phase 1。**

### 3.1 Phase 1 — 根因定位（30 min，dry-run）

> **目的**：在不改任何代码的前提下，跑一次 dry-run，统计每个工具的 `[OK/FAIL/SKIP]` 状态，**判断 11 个未入库工具是同一个根因还是多个根因**。

**操作：**

```python
# scripts/dryrun_market_collect.py（一次性脚本，不入版本）
import sys; sys.path.insert(0, 'src/reports')
from market_data_collector import collect_all
result = collect_all(dry_run=True)
print('按工具:')
for k, v in result.items():
    print(f'  {k}: {v["status"]} - {v.get("error", "")[:100]}')
print('\n按状态汇总:')
from collections import Counter
c = Counter(v['status'] for v in result.values())
print(f'  {dict(c)}')
```

**判定逻辑：**

| 失败模式分布 | 根因判定 | 修复策略 |
|-------------|---------|---------|
| 11 个全部 `FAIL: connection timeout` | 系统性网络问题 | 1 处加 retry 即可 |
| 11 个全部 `FAIL: JSONDecodeError` | 系统性解析问题 | 1 处加 response.text fallback |
| 11 个分散在不同错误 | 个别工具问题 | 11 处单独处理 |
| 部分 `OK` 部分 `SKIP` | 业务逻辑跳过 | 查 SKIP 条件 |

### 3.2 Phase 2 — 针对性修复（1-2 h）

> **根据 Phase 1 结果决定工作量**。下面的子项是"如果 Phase 1 显示这些工具属于 X 类问题，则对应执行"。

#### 3.2.1 补全采集清单（如果 §3.0 显示工具不在 `TRADE_DATE_TOOLS`）

在 `market_data_collector.py` 中补加：

```python
{
    "name": "smart_hotlist",
    "params": {"source": "combined", "limit": 10, "detailLevel": "standard", "format": "json"},
    "data_type": "smart_hotlist",
},
{
    "name": "capital_flow",
    "params": {"flowType": "hsgt", "limit": 5, "detailLevel": "standard", "format": "json"},
    "data_type": "capital_flow_hsgt",
},
```

`DATE_PARAM_MAP` 中补加：

```python
"smart_hotlist": None,       # 无日期参数
"capital_flow_hsgt": "date", # 与 capital_flow_mkt 共用 date 参数
```

#### 3.2.2 修复 `save_snapshot` 异常处理（独立于 Phase 1 根因，先做）

```python
# save_snapshot 中捕获异常时，打印完整 traceback
except Exception as e:
    import traceback
    logger.error(f"写入 snapshot 失败 [{data_type}]: {e}\n{traceback.format_exc()}")
    conn.rollback()
    return False
```

#### 3.2.3 分类修复（基于 Phase 1 根因结果）

> **不在 v2 中预设**——根据 Phase 1 输出的失败模式分布表，逐类修复。例如：

- 如果是网络问题 → 加重试 + 退避
- 如果是解析问题 → 加 content-type 判断 + 原始 body fallback
- 如果是 DB 写入问题 → 加 dead-letter 队列

### 3.3 Phase 3 — 定时器创建（30 min）

#### 3.3.1 注册 TASK_MAP

**文件：** `scripts/cron_dispatcher.py`

```python
"market_data_collect": {
    "desc": "收盘数据采集（15:05）",
    "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python scripts/cron_market_data_collect.py",
    "timeout": 300,
},
```

#### 3.3.2 创建 systemd timer + service

**`~/.config/systemd/user/ciA_market_collect.timer`：**
```ini
[Unit]
Description=CIA market data collect timer (15:05 on trade days)

[Timer]
OnCalendar=*-*-* 15:05:00
Persistent=true

[Install]
WantedBy=timers.target
```

**`~/.config/systemd/user/ciA_market_collect.service`：**
```ini
[Unit]
Description=CIA market data collect service

[Service]
Type=oneshot
ExecStart=/home/claw/invest-infra/data-pipeline/.venv/bin/python /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py market_data_collect
StandardOutput=append:/home/claw/invest-infra/data-pipeline/logs/cron_cia.log
StandardError=append:/home/claw/invest-infra/data-pipeline/logs/cron_cia.log
```

**启用：**
```bash
systemctl --user enable --now ciA_market_collect.timer
systemctl --user list-timers --all | grep market   # 确认激活
```

---

## 四、报告层改造（前置 + 3 步）

### 4.0 Phase 4 — formatters 空数据兼容性测试（1 h，**前置必做**）

> **目的**：在删 MCP 调用前，先确认所有 formatters 在 `{"rows": [], "summary": {}}` 空数据下不崩溃。

**操作：**

```python
# tests/test_formatters_empty_data.py
import pytest
from src.reports.formatters import (
    format_pre_market, format_midday, format_post_market,
)

EMPTY_DATA = {
    "market_overview": {"content": [{"text": "{}"}]},
    "sector_analysis": {"rows": [], "summary": {}},
    "smart_hotlist": {"rows": [], "summary": {}},
    "limit_stats": {"sealedLimitUp": 0, "sealedLimitDown": 0},
    "auction_scan": {"rows": [], "summary": {}},
    "auction_wts": {"rows": [], "summary": {}},
    "capital_flow_hsgt": {"items": [], "summary": {}},
    "capital_flow_mkt": {"items": [], "summary": {}},
    "broken_limit_up": {"rows": [], "summary": {}},
    "concept_ranking": {"rows": [], "summary": {}},
}

def test_format_pre_market_empty():
    """所有数据为空时,format_pre_market 不抛 IndexError/KeyError/TypeError"""
    out = format_pre_market(EMPTY_DATA)
    assert isinstance(out, str) and len(out) > 0

# 其他 formatters 同理
```

**关键约束（v2 新增）：**

- **硬兜底（结构性空）**：`{"rows": [], "summary": {}}`——formatters 必须能安全访问任意字段
- **软兜底（可读性降级）**：在 formatter 内部检测到 `rows == []` 时，输出"⚠️ 数据采集失败，请参考前一交易日报告"提示，而非空白

```python
# 软兜底示例（formatter 内部）
if not data.get("rows"):
    return f"⚠️ [{data_type}] 数据缺失，请参考前一交易日"
```

> **未完成 Phase 4，禁止进入 §4.1/§4.2 报告层代码改造。**

### 4.1 pre_market.py — 移除运行时 MCP

**改造逻辑：**

```
DB 查 → 有 → 用
  → 无 → 走 FALLBACK_DATA（不触发 MCP，触发软兜底提示）
```

**具体改动：**

1. 删除 `fetch()` 中的 `self.mcp` 调用路径（Step 2 MCP 调用）
2. 统一走 `cache.get(data_type)` → 无数据则用 `FALLBACK_DATA` + 软兜底提示
3. 保留 WOA memo 数据源（`fetch_memo`），独立数据流

### 4.2 midday.py — 移除运行时 MCP

改造逻辑同 §4.1。

### 4.3 post_market.py — 已有，无需改动

### 4.4 FALLBACK_DATA 设计原则（v2 新增）

| 维度 | 硬兜底（必须满足） | 软兜底（建议实现） |
|------|-------------------|-------------------|
| 结构 | 与 MCP 返回 JSON schema 字段一致 | 在 formatters 中检测到空 rows 输出"⚠️ 数据缺失" |
| 数值 | 默认 0 / 空数组 | 注明"采集失败"，避免误读为"市场真无数据" |
| 时间戳 | 默认 None 或昨日 | 注明降级时间 |

---

## 五、采集清单（最终版）

改造后 `market_data_collector.py` 应覆盖以下数据源：

| # | data_type | MCP 工具 | 报告需要 | 优先级 |
|---|-----------|---------|---------|-------|
| 1 | market_overview | market_overview | 盘前/午盘/盘后 | P0 |
| 2 | limit_stats | limit_stats | 盘前/午盘/盘后 | P0 |
| 3 | hot_sectors | hot_sectors | 盘后 | P0 |
| 4 | limit_up_ladder | limit_up_ladder | 盘后 | P0 |
| 5 | market_leaders | market_leaders_pick | 盘后 | P0 |
| 6 | board_break | board_break_analysis | 盘后 | P0 |
| 7 | capital_flow_mkt | capital_flow(flowType=market) | 盘后 | P0 |
| 8 | sector_analysis | sector_analysis | 盘前 | P0 |
| 9 | market_replay | market_replay_workflow | 盘前 | P1 |
| 10 | auction_scan | auction_market_scan | 盘前 | P1 |
| 11 | auction_wts | auction_weak_to_strong | 盘前 | P1 |
| 12 | auction_feedback | auction_limitup_feedback | — | P2 |
| 13 | broken_limit_up | broken_limit_up | 午盘 | P1 |
| 14 | concept_ranking | concept_ranking | 午盘 | P1 |
| 15 | smart_hotlist | smart_hotlist | 盘前/午盘 | P1 |
| 16 | capital_flow_hsgt | capital_flow(flowType=hsgt) | 盘前 | P2 |
| 17 | stock_rank_volume | stock_rank(type=volume) | — | P2 |
| 18 | stock_rank_turnover | stock_rank(type=turnover_rate) | — | P2 |
| 19 | cls_news | cls_news | 盘前 | P2 |

**P0（必须入库）：** 1-8
**P1（应该入库）：** 9-15
**P2（尽量入库）：** 16-19

> **注：** 实际清单以 Phase 0 现状快照结果为准——如果某些工具在采集层存在但运行失败，应替换为同类备用工具。

---

## 六、执行计划（6 阶段）

| Phase | 任务 | 时长 | 前置 | 验收标准 |
|-------|------|------|------|---------|
| **0** | 现状快照 | 30 min | — | 1 页报告：实际入库 vs 方案预期 gap 表 |
| **1** | dry-run 根因定位 | 30 min | Phase 0 | 失败模式分布表 + 根因判定 |
| **2** | 采集层修复 | 1-2 h | Phase 1 | dry-run 全 OK + 真采集 ≥16 工具全入库 |
| **3** | 定时器创建 | 30 min | — | `systemctl list-timers` 显示 ciA_market_collect 激活 |
| **4** | formatters 空数据测试 | 1 h | Phase 2 | pytest 覆盖率 100% + 全 pass |
| **5** | 报告层改造 pre/midday | 1 h | Phase 4 | grep `call_batch\|mcp_client` 无残留 + 真报告生成无 IndexError |
| **6** | 5 个交易日连续验证 | 5 天 | Phase 5 | 每日 MCP 调用次数 = 0 / DB 命中率 ≥ 95% / 报告无 formatters 报错 |

**总工作量预估：4-5 h 实施 + 5 天验证。**

### 6.1 回滚计划（v2 新增）

| 触发条件 | 回滚步骤 | 责任人 |
|---------|---------|--------|
| Phase 2 后 dry-run 仍有 FAIL | 恢复 §3.2.2 改动（save_snapshot traceback 可保留） | CIA |
| Phase 5 后报告生成报错 | `git revert` 当次 commit + 恢复 `mcp_client` 调用路径 | CIA |
| Phase 6 连续 2 天 DB 命中率 < 80% | 回滚到上一稳定版本，单独排查采集层 | Arc + CIA |

回滚 SOP 写入 `scripts/rollback_mcp_db_separation.md`，实施前归档。

---

## 七、风险与缓解

| 风险 | 缓解措施 | SLA |
|------|---------|-----|
| 15:05 采集时 MCP 限额从 0 点起算已耗尽 | 采集脚本内 MCP 调用失败写 failed 日志，不影响其他数据源 | 单次失败不影响其他数据源 |
| 采集超时（>20min） | 看门狗（cron_watchdog）监控超时，会补发 | **15:25 前 P0 必须全部入库**（v2 新增） |
| 15:25 后仍未完成 P0 入库 | 报告降级生成 + 告警到值班 | 报告可降级，但不能崩 |
| `market_data_collector` 本身也有 MCP 调用次数限制 | 每日约 20 次 MCP 调用，远低于 50 次限额 | — |
| `pre_market.py` / `midday.py` 原有逻辑依赖 MCP 返回的特定字段结构 | 降级数据需保持与 MCP 返回相同的嵌套结构 | Phase 4 测试覆盖 |
| 改造后某个 formatters 在空数据下崩 | Phase 4 测试覆盖，全部 pass 才能进 Phase 5 | 测试覆盖率 100% |
| Phase 1 根因是多个而非单个 | 工作量从 1-2h 上升到 3-4h | 通过 Phase 0 提前预估 |

---

## 八、验收标准

1. **15:05 任务执行后**，`daily_market_snapshot` 有 ≥16 条今日采集记录（P0 全覆盖）
2. **09:25/12:30/15:30 报告生成时**，日志中 MCP 调用次数 = 0
3. **盘后报** P0 数据（market_overview / limit_stats / hot_sectors / limit_up_ladder / market_leaders / board_break / capital_flow_mkt）全部可从 DB 读取
4. **连续 5 个交易日** P0 数据无缺失（v2 从 3 改为 5）
5. **cron_watchdog 触发或人工补发 ≤ 1 次**（即 5 天内自动化率 ≥ 80%，v2 新增）
6. **报告 formatters 在空 DB 数据下不崩溃**（Phase 4 验证，v2 新增）
7. **新增**：Phase 0 现状快照归档为 `docs/需求方案/状态快照-2026-06-11.md` 并 review 通过

---

*审计员/修订：Arc，2026-06-11*
