# 汇报模块架构审计报告

**审计对象**: `invest-infra/data-pipeline/src/reports/`  
**审计人**: system-architect (系统架构分析师)  
**审计日期**: 2026-06-09  
**版本**: v1.0  

---

## 一、模块概览

### 1.1 文件清单与职责

| 文件 | 行数 | 职责 | 复杂度 |
|------|------|------|--------|
| `report_engine.py` | 180 | 主入口，编排报告生成流程 | ⭐⭐ |
| `modules/pre_market.py` | 1105 | 盘前报数据获取与提取 | ⭐⭐⭐⭐⭐ |
| `modules/midday.py` | 232 | 午盘报数据获取与提取 | ⭐⭐⭐ |
| `modules/post_market.py` | 329 | 盘后报数据获取与提取 | ⭐⭐⭐ |
| `modules/intraday_alert.py` | 121 | 盘中异动实时数据获取 | ⭐⭐ |
| `formatters.py` | 950 | 四大报告类型的格式化渲染 | ⭐⭐⭐⭐ |
| `db.py` | 147 | 数据库操作（占位实现） | ⭐ |
| `mcp_client.py` | 237 | MCP 客户端封装（限流/重试） | ⭐⭐⭐ |
| `market_data_cache.py` | 160 | DB 缓存读取层 | ⭐⭐ |
| `trading_day.py` | 139 | 交易日判断与交易阶段 | ⭐⭐ |
| `qq_push.py` | 384 | QQ 推送模块 | ⭐⭐⭐ |
| `market_data_collector.py` | 356 | 每日数据采集器 | ⭐⭐⭐ |

### 1.2 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        report_engine.py                             │
│                     (主入口 / Orchestrator)                         │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ pre_     │  │ midday   │  │ post_    │  │ intraday_alert   │   │
│  │ market   │  │          │  │ market   │  │                  │   │
│  │ Reporter │  │ Reporter │  │ Reporter │  │ Reporter         │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘   │
│       │             │             │                  │              │
│       ▼             ▼             ▼                  ▼              │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              MarketDataCache (DB Cache Layer)            │      │
│  │         daily_market_snapshot 表读取层                    │      │
│  └────────────────────────────┬─────────────────────────────┘      │
│                               │                                    │
│              ┌────────────────┼────────────────┐                   │
│              ▼                ▼                ▼                   │
│     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│     │ PostgreSQL   │  │ MCP Client   │  │ loader.pg    │         │
│     │ (snapshot)   │  │ (实时数据)    │  │ (memo/etf)   │         │
│     └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              ReportFormatter (格式化层)                   │      │
│  │  PreMarket | Intraday | PostMarket | IntradayAlert       │      │
│  └────────────────────────────┬─────────────────────────────┘      │
│                               │                                    │
│                       ┌───────▼───────┐                           │
│                       │   QQ Push     │                           │
│                       │   (openclaw)  │                           │
│                       └───────────────┘                           │
└─────────────────────────────────────────────────────────────────────┘

外部依赖:
  loader.pg → PostgreSQL (investment_memos, index_quotes, etf_alpha_signals, etf_quotes, etc.)
  MCP API   → stock.quicktiny.cn/api/mcp-stream
```

### 1.3 数据流图

```
数据采集层                    报告引擎层                   输出层
─────────────               ─────────────               ───────

market_data_collector.py     report_engine.py            QQ Push
    │                            │                          ▲
    ▼                            │                          │
MCP Batch Call ──→ daily_market_snapshot (DB)              │
    │                            │                          │
    │                     ┌──────┴──────┐                   │
    │                     │  Cache Miss │                   │
    │                     │  → Fallback │                   │
    │                     └──────┬──────┘                   │
    │                            │                          │
    ▼                            ▼                          │
