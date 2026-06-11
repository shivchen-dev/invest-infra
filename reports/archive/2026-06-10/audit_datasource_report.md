# 汇报模块数据源审计报告

**审计日期**: 2026-06-09  
**审计人**: data-architect (数据架构师)  
**审计范围**: report_engine 模块数据源使用情况  
**代码位置**: `/home/claw/invest-infra/data-pipeline/src/reports/`

---

## 执行摘要

本次审计对汇报模块的数据源架构进行了全面审查，覆盖MCP工具调用、DB缓存策略、数据降级机制、数据源优先级四大维度。

**总体评估**: ⚠️ **中等风险** - 核心数据流设计合理，但存在若干关键问题需要修复。

| 维度 | 评分 | 状态 |
|------|------|------|
| MCP工具调用 | 7/10 | ⚠️ 需改进 |
| DB缓存策略 | 6/10 | 🔴 需修复 |
| 数据降级机制 | 8/10 | ✅ 基本完善 |
| 数据源优先级 | 7/10 | ⚠️ 需调整 |

---

## 一、MCP工具调用审计

### 1.1 MCP工具映射分析

**文件**: `mcp_client.py`  
**工具总数**: 20个

| 类别 | 工具名 | 用途 | 风险等级 |
|------|--------|------|----------|
| 盘前报 | sector_analysis | 板块分析 | 🟢 低 |
| 盘前报 | smart_hotlist | 智能热榜 | 🟢 低 |
| 盘前报 | limit_stats | 涨跌停统计 | 🟢 低 |
| 盘前报 | auction_market_scan | 竞价扫描 | 🟢 低 |
| 盘前报 | official_announcements | 官方公告 | 🟡 中 (未使用) |
| 午盘报 | market_overview | 市场概况 | 🟢 低 |
| 午盘报 | concept_ranking | 概念排名 | 🟢 低 |
| 午盘报 | capital_flow | 资金流向 | 🟢 低 |
| 午盘报 | broken_limit_up | 炸板统计 | 🟢 低 |
| 午盘报 | watchlist_list | 自选股列表 | 🟡 中 (未使用) |
| 盘后报 | hot_sectors | 热门板块 | 🟢 低 |
| 盘后报 | market_leaders_pick | 市场龙头 | 🟡 中 (未使用) |
| 盘后报 | limit_up_ladder | 涨停梯队 | 🟢 低 |
| 盘后报 | board_break_analysis | 断板分析 | 🟢 低 |
| 盘中 | limit_events | 涨停事件 | 🟢 低 |
| 盘中 | limit_down | 跌停池 | 🟢 低 |
| 盘中 | anomaly_detection | 异动检测 | 🟢 低 |
| 采集器 | market_replay_workflow | 市场回放 | 🟡 中 (未使用) |
| 采集器 | auction_weak_to_strong | 弱转强 | 🟢 低 |
| 采集器 | auction_limitup_feedback | 涨停反馈 | 🟢 低 |
| 采集器 | stock_rank | 排行 | 🟢 低 |
| 采集器 | cls_news | 财联社新闻 | 🟡 中 (未使用) |

**发现**: 
- `official_announcements`、`watchlist_list`、`market_leaders_pick`、`market_replay_workflow`、`cls_news` 在MCP_TOOLS中定义但未被任何报告模块直接调用
- 这些工具可能仅被数据采集器使用，建议添加注释说明

### 1.2 MCP客户端实现评估

**优点**:
1. ✅ 限流机制: `rate_limit_ms=100ms` 合理，避免API过载
2. ✅ 重试机制: 指数退避 (1s, 2s, 4s)，最多8秒
3. ✅ 配额保护: 检测到 `DAILY_LIMIT_EXCEEDED` 或 `-32029` 错误时立即降级，不重试
4. ✅ 客户端错误处理: HTTP 4xx 错误不重试

**问题**:

| 严重程度 | 问题描述 | 影响 | 修复建议 |
|----------|----------|------|----------|
| 🔴 高 | `_fallback_result` 返回 `{"error": True, "data": None}`，下游模块未统一处理error字段 | 可能导致报告生成时数据缺失 | 在调用方增加error检查，或降级为有意义的空数据结构 |
| 🟡 中 | `BatchMCPClient.call_batch` 异常捕获过于宽泛，单个工具失败不影响其他但无统计 | 无法追踪批量调用成功率 | 增加成功/失败计数，与MCPClient的stats合并 |
| 🟡 中 | MCP_TOKEN硬编码在源码中 | 安全风险 | 移至环境变量或配置中心 |
| 🟢 低 | `get_batch_mcp_client()` 返回全局单例，但未提供重置方法 | 测试困难 | 增加 `reset_clients()` 函数 |

