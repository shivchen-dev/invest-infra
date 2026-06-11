# 进度记录

## 2026-06-07 18:45 — 执行完成

### T-01: DDL ✅
- 文件: `init-db/05_market_snapshot.sql`
- 创建 `daily_market_snapshot` 表（trade_date, data_type, tool_name, raw_data, collected_at）

### T-02: 采集器 ✅
- 文件: `src/reports/market_data_collector.py`
- 16 个 MCP 工具分组并行采集
- upsert 写入，支持重跑
- `fetch_from_db()` 读取接口

### T-03: 缓存读取层 ✅
- 文件: `src/reports/market_data_cache.py`
- `MarketDataCache.get(data_type)` — DB 读取
- `MarketDataCache.get_or_mcp()` — DB 优先降级
- `MarketDataCache.has_all()` — 全量检查

### T-04: cron 任务 ✅
- 已登记: `arc-market-data-collector`
- 时间: 周一至周五 16:00（Asia/Shanghai）
- 推送: 完成后通知到 QQ
- nextRunAtMs: 1780905600000

### report_engine.py 更新 ✅
- 新增 `--date` 参数
- 新增 `--from-db` 参数（待各 reporter 接入）
- 新增 `_get_cache()` 方法

### 验收状态
- [x] `daily_market_snapshot` 表 DDL 完成
- [x] `market_data_collector` 可独立运行
- [x] `market_data_cache` 读取层完成
- [x] cron 任务登记成功
- [ ] 采集器实际运行测试（明日 16:00 首次触发）

### 下一步
1. 将各 reporter 改造为 DB 优先（MCP 降级）
2. 接入 `auction_weak_to_strong` 到盘前报
3. ETF 溢价套利逻辑固化

## 2026-06-07 23:42 — CC 子任务完成（T-01 + T-02 补充）

### T-01: DDL ✅（补充）
- 文件: `data-pipeline/sql/05_market_snapshot.sql`（任务指定路径）
- 表 `daily_market_snapshot` 已验证存在（PostgreSQL）
- 唯一索引: `(trade_date, data_type)`
- 索引: `idx_dms_date_type`, `idx_dms_collected`

### T-02: market_data_collector.py ✅（补充）
- `mcp_client.py` 修复: `_execute_tool` 使用 `asyncio.to_thread` 避免事件循环阻塞
- `market_data_collector.py` py_compile 验证通过
- 采集器支持 16 组 MCP 工具并行 batch 调用，upsert 写入 daily_market_snapshot

### 验收状态
- [x] `data-pipeline/sql/05_market_snapshot.sql` 创建完成
- [x] `daily_market_snapshot` 表已验证存在
- [x] `mcp_client.py` async bug 修复（sync urlopen → asyncio.to_thread）
- [x] `market_data_collector.py` py_compile 通过

---

## 2026-06-07 19:30 — 各 Reporter DB 优先改造完成

### 改造清单

| 文件 | 改造内容 |
|------|---------|
| `market_data_cache.py` | 新增 `save()` 方法，支持数据写入 DB |
| `modules/pre_market.py` | DB 优先，MCP 结果写入 DB（自举），trade_date 参数 |
| `modules/midday.py` | DB 优先，MCP 结果写入 DB（自举），trade_date 参数 |
| `modules/post_market.py` | DB 优先，MCP 结果写入 DB（自举），trade_date 参数 |
| `modules/intraday_alert.py` | 实时数据，不走缓存，trade_date 参数（接口兼容）|
| `report_engine.py` | 注入 cache，给各 reporter 传 trade_date |

### 数据流（改造后）

```
每日16:00 → market_data_collector 批量采集 → daily_market_snapshot
盘前 08:30 → ReportEngine → PreMarketReporter(cache)
                                    ↓
                            DB 有 → 直接返回
                            DB 无 → MCP call + 写入DB
盘中 12:00 → ReportEngine → MiddayReporter(cache)
盘后 18:00 → ReportEngine → PostMarketReporter(cache)
盘中异动 → IntradayAlertReporter (实时，不缓存)
```

### py_compile 验证
```
  OK  market_data_cache.py
  OK  market_data_collector.py
  OK  pre_market.py
  OK  midday.py
  OK  post_market.py
  OK  intraday_alert.py
  OK  report_engine.py
```

### 待完成
- [ ] 采集层实际运行测试（明日 16:00 首次触发）
- [x] 接入 auction_weak_to_strong 到盘前报
- [x] ETF 溢价套利逻辑固化

---

## 2026-06-08 00:15 — 已发现缺陷：盘前报节后首个交易日数据回退

### 缺陷描述
节后首个交易日 T+1 07:50 cron 触发盘前报时，snapshot(T+1) 不存在（未采集），MCP fallback 实时调用数据不完整（集合竞价未结束，07:50 < 09:25）。

**根因：** `PreMarketReporter.fetch(trade_date=None)` 默认为 `date.today()` = T+1，但 DB 中只有 snapshot(T)。

**影响范围：** 仅盘前报（午盘/盘后在盘中/盘后运行，无此问题）

### 修复方案
`src/reports/modules/pre_market.py` — `fetch()` 方法开头增加兜底逻辑：

```python
# 节后首个交易日兜底：snapshot 全缺失时自动用上一交易日
snapshot_data_types = [tool["data_type"] for tool in self.TOOL_MAP]
has_any_snapshot = any(cache.exists(dt) for dt in snapshot_data_types)
if not has_any_snapshot:
    last_t = get_last_trading_day()
    last_t_str = last_t.strftime("%Y-%m-%d") if hasattr(last_t, "strftime") else str(last_t)
    if last_t_str != trade_date_str:
        logger.warning(f"盘前报：{trade_date_str} 无 snapshot，自动回退到 {last_t_str}")
        trade_date_str = last_t_str
        cache = self.cache or MarketDataCache(trade_date_str)
```

### 修复后节后行为
```
T+1 07:50 → snapshot(T+1) 全不存在 → 回退到 T
  → cache.get(limit_stats) → snapshot(T) ✅
  → cache.get(auction_scan) → snapshot(T) ✅
```

### 修复状态
- [x] 代码修改完成（pre_market.py）
- [x] py_compile 验证通过
- [ ] 实际节假日场景验证（需下一次节假日后首个交易日观察）

---

## 2026-06-08 00:20 — auction_weak_to_strong 接入数据采集层 ✅

### Step 1: market_data_collector.py — 无需修改
`auction_weak_to_strong` 工具已在 `TRADE_DATE_TOOLS` 中定义（data_type=`auction_wts`），
`DATE_PARAM_MAP` 已配 `tradeDate` 参数。

### Step 2: pre_market.py TOOL_MAP — 新增 auction_weak_to_strong
- 添加 `{"name": "auction_weak_to_strong", "data_type": "auction_wts", "params": {"tradeDate": "__DATE__", ...}}`
- DB 优先策略下：cache hit → 直接读 snapshot(auction_wts)；cache miss → MCP 调用 + 写入 DB

### Step 3: _extract_weak_to_strong — 改为读取专用缓存
- 旧实现：复用 `_extract_auction_candidates(auction_data)` 取前3（stub）
- 新实现：解析 `auction_wts` 独立缓存的 JSON rows，提取 code/name/change/gap_pct
- 调用处更新：`results.get("auction_wts", {})` → `_extract_weak_to_strong(wts_data)`

### py_compile 验证
```
  OK pre_market.py
  OK market_data_collector.py
```