PreMarketReporter              Formatters                  │
MiddayReporter     ──────────→  split_messages() ──────────→│
PostMarketReporter             save_report(DB)              │
IntradayAlertReporter          (stub)                       │
```

---

## 二、模块划分评估

### 2.1 ✅ 优点

| 维度 | 评价 | 说明 |
|------|------|------|
| **职责分离** | 良好 | 数据获取（Reporter）与格式化（Formatter）分层清晰 |
| **报告类型隔离** | 良好 | 四种报告类型各自独立模块，互不干扰 |
| **缓存层独立** | 良好 | MarketDataCache 作为独立抽象层，解耦了 DB 查询逻辑 |
| **推送层独立** | 良好 | QQ Push 模块独立封装，支持降级策略 |

### 2.2 ⚠️ 问题：PreMarketReporter 严重膨胀

**严重程度**: P1（高）

`pre_market.py` 达 **1105 行**，远超合理范围。当前职责包括：
- WOA memo 数据解析（6 个静态解析方法）
- DB 旧版 WOA 数据查询（3 张表 SQL）
- 数据提取逻辑（8+ 个 extract 方法）
- 业务推导逻辑（operation_ref, today_attention, today_judgment 等）

**违反原则**: 单一职责原则 (SRP) — 一个类承担了数据获取、数据解析、业务推导三重职责。

**建议**:
1. 将 `_parse_*` 系列方法提取为独立的 `MemoParser` 工具类
2. 将 `_extract_*` 系列方法提取为独立的 `DataExtractor` 类
3. 将 `_build_*` 系列业务推导方法保留在 Reporter 中，但可进一步拆分

### 2.3 ⚠️ 问题：Formatters.py 同样膨胀

**严重程度**: P1（高）

`formatters.py` 达 **950+ 行**，包含四个 Formatter 类。虽然比 Reporter 稍好，但仍建议拆分：
- `PreMarketFormatter` (~180 行) — 可接受
- `IntradayFormatter` (~200 行) — 可接受
- `PostMarketFormatter` (~350 行) — **偏大**
- `IntradayAlertFormatter` (~50 行) — 合理

**建议**: 将 PostMarketFormatter 拆分为多个私有方法或提取为 `_format_*` 子模块。

### 2.4 ⚠️ 问题：缺少抽象基类

**严重程度**: P2（中）

四个 Reporter 类没有共同的抽象基类，导致：
- `report_engine.py` 使用字典映射手动分发 (`handlers.get(self.report_type)`)
- 无法通过多态统一调用
- 新增报告类型需修改 ReportEngine 代码

**建议**: 定义 `BaseReporter` 抽象基类，包含 `async def fetch(trade_date: str) -> Dict` 接口。

---

## 三、依赖关系分析

### 3.1 依赖图

```
report_engine.py
├── reports.trading_day (is_trading_day, get_trading_phase)
├── reports.db (get_db) — ⚠️ 占位实现
├── reports.formatters (format_report)
├── reports.mcp_client (get_batch_mcp_client)
├── reports.qq_push (send_to_qq)
├── reports.market_data_cache (MarketDataCache)
└── modules.{pre_market, midday, post_market, intraday_alert}
    └── reports.market_data_cache (依赖同上)

modules/pre_market.py
├── reports.market_data_cache
├── loader.pg (get_conn) — ⚠️ 直接依赖外部模块
└── reports.trading_day (get_last_trading_day)

modules/post_market.py
├── reports.market_data_cache
├── loader.pg (get_conn) — ⚠️ 直接依赖外部模块

market_data_cache.py
└── loader.pg (get_conn) — ⚠️ 直接依赖外部模块

mcp_client.py
└── (无内部依赖，仅标准库 + urllib)