### 1.3 各模块MCP调用情况

#### 盘前报 (`pre_market.py`)
- **当前策略**: DB优先，cache miss时**不触发MCP**（降级为空字典）
- **MCP调用**: ❌ 无直接调用
- **数据源**: WOA memo (主) + DB snapshot (辅)
- **评估**: ✅ 合理，避免不必要的MCP调用

#### 午盘报 (`midday.py`)
- **当前策略**: DB优先，cache miss时**不触发MCP**（降级为FALLBACK_DATA）
- **MCP调用**: ❌ 无直接调用
- **数据源**: DB snapshot
- **评估**: ✅ 合理

#### 盘后报 (`post_market.py`)
- **当前策略**: DB Only，cache miss时**不触发MCP**（降级为FALLBACK_DATA）
- **MCP调用**: ❌ 无直接调用
- **数据源**: DB snapshot
- **评估**: ✅ 合理

#### 盘中异动 (`intraday_alert.py`)
- **当前策略**: 始终走MCP实时获取，不走DB缓存
- **MCP调用**: ✅ 3个工具批量调用 (limit_events, limit_down, anomaly_detection)
- **数据源**: MCP实时
- **评估**: ✅ 合理，盘中异动需要实时数据

---

## 二、DB缓存策略审计

### 2.1 MarketDataCache实现分析

**文件**: `market_data_cache.py`  
**数据库表**: `daily_market_snapshot`

| 方法 | 功能 | 问题 |
|------|------|------|
| `get(data_type)` | 读取指定类型数据 | ✅ 实现正确，有本地缓存 `_cache` |
| `exists(data_type)` | 检查数据是否存在 | ✅ 实现正确 |
| `save(data_type, tool_name, data)` | 写入DB快照 | ✅ 使用UPSERT (ON CONFLICT) |
| `has_all(data_types)` | 检查所有类型是否已采集 | ⚠️ N+1查询问题 |

### 2.2 缓存命中率分析

**当前实现**:
```python
# pre_market.py - 盘前报
for dt in self.SNAPSHOT_DATA_TYPES:
    data = cache.get(dt)  # 每次调用都查DB（除非在_cache中）
```

**问题**:
1. 🔴 **`has_all()` 方法存在N+1查询问题**: 对每个data_type单独执行SELECT，应改为批量查询
2. 🟡 **本地缓存 `_cache` 未跨实例共享**: 每次创建新的MarketDataCache实例时缓存为空
3. 🟢 **UPSERT策略正确**: `ON CONFLICT (trade_date, data_type)` 避免重复写入

### 2.3 数据写入路径分析

**数据采集器 → DB写入流程**:
```
MCP工具调用 → market_data_collector.py → MarketDataCache.save() → daily_market_snapshot表
```

**报告读取流程**:
```
ReportEngine → Reporter.fetch() → MarketDataCache.get() → daily_market_snapshot表
```

**评估**: ✅ 数据流清晰，采集与读取分离合理

### 2.4 DB连接管理

**文件**: `loader.pg` (外部模块)  
**问题**: 
- 🔴 `market_data_cache.py` 中每次查询都创建/关闭连接 (`with get_conn() as conn:`)
- 高频调用时可能产生连接开销
- **建议**: 考虑使用连接池或长连接

---

## 三、数据降级机制审计

### 3.1 各模块降级策略对比

| 模块 | DB Miss降级 | MCP调用 | 降级数据结构完整性 |
|------|-------------|---------|-------------------|
| pre_market.py | 空字典 `{}` | ❌ 不触发 | ⚠️ 部分字段可能缺失 |
| midday.py | FALLBACK_DATA | ❌ 不触发 | ✅ 完整 |
| post_market.py | FALLBACK_DATA | ❌ 不触发 | ✅ 完整 |
| intraday_alert.py | N/A (始终MCP) | ✅ 始终调用 | N/A |

### 3.2 降级数据完整性评估

#### 午盘报 (`midday.py`) - ✅ 优秀
```python
FALLBACK_DATA = {
    "market_overview": {"content": [{"text": "{}"}]},
    "concept_ranking": {"content": [{"text": "{\"rows\": []}"}]},
    ...
}
```
- 所有必需字段都有默认值
- JSON字符串格式与正常数据一致，解析器不会崩溃

