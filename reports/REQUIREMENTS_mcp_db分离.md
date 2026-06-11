# 投研系统收盘数据改造方案
**主题：** MCP 采集 → DB 缓存 → 报告只读 DB，彻底消除运行时 MCP 调用压力
**状态：** 待评审
**日期：** 2026-06-08

---

## 一、现状问题

### 1.1 数据流架构（现状）

```
15:30 post_market 报告生成
  ├─ MarketDataCache.get() → 查 daily_market_snapshot
  │   ├─ limit_stats      ✅ DB命中（已采集入库）
  │   ├─ hot_sectors       ✅ DB命中（已采集入库）
  │   ├─ limit_up_ladder   ✅ DB命中（已采集入库）
  │   ├─ market_leaders   ❌ DB未命中 → 触发 MCP 实时调用
  │   ├─ board_break      ❌ DB未命中 → 触发 MCP 实时调用
  │   └─ capital_flow_mkt ❌ DB未命中 → 触发 MCP 实时调用
  └─ 3项 MCP 调用全部触发 → MCP 日限额50次已耗尽 → 限流失败
```

**结果：** 盘后报告 3/6 数据源缺失，只能用降级结果。

### 1.2 根因分析

| 根因 | 说明 |
|------|------|
| `market_data_collector.py` 缺少 `market_leaders_pick` | 采集清单漏项 |
| `market_data_collector.py` 从未加入定时调度 | 有工具，无调度 |
| `board_break_analysis` 和 `capital_flow_mkt` 虽然在采集清单里但实际未入库 | 可能是采集失败未追查 |
| 报告模块 fallback 到 MCP 导致限额耗尽 | 架构设计问题 |

### 1.3 采集清单与实际入库对比

| 数据源 | market_data_collector 有无 | daily_market_snapshot 有无 | 报告是否需要 |
|--------|--------------------------|--------------------------|------------|
| `market_overview` | ✅ | ✅ | 盘前用 |
| `limit_stats` | ✅ | ✅ | ✅ 盘后用 |
| `hot_sectors` | ✅ | ✅ | ✅ 盘后用 |
| `limit_up_ladder` | ✅ | ✅ | ✅ 盘后用 |
| `board_break_analysis` | ✅ | ❌ 未入库 | ✅ 盘后用 |
| `capital_flow` | ✅ | ❌ 未入库 | ✅ 盘后用 |
| `market_replay_workflow` | ✅ | ❌ 未入库 | 盘前用 |
| `broken_limit_up` | ✅ | ❌ 未入库 | — |
| `auction_market_scan` | ✅ | ❌ 未入库 | 盘前用 |
| `auction_weak_to_strong` | ✅ | ❌ 未入库 | 盘前用 |
| `auction_limitup_feedback` | ✅ | ❌ 未入库 | — |
| `stock_rank` | ✅ (×2) | ❌ 未入库 | — |
| `cls_news` | ✅ | ❌ 未入库 | 盘前用 |
| `concept_ranking` | ✅ | ❌ 未入库 | — |
| `sector_analysis` | ✅ | ✅ | 盘前用 |
| **`market_leaders_pick`** | ❌ **漏加** | ❌ | ✅ 盘后用 |

**结论：** 16个工具中，实际入库的仅 5 个（limit_stats/hot_sectors/limit_up_ladder/sector_analysis/market_overview），其余11个有工具无调度或调度了但采集失败。

---

## 二、改造目标

### 2.1 架构原则

> **MCP 只负责采集数据入库，报告只读 DB，MCP 不出现在报告的运行时调用链中。**

### 2.2 目标状态

```
15:05 market_data_collector 批量采集 → daily_market_snapshot
15:30 post_market 报告生成 → 只读 DB → 0 次 MCP 调用
```

### 2.3 改造范围

1. **修复 `market_data_collector.py`**
   - 补全缺失的 `market_leaders_pick`
   - 排查 11 个数据源未入库的原因（board_break/capital_flow/market_replay 等）

2. **新增定时任务 `ciA_market_collect.timer/service`**
   - 15:05 执行（收盘后立即批量采集）
   - 覆盖所有报告需要的数据

3. **改造报告模块**
   - 删除 `post_market.py` 中运行时 MCP 调用逻辑
   - 改为纯 DB 读取，DB 未命中则用降级静态数据（不触发 MCP）