qq_push.py
├── httpx
└── subprocess (openclaw CLI)
```

### 3.2 ⚠️ 问题：loader.pg 直接耦合

**严重程度**: P1（高）

`pre_market.py`、`post_market.py`、`market_data_cache.py` 均直接 `from loader.pg import get_conn`，导致：
- 汇报模块与数据加载模块强耦合
- 无法独立测试汇报模块（需要 PostgreSQL 连接）
- 违反依赖倒置原则

**建议**:
1. 定义 `DataSource` 抽象接口
2. 通过依赖注入传入数据源实例
3. 或使用工厂模式在运行时决定使用哪种数据源

### 3.3 ⚠️ 问题：sys.path.insert 反模式

**严重程度**: P2（中）

`report_engine.py` 第 21 行:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
```

这种动态修改 `sys.path` 的方式：
- 破坏模块导入的可预测性
- 在不同运行环境（CLI vs cron vs import）下行为不一致
- 可能导致命名冲突

**建议**: 使用 Python 包结构 + `python -m reports.report_engine` 方式运行。

### 3.4 ⚠️ 问题：全局单例过多

**严重程度**: P2（中）

以下模块使用全局单例模式:
- `db.py`: `_db` 全局实例
- `mcp_client.py`: `_mcp_client`, `_batch_client` 全局实例
- `qq_push.py`: `_token_manager` 全局实例

虽然简化了调用，但：
- 难以进行单元测试（无法 mock）
- 多线程环境下可能存在竞态条件
- 配置变更需要重启进程

**建议**: 使用依赖注入容器或配置类管理全局状态。

### 3.5 ✅ 优点：MCP 客户端封装良好

`mcp_client.py` 提供了良好的抽象:
- 限流机制 (`_rate_limit`)
- 重试 + 指数退避 (`_exponential_backoff`)
- 配额耗尽快速降级（不重试）
- 批量调用支持 (`BatchMCPClient`)

---

## 四、可扩展性评估

### 4.1 新增报告类型成本

**当前成本**: 高

新增一种报告类型需要修改以下位置:
1. `report_engine.py`: 添加 handler 映射 + `_fetch_xxx` 方法
2. `formatters.py`: 添加新 Formatter 类 + `get_formatter()` 映射
3. `modules/`: 创建新 Reporter 模块

**违反原则**: 开闭原则 (OCP) — 对扩展不开放，对修改封闭。

**建议架构**:
```python
# 使用策略模式 + 注册表
class ReporterRegistry:
    _registry = {}
    
    @classmethod
    def register(cls, report_type: str):
        def decorator(reporter_class):
            cls._registry[report_type] = reporter_class
            return reporter_class
        return decorator
    
    @classmethod
    def get(cls, report_type: str) -> BaseReporter:
        return cls._registry[report_type]()

# 使用方式
@ReporterRegistry.register("custom_report")
class CustomReporter(BaseReporter):
    async def fetch(self, trade_date: str) -> Dict:
        ...
```

### 4.2 新增数据源成本

**当前成本**: 中

新增一种 MCP 工具需要修改:
1. `mcp_client.py`: `MCP_TOOLS` 映射
2. `market_data_cache.py`: `DATA_TYPE_MAP` 映射
3. `market_data_collector.py`: `TRADE_DATE_TOOLS` 列表
4. 各 Reporter 模块: 添加数据获取逻辑

**建议**: 将工具配置外置为 YAML/JSON 配置文件，减少代码修改。

### 4.3 新增推送渠道成本

**当前成本**: 中

QQ Push 模块已支持双通道降级（openclaw CLI → QQ API），扩展其他渠道需要:
1. 在 `qq_push.py` 添加新 Pusher 类
2. 修改 `send_to_qq()` 统一入口

**建议**: 定义 `PushChannel` 抽象接口，使用策略模式。

---

## 五、与其他模块的集成方式

### 5.1 与数据采集器 (`market_data_collector.py`) 的集成

| 维度 | 评价 |
|------|------|
| **数据共享** | ✅ 良好 — 通过 `daily_market_snapshot` 表共享数据 |
| **耦合度** | ⚠️ 中 — Cache 层直接查询 DB，与 Collector 写入同一表 |
| **时序依赖** | ✅ 合理 — Collector 16:00 采集 → Reporter 次日读取 |