#### 盘后报 (`post_market.py`) - ✅ 优秀
```python
FALLBACK_DATA = {
    "limit_stats": {"sealedLimitUp": 0, "sealedLimitDown": 0, ...},
    "hot_sectors": {"rows": [{"name": "暂无数据", ...}], ...},
    ...
}
```
- 结构完整，覆盖所有下游formatter的字段访问
- 使用"暂无数据"、"N/A"等明确标识

#### 盘前报 (`pre_market.py`) - ⚠️ 需改进
```python
# Step 2: DB未命中时返回空字典
for dt in self.SNAPSHOT_DATA_TYPES:
    data = cache.get(dt)
    if data is not None:
        results[dt] = data
    else:
        results[dt] = {}  # 空字典，下游可能访问不存在的键
```

**问题**: 
- `_extract_sentiment()`、`_extract_sectors()` 等方法对空字典有防御性处理（try-except）
- 但 `_extract_auction_candidates()` 中 `auction_data.get("content", [{}])[0].get("text", "")` 在空字典时会崩溃

**修复建议**: 
- 为盘前报也定义FALLBACK_DATA，与午盘/盘后报保持一致

### 3.3 WOA Memo降级

**盘前报的memo数据源**:
```python
memo_data = self.fetch_memo(trade_date_str)
if memo_data:
    # 使用memo数据
else:
    # memo_data为空，后续字段使用默认值
```

**评估**: ✅ 合理，memo查询失败时返回空字典，下游有默认值处理

---

## 四、数据源优先级审计

### 4.1 各模块数据源优先级

| 模块 | 主数据源 | 备用数据源 | MCP角色 | 优先级正确性 |
|------|----------|------------|---------|-------------|
| pre_market.py | WOA memo (DB) | DB snapshot | 不触发 | ✅ 正确 |
| midday.py | DB snapshot | FALLBACK_DATA | 不触发 | ✅ 正确 |
| post_market.py | DB snapshot | FALLBACK_DATA | 不触发 | ✅ 正确 |
| intraday_alert.py | MCP实时 | N/A | 唯一数据源 | ✅ 正确 |

### 4.2 盘前报数据流详细分析

**数据源层次**:
```
1. WOA memo (investment_memos表) - 主数据源
   ├── morning_collect → market_overview
   ├── factor_calculation → factors
   ├── risk_monitoring → risks
   └── daily_report → woa_summary, scenarios, etf_signals

2. DB快照 (daily_market_snapshot表) - 辅助数据源
   ├── sector_analysis
   ├── smart_hotlist
   ├── limit_stats
   ├── auction_scan
   ├── auction_wts
   └── hsgt

3. 旧版WOA数据 (index_quotes, etf_alpha_signals, etf_quotes) - 补充数据源
```

**评估**: ✅ 优先级设计合理，WOA memo作为主数据源提供AI分析结果，DB快照提供结构化市场数据

### 4.3 节后首个交易日兜底逻辑

**代码位置**: `pre_market.py` Line 303-314
```python
# 节后首个交易日兜底：snapshot全缺失时自动用上一交易日
has_any_snapshot = any(cache.exists(dt) for dt in self.SNAPSHOT_DATA_TYPES)
if not has_any_snapshot:
    last_t = get_last_trading_day()
    # 使用上一交易日数据
```

**评估**: ✅ 合理的容错机制，避免休市后首个交易日数据完全缺失

---

## 五、db.py占位实现问题

### 5.1 问题分析

**文件**: `db.py`  
**状态**: 全部TODO占位实现

| 方法 | 当前行为 | 影响 |
|------|----------|------|
| `save_report()` | 返回固定ID 1，不写入DB | ⚠️ 报告未持久化 |
| `get_report()` | 返回None | ⚠️ 无法读取历史报告 |
| `save_alert()` | 返回固定ID 1 | ⚠️ 告警未持久化 |
| `get_recent_alerts()` | 返回空列表 | ⚠️ 无法查询历史告警 |
| `is_duplicate_alert()` | 始终返回False | 🔴 **重复告警风险** |
| `update_subscription()` | 始终返回True | ⚠️ 订阅状态未持久化 |

### 5.2 影响评估

**严重程度**: 🔴 **高**