4. **改造 `cron_dispatcher.py`**
   - 注册 `market_data_collect` 任务入口

5. **新增执行记录日志**
   - 采集结果写日志，便于监控哪些数据源成功/失败

---

## 三、改造详情

### 3.1 修复 market_data_collector.py

#### 3.1.1 补全 `market_leaders_pick`

**文件：** `src/reports/market_data_collector.py`

在 `TRADE_DATE_TOOLS` 列表中增加：
```python
{
    "name": "market_leaders_pick",
    "params": {"detailLevel": "standard", "format": "json"},
    "data_type": "market_leaders",
},
```

在 `DATE_PARAM_MAP` 中增加：
```python
"market_leaders_pick": "date",
```

#### 3.1.2 补全 `market_replay_workflow` 的 date 参数

`market_replay_workflow` 的 date 参数名是 `date`，确认已在 `DATE_PARAM_MAP` 中。

#### 3.1.3 采集结果写入日志（增强）

每次采集完成后，写入结构化日志：
```
[2026-06-08 15:05:32] market_data_collect: success=14, failed=2, skipped=0
  [OK] market_leaders
  [OK] capital_flow_mkt
  [FAIL] board_break_analysis — MCP error: DAILY_LIMIT_EXCEEDED
```

便于：
- 监控哪些数据源失败
- 追溯 `board_break_analysis` 等长期失败的原因

### 3.2 新增定时任务

#### 3.2.1 注册 TASK_MAP 入口

**文件：** `scripts/cron_dispatcher.py`

在 `TASK_MAP` 中增加：
```python
"market_data_collect": {
    "desc": "收盘数据采集（15:05）",
    "shell": "cd /home/claw/invest-infra/data-pipeline && .venv/bin/python src/reports/market_data_collector.py",
    "timeout": 300,
},
```

#### 3.2.2 创建 systemd timer + service

**文件：** `~/.config/systemd/user/ciA_market_collect.timer`
```ini
[Unit]
Description=CIA market data collect timer (15:05)

[Timer]
OnCalendar=*-*-* 15:05:00
Persistent=true

[Install]
WantedBy=timer.target
```

**文件：** `~/.config/systemd/user/ciA_market_collect.service`
```ini
[Unit]
Description=CIA market data collect service

[Service]
Type=oneshot
ExecStart=/home/claw/invest-infra/data-pipeline/.venv/bin/python /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py market_data_collect
StandardOutput=append:/home/claw/invest-infra/data-pipeline/logs/cron_cia.log
StandardError=append:/home/claw/invest-infra/data-pipeline/logs/cron_cia.log
```

#### 3.2.3 启用定时器

```bash
systemctl --user enable --now ciA_market_collect.timer
```

### 3.3 改造报告模块 — 移除运行时 MCP 调用

#### 3.3.1 改造 `PostMarketReporter.fetch()`

**文件：** `src/reports/modules/post_market.py`

**现状逻辑（第 51-80 行）：**
```
DB 查 → 有 → 用
    → 无 → MCP 调用（运行时）→ 写入 DB
```

**改造后逻辑：**
```
DB 查 → 有 → 用
    → 无 → 返回降级空数据（不触发 MCP）
```

即：**删除 Step 2（MCP 调用写入 DB），改为纯 DB 读取 + 降级兜底**。

#### 3.3.2 降级数据定义

| 数据源 | DB 未命中时 |
|--------|------------|
| `market_leaders` | `{"hasMainLine": false, "mainLines": [], "observations": []}` |
| `board_break` | `{"focus": "all", "statusBreakdown": {}, "breakRate": "N/A"}` |
| `capital_flow_mkt` | `{"items": [], "summary": {}}` |

#### 3.3.3 同样改造其他报告模块

| 模块 | 文件 | 同样移除运行时 MCP |
|------|------|-----------------|
| 盘前报 | `modules/pre_market.py` | ✅ |
| 午盘报 | `modules/midday.py` | ✅ |

### 3.4 采集时间窗口分析

```
15:00  收盘（index_eod 北向数据采集）
15:05  market_data_collect 批量采集（16个工具，5个一批约3批）
15:25  采集完成，数据写入 daily_market_snapshot
15:30  post_market 报告生成，纯读 DB
```

若 `market_data_collector` 执行超过 20 分钟（采集超时），`post_market` 报告会拿到部分数据，后续可接受。