### 5.2 与 `loader.pg` 的集成

| 维度 | 评价 |
|------|------|
| **耦合度** | ❌ 高 — 汇报模块直接依赖 loader.pg 的 `get_conn()` |
| **表依赖** | ⚠️ 隐式 — 依赖 `investment_memos`, `index_quotes`, `etf_alpha_signals` 等表结构 |
| **可测试性** | ❌ 差 — 无法脱离 PostgreSQL 独立运行/测试 |

### 5.3 与 MCP API 的集成

| 维度 | 评价 |
|------|------|
| **封装性** | ✅ 良好 — MCP 调用全部通过 `mcp_client.py` 统一出口 |
| **降级策略** | ✅ 良好 — 配额耗尽/错误时返回 fallback 结果 |
| **安全性** | ❌ 差 — Token 硬编码在源码中（见问题 6.1） |

### 5.4 与 QQ Push 的集成

| 维度 | 评价 |
|------|------|
| **封装性** | ✅ 良好 — 统一 `send_to_qq()` 入口 |
| **降级策略** | ✅ 良好 — openclaw CLI → QQ API 双通道 |
| **错误隔离** | ✅ 良好 — ReportEngine 中 QQ 推送失败不阻塞报告保存 |

---

## 六、数据库表设计评估

### 6.1 daily_market_snapshot 表（推断结构）

根据代码反推的表结构:

```sql
CREATE TABLE daily_market_snapshot (
    trade_date    DATE NOT NULL,
    data_type     VARCHAR(64) NOT NULL,
    tool_name     VARCHAR(128),
    raw_data      JSONB NOT NULL,
    collected_at  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (trade_date, data_type)  -- ON CONFLICT 暗示此复合主键
);

-- 推断的索引需求:
CREATE INDEX idx_snapshot_trade_date ON daily_market_snapshot(trade_date);
```

**评价**:
| 维度 | 评分 | 说明 |
|------|------|------|
| **范式化** | ⭐⭐⭐ | JSONB 存储非结构化数据，灵活但查询困难 |
| **扩展性** | ⭐⭐⭐⭐ | 新增数据类型无需改表结构 |
| **查询性能** | ⭐⭐ | 缺少 `collected_at` 索引，无法高效查找最新快照 |
| **数据完整性** | ⭐⭐ | JSONB 无 schema 校验，可能存储不一致数据 |

### 6.2 market_reports 表（db.py 中定义但未实现）

```python
# db.py 中的接口定义:
def save_report(self, report_type: str, trade_date: date, content: Dict) -> int
def get_report(self, report_type: str, trade_date: date) -> Optional[Dict]
```

**问题**: 
- `db.py` 是 **占位实现**（所有方法返回固定值）
- 实际报告未持久化到数据库
- 无法追溯历史报告内容

### 6.3 intraday_alerts 表（db.py 中定义但未实现）

```python
# db.py 中的接口定义:
def save_alert(self, alert_type: str, stock_code: str, stock_name: str, 
               detail: Dict, trade_date: date) -> int
def get_recent_alerts(self, trade_date: date, limit: int = 50) -> List[Dict]
def is_duplicate_alert(self, stock_code: str, alert_type: str, 
                       alert_time: datetime, window_minutes: int = 30) -> bool
```

**问题**:
- 占位实现，去重逻辑未实现（始终返回 `False`）
- 盘中异动数据仅通过 MCP 实时获取，无持久化

### 6.4 ⚠️ 缺失的表设计

以下功能在代码中有调用但未见对应表:
| 功能 | 涉及代码 | 缺失表 |
|------|----------|--------|
| WOA memo 查询 | `pre_market.py` → `loader.pg` | `investment_memos` (外部依赖) |
| ETF 套利信号 | `post_market.py` → `etf_alpha_signals` | `etf_alpha_signals` (外部依赖) |
| 指数行情 | `pre_market.py` → `index_quotes` | `index_quotes` (外部依赖) |