`ReportEngine.run()` 中的流程:
```python
# 3. 保存到数据库
self.db.save_report(self.report_type, self.trade_date, self.data)
```

当前实现中，报告生成成功后调用 `save_report()` 但实际未保存。这意味着：
1. 无法查询历史报告
2. 无法实现报告版本对比
3. 系统重启后所有报告丢失

**修复建议**: 
- 接入真实PostgreSQL数据库
- 创建 `reports` 表存储生成的报告
- 实现完整的CRUD操作

---

## 六、MCP工具调用策略专业评估

### 6.1 限流策略

**当前配置**: `rate_limit_ms=100ms`  
**评估**: ✅ 合理，每秒10次调用符合大多数API限制

**建议**: 
- 考虑根据MCP服务实际QPS限制动态调整
- 增加全局并发控制（semaphore）

### 6.2 重试策略

**当前配置**: `max_retries=3`，指数退避 (1s, 2s, 4s)  
**评估**: ✅ 合理

**问题**: 
- 🔴 `_fallback_result` 在配额耗尽时直接返回，不触发重试（正确）
- 🟡 但重试期间可能消耗配额（如果MCP服务在重试后恢复）

### 6.3 降级策略

**当前实现**:
```python
def _fallback_result(self, tool_name: str) -> Dict[str, Any]:
    return {
        "error": True,
        "tool": tool_name,
        "message": "数据暂不可用",
        "data": None
    }
```

**评估**: ⚠️ 降级结果结构不完整，下游需要额外处理

**建议**: 
- 根据工具类型返回有意义的降级数据（如空列表、零值）
- 或在调用方统一处理error字段

---

## 七、问题汇总与修复建议

### 7.1 问题严重程度分布

| 严重程度 | 数量 | 问题 |
|----------|------|------|
| 🔴 高 | 3 | db.py占位实现、pre_market降级不完整、MCP_TOKEN硬编码 |
| 🟡 中 | 4 | BatchMCPClient统计缺失、DB连接管理、has_all N+1查询、未使用工具映射 |
| 🟢 低 | 2 | MCPClient单例测试困难、本地缓存跨实例问题 |

### 7.2 修复优先级

#### P0 - 立即修复
1. **db.py接入真实数据库** - 报告持久化是核心功能
2. **pre_market.py补充FALLBACK_DATA** - 避免cache miss时崩溃

#### P1 - 近期修复
3. **MCP_TOKEN移至环境变量** - 安全风险
4. **BatchMCPClient增加统计** - 可观测性
5. **has_all()改为批量查询** - 性能优化

#### P2 - 计划修复
6. **DB连接池优化** - 高频调用场景
7. **清理未使用工具映射** - 代码整洁
8. **MCPClient增加reset方法** - 测试友好

---

## 八、数据流架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    ReportEngine (主入口)                      │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   pre_market      midday/post    intraday_alert
   (DB+Memo)       market (DB)     (MCP实时)
         │               │               │
         ▼               ▼               ▼
   ┌──────────┐    ┌──────────┐    ┌──────────┐
   │WOA Memo  │    │ DB Cache │    │ MCP Client│
   │(主数据源) │    │(快照表)  │    │ (实时API) │
   └──────────┘    └──────────┘    └──────────┘
         │               │               │
         ▼               ▼               ▼
   ┌──────────────────────────────────────────┐
   │        MarketDataCache (缓存层)            │
   │  - get() / save() / exists()              │
   │  - daily_market_snapshot表                 │
   └──────────────────────────────────────────┘
                         │
                         ▼
               ┌─────────────────┐
               │ PostgreSQL DB   │
               │ - investment_   │
               │   memos         │
               │ - daily_market_ │
               │   snapshot      │
               │ - index_quotes  │
               │ - etf_*         │
               └─────────────────┘
```

---

## 九、结论

汇报模块的数据源架构设计整体合理，各模块根据数据时效性要求选择了合适的数据源：

1. **盘前/午盘/盘后报**: DB优先策略正确，避免不必要的MCP调用
2. **盘中异动**: MCP实时获取符合业务需求
3. **降级机制**: 午盘/盘后报完善，盘前报需补充

**主要风险点**:
- db.py的占位实现导致报告无法持久化（P0）
- 盘前报cache miss时降级不完整（P0）
- MCP_TOKEN硬编码存在安全风险（P1）

**建议优先修复P0问题，确保系统核心功能正常运行。**

---

*审计完成时间: 2026-06-09*  
*审计人: data-architect*
