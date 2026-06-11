# 投研系统数据采集层 — 任务计划

## 目标
每日 16:00 一次性 MCP 批量采集 → PostgreSQL 缓存 → 各报告从 DB 读

## 数据流变更

**Before:**
```
MCP工具 → report_engine（按需调用，每次独立）→ QQ推送
```
每次报告生成都单独调用 MCP，无缓存。

**After:**
```
每日16:00 → market_data_collector（一次批量采集）→ daily_market_snapshot 表
                                                        ↓
                           ┌─────────────────────────────┼─────────────────────────────┐
                    盘前报 ← DB读              午盘报 ← DB读              盘后报 ← DB读
```

## 工作步骤

### T-01: DDL — 新增数据采集表
**文件:** `data-pipeline/sql/05_market_snapshot.sql`

创建 `daily_market_snapshot` 表：
```sql
CREATE TABLE daily_market_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    trade_date      DATE NOT NULL,
    data_type       VARCHAR(50) NOT NULL,   -- limit_stats / auction / capital_flow / ladder 等
    tool_name       VARCHAR(100) NOT NULL,  -- 对应的 MCP 工具名
    raw_data        JSONB NOT NULL,
    collected_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (trade_date, data_type)
);
CREATE INDEX idx_dms_date_type ON daily_market_snapshot(trade_date, data_type);
```

### T-02: market_data_collector.py — 采集器
**文件:** `data-pipeline/src/reports/market_data_collector.py`

- 16:00 执行（收盘后）
- 并行 batch 调用所有 MCP 工具
- 写入 `daily_market_snapshot` 表
- 支持重跑（upsert）

**MCP 工具分组：**
```
Group-A (大盘/复盘):
  - market_overview
  - limit_stats
  - market_replay_workflow

Group-B (涨停/板块):
  - hot_sectors
  - limit_up_ladder
  - board_break_analysis
  - broken_limit_up

Group-C (资金):
  - capital_flow (market)
  - capital_flow (sector, top5)
  - stock_rank (volume / turnover)

Group-D (竞价):
  - auction_market_scan
  - auction_weak_to_strong
  - auction_limitup_feedback

Group-E (龙虎/其他):
  - dragon_tiger
  - cls_news (今日重要)
```

### T-03: report_engine.py — 改造为 DB 优先
**文件:** `data-pipeline/src/reports/report_engine.py`

- 新增 `fetch_from_db(data_type)` 方法
- 报告生成时优先从 DB 读
- DB 无数据时降级走 MCP（容错）
- MCP 结果同时写入 DB（自举）

### T-04: cron 任务登记
**文件:** `data-pipeline/src/pipeline/scheduler_jobs.sql`

```sql
INSERT INTO scheduler_jobs (job_name, cron_expr, handler, enabled)
VALUES (
  'market_data_collector',
  '0 16 * * 1-5',  -- 周一至周五 16:00
  'reports.market_data_collector.run',
  true
);
```

## 验收标准
- [ ] `daily_market_snapshot` 表创建成功
- [ ] `market_data_collector` 可独立运行，23个工具全部采集入库
- [ ] 盘后报从 DB 读取，不走 MCP
- [ ] cron 任务登记成功

## 工作量
3h（含测试）

## 阻塞项
- PostgreSQL 连接配置（config.py 已配置）
- MCP 日调用限额确认（待确认 25次/日是否超限）