**建议**: 在架构文档中明确标注汇报模块的外部表依赖，建立数据血缘关系。

---

## 七、架构层面问题与风险汇总

### P0（致命）— 必须修复

| # | 问题 | 影响 | 修复建议 |
|---|------|------|----------|
| 1 | **db.py 为占位实现** | 报告无法持久化，失败后无法追溯 | 实现完整的 Database 类，对接 PostgreSQL |
| 2 | **MCP Token 硬编码** | `mcp_client.py:18` — Token 泄露风险 | 移至环境变量或密钥管理服务 |

### P1（高）— 应尽快修复

| # | 问题 | 影响 | 修复建议 |
|---|------|------|----------|
| 3 | **PreMarketReporter 膨胀 (1105行)** | 难以维护、测试和复用 | 拆分为 Parser/Extractor/Reporter 三层 |
| 4 | **loader.pg 直接耦合** | 无法独立测试汇报模块 | 定义 DataSource 接口，依赖注入 |
| 5 | **交易日判断不完整** | `trading_day.py:36` — 仅判断周末，未处理节假日 | 接入节假日 API 或本地日历 |

### P2（中）— 建议改进

| # | 问题 | 影响 | 修复建议 |
|---|------|------|----------|
| 6 | **缺少抽象基类** | 新增报告类型需修改多处代码 | 定义 BaseReporter/BaseFormatter 接口 |
| 7 | **sys.path.insert 反模式** | 模块导入不可预测 | 使用 Python 包 + `python -m` 运行 |
| 8 | **全局单例过多** | 难以测试，多线程风险 | 使用 DI 容器或配置类 |
| 9 | **Formatters.py 膨胀 (950行)** | 维护困难 | PostMarketFormatter 进一步拆分 |

### P3（低）— 可后续优化

| # | 问题 | 影响 | 修复建议 |
|---|------|------|----------|
| 10 | **MCP_TOOLS / DATA_TYPE_MAP 重复定义** | 维护两份映射，易不一致 | 统一为单一配置源 |
| 11 | **硬编码文件路径** | `report_engine.py:36` — 日志路径硬编码 | 使用配置文件管理路径 |
| 12 | **无健康检查端点** | 无法监控模块运行状态 | 添加 `/health` 或 CLI 检查命令 |

---

## 八、推荐架构演进路线

### Phase 1: 基础加固（P0+P1）
1. 实现 `db.py` 完整功能，支持报告持久化
2. MCP Token 移至环境变量
3. 接入节假日 API 完善交易日判断
4. 拆分 PreMarketReporter 为子模块

### Phase 2: 接口抽象（P2）
5. 定义 `BaseReporter` / `BaseFormatter` 抽象基类
6. 实现 ReporterRegistry 注册表模式
7. 定义 DataSource 接口，解耦 loader.pg 依赖
8. 消除 sys.path.insert，改用包结构

### Phase 3: 可观测性（P3）
9. 统一配置管理（YAML/环境变量）
10. 添加健康检查和指标收集
11. MCP_TOOLS / DATA_TYPE_MAP 统一配置源
12. 补充单元测试覆盖核心逻辑

---

## 九、总结

汇报模块整体架构 **分层清晰**（采集→缓存→引擎→格式化→推送），数据流设计合理。主要问题集中在：

1. **代码规模失控**: PreMarketReporter (1105行) 和 Formatters.py (950行) 严重膨胀
2. **基础设施未完善**: db.py 占位实现、交易日判断不完整
3. **安全漏洞**: MCP Token 硬编码
4. **扩展性不足**: 新增报告类型需修改多处代码

建议优先完成 Phase 1 的基础加固，再逐步推进接口抽象和可观测性建设。

---

*报告结束*