### 3.5 数据源覆盖目标

改造完成后，以下数据源必须在 15:25 前入库：

| 优先级 | 数据源 | 用途 | 备注 |
|--------|--------|------|------|
| P0 | `market_overview` | 盘前/午盘/盘后 | 已有 |
| P0 | `limit_stats` | 盘前/午盘/盘后 | 已有 |
| P0 | `hot_sectors` | 盘前/午盘/盘后 | 已有 |
| P0 | `limit_up_ladder` | 盘后 | 已有 |
| P0 | `market_leaders` | 盘后 | **补加** |
| P0 | `board_break` | 盘后 | 待排查为何未入库 |
| P0 | `capital_flow_mkt` | 盘后 | 待排查为何未入库 |
| P1 | `market_replay` | 盘前 | 待排查为何未入库 |
| P1 | `sector_analysis` | 盘前 | 已有 |
| P1 | `cls_news` | 盘前 | 待排查为何未入库 |
| P2 | `auction_*` | 盘前竞价 | 待排查 |
| P2 | `concept_ranking` | — | 待定 |
| P2 | `stock_rank` | — | 待定 |

---

## 四、执行计划

### Step 1（高优）：修复 market_data_collector.py
- [ ] 补加 `market_leaders_pick` 到 TRADE_DATE_TOOLS
- [ ] 补加 `market_leaders_pick` 到 DATE_PARAM_MAP
- [ ] 增强采集日志（成功/失败分行列出）
- [ ] 手动运行一次验证：`python src/reports/market_data_collector.py`

### Step 2（高优）：注册任务到 cron_dispatcher.py
- [ ] 在 TASK_MAP 中注册 `market_data_collect`
- [ ] 创建 systemd timer + service 文件
- [ ] `systemctl --user enable --now ciA_market_collect.timer`

### Step 3（高优）：改造 post_market.py
- [ ] 删除 `PostMarketReporter.fetch()` 中的 MCP 调用逻辑（Step 2）
- [ ] 改为 DB 读不到则返回降级数据
- [ ] 手动测试：从 DB 删除一条记录，确认走降级路径

### Step 4：中优先级
- [ ] 同样改造 `pre_market.py` 和 `midday.py`
- [ ] 排查 `board_break_analysis` 和 `capital_flow_mkt` 为何未入库

### Step 5：验证
- [ ] 观察 15:05 定时任务执行日志
- [ ] 确认 `daily_market_snapshot` 15:25 前有 14+ 条记录
- [ ] 确认 15:30 `post_market` 报告 0 次 MCP 调用

---

## 五、风险与注意事项

| 风险 | 缓解措施 |
|------|---------|
| 15:05 采集时 MCP 限额已耗尽（若限额从0点起算） | 采集脚本内 MCP 调用失败应写入 failed 日志，但不影响其他数据源 |
| 采集超时（>25min）导致报告拿到空数据 | 看门狗（cron_watchdog）已在监控超时，会补发 |
| `market_data_collector` 本身也有 MCP 调用次数限制 | 每日 16 个工具分 3-4 批执行，约 16 次 MCP 调用，远低于 50 次限额 |
| DB 写入失败导致数据丢失 | `save_snapshot` 有异常捕获，失败写日志不抛错 |

---

## 六、涉及文件清单

| 文件 | 操作 |
|------|------|
| `src/reports/market_data_collector.py` | 修改：补加 market_leaders_pick、增强日志 |
| `scripts/cron_dispatcher.py` | 修改：注册 market_data_collect 任务 |
| `src/reports/modules/post_market.py` | 修改：移除运行时 MCP 调用 |
| `src/reports/modules/pre_market.py` | 修改：移除运行时 MCP 调用 |
| `src/reports/modules/midday.py` | 修改：移除运行时 MCP 调用 |
| `~/.config/systemd/user/ciA_market_collect.timer` | 新增 |
| `~/.config/systemd/user/ciA_market_collect.service` | 新增 |

---

## 七、验收标准

1. **15:05 任务执行后**，daily_market_snapshot 有 14+ 条今日采集记录
2. **15:30 post_market 报告生成时**，日志中 MCP 调用次数 = 0
3. **market_reports 表**仍为空（因为 db.py 是占位实现），不影响报告推送
4. 连续 3 个交易日，`board_break`、`capital_flow_mkt`、`market_leaders` 均成功入库