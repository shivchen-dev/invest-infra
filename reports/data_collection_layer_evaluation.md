# 投研数据采集层全面评估报告

**评估人**: data-arch-eng (资深数据工程师)  
**评估日期**: 2026-06-03  
**评估范围**: `/home/claw/invest-infra/data-pipeline/`  
**代码版本**: Phase 1 数据采集管线  

---

## 一、执行摘要

当前数据采集层已构建了 **Bronze → Silver** 双层架构，覆盖了 A 股股票、ETF、指数、财报、新闻等核心数据类型，接入了 akshare（免费）、次方量化（付费）、RssCast MCP（第三方）三大数据源。整体架构方向正确，但在**数据源覆盖度、错误处理机制、可观测性、并发性能**等方面存在明显缺口。

| 评估维度 | 评分 (1-5) | 状态 |
|---------|:----------:|------|
| 数据源覆盖度 | 3 | ⚠️ 中等 — 缺少宏观/行业/另类数据 |
| 数据类型完整性 | 3 | ⚠️ 中等 — 缺少高频/Level2/资金流向明细 |
| 架构设计质量 | 4 | ✅ 良好 — collector/loader 分离清晰 |
| 数据质量保障 | 3 | ⚠️ 中等 — NaN 处理有但缺乏一致性校验 |
| 性能与效率 | 3 | ⚠️ 中等 — 串行采集，无并发控制 |
| 可靠性与可观测性 | 2 | ❌ 不足 — 缺少重试、审计日志未使用 |

---

## 二、数据源覆盖度

### 2.1 已接入数据源

| 数据源 | 类型 | 认证方式 | 覆盖范围 | 状态 |
|--------|------|---------|---------|------|
| **akshare** | 免费开源 | 无需认证 | A股全量股票、ETF、指数、财报、新闻、研报 | ✅ 核心数据源 |
| **次方量化 (cifang)** | 付费 API | `CIFANG_TOKEN` 环境变量 | ETF 实时行情 + 历史K线（等比复权） | ✅ 补充数据源 |
| **RssCast MCP** | 第三方服务 | `RSSCAST_TOKEN` 环境变量 | 股票/指数实时行情 + 历史K线 | ✅ 备用数据源 |

### 2.2 缺失数据源

| 缺失类别 | 优先级 | 说明 | 建议方案 |
|---------|:------:|------|---------|
| **宏观经济数据** | 🔴 P0 | GDP、CPI、PMI、利率、M2等宏观指标完全缺失，无法支撑基本面分析 | 接入国家统计局 API / Wind / Tushare |
| **行业/板块数据** | 🔴 P0 | 申万行业分类、板块指数、行业轮动数据缺失 | 接入 akshare `stock_board_industry_name_em` |
| **资金流向明细** | 🟡 P1 | 仅有 ETF 主力资金净流入汇总，缺少个股/北向资金/融资融券明细 | 接入 akshare `stock_individual_fund_flow` / `stock_hsgt_north_net_flow_in_em` |
| **龙虎榜数据** | 🟡 P1 | 机构席位、游资动向等另类数据缺失 | 接入 akshare `stock_lhb_detail_em` |
| **停复牌信息** | 🟡 P1 | 无停复牌日历，无法处理停牌期间的数据采集逻辑 | 接入 akshare `stock_tfp_em` |
| **分红送配** | 🟡 P1 | 无除权除息日数据，复权因子依赖 akshare 内部计算 | 接入 akshare `stock_history_dividend` |
| **港股/美股** | 🟢 P2 | 仅覆盖 A 股和场内 ETF，未覆盖港股通/美股标的 | 接入 akshare `stock_hk_*` / `stock_us_*` |

### 2.3 数据源冗余分析

- **akshare 与 RssCast 存在功能重叠**：两者均提供股票/指数实时行情和历史K线
- **次方量化作为 ETF 专用补充源**定位合理，其等比复权质量优于 akshare
- **建议**：建立数据源优先级策略（主源 → 备源），避免重复采集

---

## 三、数据类型完整性

### 3.1 已覆盖数据类型

| 数据类型 | 采集器 | 存储位置 | 频率 | 状态 |
|---------|--------|---------|------|------|
| **公司主数据** | `companies.py` | PG `companies` 表 | 日频全量同步 | ✅ |
| **股票日行情** | `quotes.py` (akshare) | PG `daily_quotes` + MinIO Bronze | 日频 | ✅ |
| **ETF 实时行情** | `etf.py` (akshare) / `cifang.py` | PG `etf_quotes` + MinIO Bronze | 日内刷新 | ✅ |
| **ETF 历史K线** | `etf.py` (akshare) / `cifang.py` | PG `etf_quotes` + MinIO Bronze | 日频增量 | ✅ |
| **财报摘要** | `financial.py` | PG `financial_reports` + MinIO Bronze | 季频 | ✅ |
| **财务指标** | `financial.py` (indicator) | PG `financial_reports` (回填) | 季频 | ✅ |
| **个股新闻** | `news.py` | PG `news_articles` + MinIO Bronze | 日频 | ✅ |
| **研报列表** | `research_report.py` | PG `research_reports` (表已建，采集未接入 pipeline) | 按需 | ⚠️ 部分 |

### 3.2 缺失数据类型

| 缺失类型 | 优先级 | 说明 | 建议方案 |
|---------|:------:|------|---------|
| **指数行情** | 🔴 P0 | RssCast 已实现 `fetch_index_quotes_normalized`，但 akshare 主 pipeline 未覆盖 | 在 `run_all()` 中增加指数采集步骤 |
| **ETF Alpha 信号** | 🟡 P1 | 表结构已建 (`alpha_signals`, `etf_alpha_signals`)，有计算脚本但未纳入调度 | 接入 cron 调度 |
| **ETF 套利信号** | 🟡 P1 | 表结构已建 (`etf_arbitrage_signals`)，有配置参数但未自动化 | 接入 cron 调度 |
| **ETF 健康监控** | 🟡 P1 | `etf_health_monitor.py` 已实现 IOPV/流动性/波动率检查，但告警未持久化到统一表 | 将告警写入 `etf_health_alerts` 并纳入调度 |
| **风险监控** | 🟡 P1 | `risk_monitor.py` 已实现价格波动/成交量异常检测，但未接入 pipeline | 同上 |
| **Level2 高频数据** | 🟢 P2 | 无 Tick 级/逐笔成交数据 | 需接入付费数据源（如 Tushare Pro / Wind） |
| **舆情情感分析** | 🟢 P2 | `news_articles` 表有 `sentiment_label/score` 字段但采集器未填充 | 在新闻采集后增加 NLP 处理步骤 |

### 3.3 数据覆盖缺口总结

```
已覆盖: 公司主数据 ✓ | 股票日行情 ✓ | ETF行情 ✓ | 财报 ✓ | 新闻 ✓ | 研报(部分)
缺失:   指数行情 ✗ | 宏观数据 ✗ | 行业板块 ✗ | 资金流向明细 ✗ | Level2 ✗
```

---

## 四、架构设计质量

### 4.1 优点

#### ✅ Collector/Loader 分离清晰
- **Collector 层** (`src/collector/`)：专注数据获取，每个采集器独立封装 API 调用和字段映射
- **Loader 层** (`src/loader/`)：专注数据写入，PG loader 提供批量 upsert，MinIO loader 负责 Bronze 层存储
- **Pipeline 层** (`src/pipeline.py`)：编排调度，协调 collector → minio → pg 的数据流

#### ✅ 三层数据架构设计合理
```
Bronze (MinIO) → Silver (PG) → Gold (PG factor_values/analysis_signals)
```
- MinIO 存储原始 JSON（`bronze-quotes/`, `bronze-financial/`, `bronze-news/`）
- PG 存储清洗后的结构化数据
- 为后续 Gold 层因子计算预留了表结构

#### ✅ 数据库 Schema 设计完善
- 主键、外键、唯一约束、索引齐全
- `data_source_log` 和 `scheduler_jobs` 表已定义（审计和调度基础设施）
- JSONB 字段支持灵活扩展（`details_json`, `config_json`）

### 4.2 问题

#### ❌ P0: Pipeline 主编排器缺乏错误隔离

**现状**: `run_all()` 中各步骤串行执行，单步失败会导致整个 pipeline 中断。

```python
# src/pipeline.py L96-105 — 无 try/except 包裹
for code in batch_codes:
    batch = quotes.fetch_quotes(code, ...)  # 如果这里异常，后续所有股票都不会采集
    ...
```

**影响**: 单只股票 API 异常 → 整个批次中断 → 当日数据采集不完整。

**建议**: 
- 每步增加 `try/except`，记录失败股票并继续
- 引入步骤级结果汇总（成功数/失败数）

#### ❌ P0: 采集器无重试机制

**现状**: 所有采集器的异常处理均为 `except Exception: return []`，静默丢弃错误。

```python
# src/collector/quotes.py L53-55
try:
    df = ak.stock_zh_a_daily(...)
except Exception as e:
    logger.warning(f"{symbol} 行情获取失败: {e}")
    return []  # 无重试，直接返回空
```

**影响**: 网络抖动、API 限流等临时故障导致数据永久丢失。

**建议**: 
- 引入 `tenacity` 库实现指数退避重试（3次重试，间隔 1s/5s/25s）
- 区分可重试错误（超时、5xx）和不可重试错误（404、认证失败）

#### ❌ P1: Loader 层连接池管理不当

**现状**: `pg.py` 使用模块级单例连接池，但 `companies.py` / `etf.py` / `cifang.py` 中的数据库写入均直接 `psycopg2.connect()` 创建新连接。

```python
# src/collector/cifang.py L265 — 绕过连接池
conn = psycopg2.connect(pg.uri)
try:
    ...
finally:
    conn.close()
```

**影响**: 
- 同一 pipeline 运行中可能同时存在多个独立连接（连接池 + 直连）
- 高并发场景下可能耗尽数据库连接

**建议**: 
- 统一使用 `pg.py` 的 `_get_pool()` 获取连接
- 或在 collector 层注入 loader 依赖，避免直接操作数据库

#### ❌ P1: 事务管理不完整

**现状**: 部分写入操作有事务（`conn.commit()`），但 pipeline 整体无跨步骤事务。

```python
# src/pipeline.py — 各步骤独立 commit，无整体回滚机制
pg_loader.batch_upsert_quotes(batch)   # 内部 commit
minio_loader.store_json(...)           # 无事务关联
```

**影响**: 如果 MinIO 写入失败但 PG 已提交，会导致 Bronze/Silver 层数据不一致。

**建议**: 
- 引入两阶段提交或补偿机制
- 至少记录每步的 `batch_id`，便于事后对账

#### ⚠️ P2: 全局状态管理

**现状**: `rsscast.py` 使用全局 `_default_client`，通过 `configure()` 函数修改。

```python
# src/collector/rsscast.py L257-263
_default_client: Optional[RssCastClient] = None
def configure(endpoint, token):
    global _default_client
    _default_client = RssCastClient(endpoint, token)
```

**影响**: 多线程环境下存在竞态条件；不利于单元测试。

**建议**: 改为实例化方式，通过参数传递 client。

---

## 五、数据质量保障

### 5.1 现有机制

| 机制 | 实现位置 | 说明 | 评价 |
|------|---------|------|------|
| **NaN/Inf 过滤** | `pg.py:_nan_to_none()` | 将 NaN/Inf 转为 None，保留 -1 sentinel | ✅ 基本覆盖 |
| **日期标准化** | `pg.py:_normalize_date()` | ISO 格式转换 | ✅ 基本覆盖 |
| **字段映射校验** | 各 collector 内部 | 手动映射 akshare 列名到标准字段 | ⚠️ 无自动化校验 |
| **Upsert 去重** | PG UNIQUE 约束 | `daily_quotes(company_id, trade_date)` 等 | ✅ 防止重复写入 |
| **MinIO 原始存档** | `minio.py:store_json()` | 每批数据存为 JSON 文件 | ✅ 可追溯 |

### 5.2 缺失机制

| 缺失项 | 优先级 | 说明 | 建议方案 |
|--------|:------:|------|---------|
| **数据完整性校验** | 🔴 P0 | 无采集后校验（如：记录数是否达标、字段值域检查） | 增加 `min_records_warning` 阈值告警（已有配置但未使用） |
| **跨源一致性校验** | 🔴 P0 | akshare 与次方量化的同一数据未做比对 | 建立主备源交叉验证机制 |
| **断点续传** | 🟡 P1 | 无采集进度记录，失败后无法从断点恢复 | 使用 `data_source_log` 表记录每批 `batch_id` 和状态 |
| **数据血缘追踪** | 🟡 P1 | 无 `batch_id` 贯穿 Bronze→Silver→Gold | 在每条记录中注入 `batch_id` 和 `collected_at` |
| **Schema 版本管理** | 🟢 P2 | 数据库变更通过 SQL 文件手动执行，无迁移工具 | 引入 `alembic` 或 `flyway` |

### 5.3 Sentinel 值使用风险

**现状**: ETF 历史K线写入时使用 `-1` 作为 sentinel 值表示"不更新 spot 字段"。

```python
# src/pipeline.py L265-272 — sentinel = -1
"iopv": -1, "premium_rate": -1, ...
```

**风险**: 
- `-1` 是合法数值范围外的哨兵，但 `_nan_to_none()` 会保留它
- UPSERT 中 `NULLIF(-1, -1)` 转为 NULL 的逻辑依赖特定 SQL 写法
- 如果上游数据本身包含 `-1`（极端情况），会导致误判

**建议**: 
- 使用 `None` + COALESCE 替代 sentinel 模式
- 或在 schema 层增加 CHECK 约束排除哨兵值

---

## 六、性能与效率

### 6.1 现有机制

| 机制 | 实现位置 | 说明 | 评价 |
|------|---------|------|------|
| **批量写入** | `pg.py:execute_batch()` | psycopg2 extras 批量执行 | ✅ 优于逐条 INSERT |
| **请求间隔控制** | `config.py:request_interval=0.5s` | 每只股票采集后 sleep | ⚠️ 仅串行限速 |
| **MinIO 分日存储** | `minio.py:store_json()` | 按日期分文件存储 | ✅ 便于管理 |
| **增量回补** | `cron_etf_kline_evening.py` | 仅采集缺失日期（最多5天） | ✅ 避免重复采集 |

### 6.2 性能瓶颈

#### ❌ P0: 全串行采集，无并发

**现状**: `run_all()` 中每只股票串行采集：

```python
# src/pipeline.py L99-105
for code in batch_codes:
    batch = quotes.fetch_quotes(code, ...)  # 串行
    ...
    time.sleep(cc.request_interval)         # 串行限速
```

**影响**: 
- 50只股票 × (API延迟 + 0.5s sleep) ≈ 2-3分钟仅完成单数据类型
- 4个数据类型（行情+财报+指标+新闻）串行执行，总耗时可能超过 15 分钟
- ETF 全量采集（1486只）在 `batch_fetch_etf_hist()` 中同样串行

**建议**: 
- 使用 `concurrent.futures.ThreadPoolExecutor` 实现并发采集
- 控制并发数（如 10 线程），配合信号量限制 API QPS
- 或引入 `asyncio` + `httpx.AsyncClient` 实现异步采集

#### ❌ P1: ETF 全量采集性能风险

**现状**: `run_etf_pipeline()` 默认 `limit=1486`（全量 ETF），每只 ETF 串行请求 API。

```python
# src/pipeline.py L247-278 — 1486只ETF串行
for etf in target_etfs:
    hist = etf_collector.fetch_etf_hist(code, ...)  # 串行
    time.sleep(cc.request_interval)
```

**影响**: 
- 1486 × (API延迟 + 0.5s) ≈ 20-30 分钟（仅历史K线）
- 盘中刷新场景下可能超时

**建议**: 
- 区分"全量初始化"和"增量刷新"模式
- 增量刷新仅处理当日数据，使用批量 API（如次方量化的 `fetch_fund_spot()` 一次返回全部）

#### ⚠️ P2: 连接池大小偏小

**现状**: `pg.py` 连接池 `minconn=1, maxconn=4`。

**影响**: 
- 单进程场景下够用，但如果引入并发采集，4个连接可能成为瓶颈
- 批量写入时 execute_batch 会占用一个连接直到完成

**建议**: 根据并发数调整 `maxconn`（如 `max(4, 并发线程数 + 1)`）

---

## 七、可靠性与可观测性

### 7.1 现有机制

| 机制 | 实现位置 | 说明 | 评价 |
|------|---------|------|------|
| **日志记录** | 各模块 `logger.info/warning` | 基础 INFO/WARNING 级别日志 | ⚠️ 有但不够结构化 |
| **RotatingFileHandler** | `cron_etf_kline_evening.py` | 部分脚本配置了日志轮转 | ⚠️ 仅部分脚本使用 |
| **健康检查** | `etf_health_monitor.py` | IOPV/流动性/波动率监控 | ✅ 有但告警未持久化 |
| **风险监控** | `risk_monitor.py` | 价格波动/成交量异常检测 | ✅ 有但未接入调度 |

### 7.2 严重缺失

#### ❌ P0: data_source_log 表未被使用

**现状**: Schema 中定义了 `data_source_log` 表（L296-319），但代码中无任何写入逻辑。

```sql
-- init-db/00_schema.sql L296 — 审计日志表已定义
CREATE TABLE data_source_log (
    source_name VARCHAR(100),
    data_type VARCHAR(30),
    batch_id VARCHAR(50),
    status VARCHAR(20),  -- success/partial/failed
    records_fetched INT,
    records_written INT,
    ...
);
```

**影响**: 
- 无法追踪每次采集的成败、耗时、记录数
- 无法进行采集质量趋势分析
- `scheduler_jobs` 表同样未被使用

**建议**: 
- 在 pipeline 每步完成后写入 `data_source_log`
- 在 cron 脚本入口/出口记录执行状态到 `scheduler_jobs`

#### ❌ P0: 无告警通知机制

**现状**: `etf_health_monitor.py` 和 `risk_monitor.py` 仅打印日志，未集成任何通知渠道。

**影响**: 
- 采集失败、数据异常时无人知晓
- 无法通过飞书/钉钉/邮件/微信等渠道及时通知

**建议**: 
- 实现统一的告警适配器（支持 Webhook/飞书/钉钉）
- 在 pipeline 失败时自动发送告警

#### ❌ P1: 日志格式不统一

**现状**: 
- `cron_etf_kline_evening.py` 使用 RotatingFileHandler + 结构化格式
- `pipeline.py` / collector 仅使用 `logging.getLogger(__name__)`，无文件输出
- bootstrap_runner.py 仅输出 JSON 结果到 stdout

**影响**: 
- 日志分散在多处，难以集中检索
- 缺少统一的时间戳、模块名、请求 ID

**建议**: 
- 定义统一的日志格式（JSON 格式便于 ELK 解析）
- 所有脚本通过 `bootstrap_runner.py` 或公共配置初始化日志

#### ⚠️ P1: 无采集成功率监控

**现状**: 虽有 `MIN_RECORDS_WARNING=10` 配置，但未在 pipeline 中实际使用。

```python
# config.py L78 — 配置了但未使用
min_records_warning: int = env_int("MIN_RECORDS_WARNING", 10)
```

**建议**: 
- 每步采集后检查记录数是否低于阈值
- 低于阈值时标记 `status=partial` 并触发告警

---

## 八、关键缺口与优化建议（按优先级排序）

### 🔴 P0 — 立即修复（影响数据可用性）

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 1 | **采集器无重试机制** | 临时故障导致数据永久丢失 | 引入 `tenacity` 实现指数退避重试（3次） | 2人日 |
| 2 | **Pipeline 无错误隔离** | 单步失败导致全量中断 | 每步增加 try/except，记录失败并继续 | 1人日 |
| 3 | **data_source_log 未使用** | 无法追踪采集质量 | 在 pipeline 每步写入审计日志 | 1人日 |
| 4 | **无告警通知** | 故障无人知晓 | 实现 Webhook 告警适配器（飞书/钉钉） | 2人日 |

### 🟡 P1 — 短期优化（影响数据质量和运维效率）

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 5 | **全串行采集，无并发** | 采集耗时过长 | ThreadPoolExecutor 并发采集（10线程） | 3人日 |
| 6 | **跨源一致性校验缺失** | akshare/次方量化数据不一致无法发现 | 建立主备源交叉验证机制 | 2人日 |
| 7 | **指数行情未接入 pipeline** | 缺少大盘指数数据 | 在 `run_all()` 中增加指数采集步骤 | 1人日 |
| 8 | **统一日志格式** | 日志分散难检索 | JSON 格式 + RotatingFileHandler 全局配置 | 1人日 |
| 9 | **Loader 连接池统一** | 直连绕过连接池 | collector 层注入 loader 依赖 | 1人日 |

### 🟢 P2 — 中期规划（影响扩展性和可维护性）

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 10 | **宏观/行业数据缺失** | 无法支撑基本面分析 | 接入 Tushare/Wind 宏观数据 | 3人日 |
| 11 | **断点续传机制** | 失败后需全量重采 | batch_id + 进度表记录 | 2人日 |
| 12 | **Schema 迁移工具** | 手动执行 SQL 易出错 | 引入 alembic | 1人日 |
| 13 | **单元测试覆盖** | 仅 signals/alpha.py 有测试 | 为 collector/loader 增加集成测试 | 5人日 |
| 14 | **配置管理优化** | 环境变量分散，无校验 | Pydantic Settings + 配置热更新 | 2人日 |

---

## 九、架构改进路线图

```
Phase 1 (当前)                    Phase 2 (短期)                  Phase 3 (中期)
─────────────                    ─────────────                   ─────────────
┌──────────────────┐            ┌──────────────────┐           ┌──────────────────┐
│ akshare (主源)   │            │ + 重试机制        │           │ + 宏观数据       │
│ 次方量化 (ETF)   │    →       │ + 错误隔离        │    →      │ + 行业板块       │
│ RssCast (备源)   │            │ + 审计日志        │           │ + 资金流向明细   │
├──────────────────┤            │ + 并发采集        │           │ + Level2数据     │
│ Bronze: MinIO    │            │ + 告警通知        │           │ + 停复牌日历     │
│ Silver: PG       │            │ + 跨源校验        │           │ + 舆情情感分析   │
└──────────────────┘            └──────────────────┘           └──────────────────┘
```

---

## 十、结论

当前数据采集层已具备**良好的架构基础**（collector/loader 分离、三层数据架构、完善的数据库 Schema），但在**可靠性（重试/错误隔离）、可观测性（审计日志/告警）、性能（并发）**三个关键维度存在明显短板。

**建议优先解决 P0 级问题**（重试机制、错误隔离、审计日志、告警通知），这些改动工作量小但能显著提升系统的生产可用性。随后逐步推进 P1/P2 优化，完善数据源覆盖和性能瓶颈。

---

*本报告由 data-arch-eng 基于代码静态分析生成，未涉及运行时指标。建议结合实际运行日志进一步验证评估结论。*

---

## 十一、采集器实现质量分析（code-quality-expert）

**评估人**: code-quality-expert (Python代码质量专家)  
**评估日期**: 2026-06-03  
**评估范围**: `/home/claw/invest-infra/data-pipeline/src/collector/*.py` + `src/loader/pg.py` + `src/config.py`

---

### 11.1 采集器代码质量总览

| 采集器 | 文件路径 | 综合评分 | 关键问题数 |
|--------|---------|:--------:|:----------:|
| **quotes** | `collector/quotes.py` | ⚠️ 3/5 | 4 |
| **financial** | `collector/financial.py` | ⚠️ 3/5 | 5 |
| **news** | `collector/news.py` | ⚠️ 2/5 | 4 |
| **etf** | `collector/etf.py` | ⚠️ 3/5 | 6 |
| **cifang** | `collector/cifang.py` | ✅ 4/5 | 3 |
| **rsscast** | `collector/rsscast.py` | ✅ 4/5 | 3 |
| **companies** | `collector/companies.py` | ⚠️ 3/5 | 3 |
| **etf_health_monitor** | `collector/etf_health_monitor.py` | ⚠️ 2/5 | 5 |

---

### 11.2 各采集器详细分析

#### 11.2.1 quotes.py — 日行情数据采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/quotes.py`

**✅ 优点**:
- 字段映射清晰（`field_map` 字典），易于维护
- 日志记录完整（获取前/后均有 INFO 级别日志）
- `_market_for_code()` 能正确识别 SH/SZ/BJ 交易所

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| Q1 | 🔴 P0 | L53-55 | **裸 `except Exception` 吞掉所有异常**，包括 `KeyboardInterrupt`、`SystemExit` 等系统信号 | 改为 `except (requests.RequestException, akshare.AkShareError) as e:`，仅捕获业务异常 |
| Q2 | 🟡 P1 | L85-86 | **涨跌幅计算逻辑错误**：使用 `(close - open) / open` 而非标准的前复权涨跌幅 `(close - pre_close) / pre_close` | 从 akshare 结果中取 `pre_close` 字段计算，或等待 akshare 返回 `change_pct` |
| Q3 | 🟡 P1 | L26 | **未知代码默认 SH**：`_market_for_code()` 对无法识别的代码（如科创板 688xxx 以外的特殊代码）默认返回 "SH"，可能导致数据写入错误交易所 | 抛出 `ValueError` 而非静默降级 |
| Q4 | 🟢 P2 | L73-81 | **逐行 iterrows() 性能差**：对大量数据（如全市场5000只股票）逐行迭代效率低 | 使用 `df.to_dict('records')` + 列表推导式批量转换 |

**改进示例 (Q2)**:
```python
# 当前错误实现
if r.get("close_price") and r.get("open_price"):
    r["change_pct"] = round((r["close_price"] - r["open_price"]) / r["open_price"] * 100, 4)

# 建议修正
pre_close = row.get("昨收") or row.get("pre_close")
if r.get("close_price") and pre_close:
    r["change_pct"] = round((r["close_price"] - float(pre_close)) / float(pre_close) * 100, 4)
```

---

#### 11.2.2 financial.py — 财报数据采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/financial.py`

**✅ 优点**:
- 双层采集策略（abstract + indicator）互补数据缺口
- `_report_type_from_date()` 能正确区分 Q1/Q2/Q3/annual
- 财务指标回填函数 `backfill_financial_assets` 设计合理

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| F1 | 🔴 P0 | L39-43, L111-115, L173-177 | **三处裸 `except Exception`**，akshare API 异常被静默吞掉 | 统一改为捕获具体异常类型，至少记录异常堆栈 |
| F2 | 🟡 P1 | L64-72 | **嵌套函数在循环内定义**：`_val()` 在 `for d in dates:` 循环中每次重新定义，产生不必要的闭包开销 | 提取为模块级函数或类方法 |
| F3 | 🟡 P1 | L49 | **硬编码列名 `"选项"`, `"指标"`**：akshare 返回的列名可能变化，导致解析失败 | 使用 `df.columns.tolist()` 动态识别，或增加列名校验 |
| F4 | 🟢 P2 | L168-195 | **`fetch_financial_detail()` 返回原始格式**：未做字段标准化，调用方需额外处理 | 增加 `_normalize_financial_record()` 统一输出格式 |
| F5 | 🟢 P2 | L147-149 | **资产负债率反推总负债精度问题**：`liabilities = assets * debt_ratio / 100`，但 akshare 的 `debt_ratio_raw` 可能为 None | 增加空值检查并记录警告日志 |

**改进示例 (F2)**:
```python
# 当前：嵌套函数在循环内定义（性能浪费）
for d in dates:
    def _val(metric_name: str) -> Optional[float]:
        idx = metrics.get(metric_name)
        if idx is None: return None
        v = df.iloc[idx][d]
        try: return float(v) if pd.notna(v) else None
        except (ValueError, TypeError): return None

# 建议：提取为模块级函数
def _extract_metric(df: pd.DataFrame, metrics: dict, metric_name: str, date_col) -> Optional[float]:
    idx = metrics.get(metric_name)
    if idx is None: return None
    v = df.iloc[idx][date_col]
    try: return float(v) if pd.notna(v) else None
    except (ValueError, TypeError): return None

# 循环内直接调用
for d in dates:
    records.append({
        "revenue": _extract_metric(df, metrics, "营业总收入", d),
        ...
    })
```

---

#### 11.2.3 news.py — 舆情数据采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/news.py`

**✅ 优点**:
- 代码简洁，职责单一
- `_parse_time()` 支持多种时间格式

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| N1 | 🔴 P0 | L17-21 | **裸 `except Exception`**：akshare API 异常被吞掉 | 捕获具体异常类型 |
| N2 | 🟡 P1 | L39-48 | **时间解析过于脆弱**：仅支持 ISO 格式和 date 对象，对 "2026-06-03 10:30:00" 等常见格式无法解析 | 使用 `dateutil.parser.parse()` 或增加更多格式尝试 |
| N3 | 🟡 P1 | L31 | **内容截断无长度检查**：`str(row.get("新闻内容", ""))[:500]` 在内容为空字符串时仍执行切片，浪费计算 | 先检查非空再截断 |
| N4 | 🟢 P2 | — | **无去重机制**：同一新闻可能被重复采集（如 pipeline 重试） | 基于 `source_url` 或 `title + published_at` 组合键去重 |

**改进示例 (N2)**:
```python
# 当前脆弱实现
def _parse_time(t) -> Optional[datetime]:
    if t is None: return None
    if isinstance(t, datetime): return t
    if isinstance(t, date): return datetime.combine(t, datetime.min.time())
    try: return datetime.fromisoformat(str(t).replace("T", " ").split(".")[0])
    except (ValueError, TypeError): return None

# 建议：使用 dateutil 增强解析
from dateutil import parser as date_parser

def _parse_time(t) -> Optional[datetime]:
    if t is None: return None
    if isinstance(t, datetime): return t
    if isinstance(t, date): return datetime.combine(t, datetime.min.time())
    try:
        return date_parser.parse(str(t))
    except (ValueError, TypeError):
        logger.debug(f"无法解析时间: {t!r}")
        return None
```

---

#### 11.2.4 etf.py — ETF 数据采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/etf.py`

**✅ 优点**:
- **双源 fallback 机制**（新浪 → 东方财富）设计优秀
- `sync_etfs_to_db()` 使用 `ON CONFLICT ... DO UPDATE` 实现幂等写入
- `batch_fetch_etf_hist()` 有进度日志和批量 commit

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| E1 | 🔴 P0 | L23 | **`fetch_etf_spot()` 无异常处理**：akshare API 调用失败直接抛出异常，导致整个 pipeline 崩溃 | 增加 `try/except` 包裹，返回空列表或降级数据 |
| E2 | 🟡 P1 | L173-204, L226-283 | **数据库直连绕过连接池**：`sync_etfs_to_db()` 和 `batch_fetch_etf_hist()` 均使用 `psycopg2.connect(pg.uri)` 创建新连接，与 `pg.py` 的连接池隔离 | 统一使用 `pg.get_conn()` 上下文管理器 |
| E3 | 🟡 P1 | L108 | **循环内 import**：`from datetime import datetime` 放在 `for` 循环内部（L108），每次迭代都执行 import | 移到文件顶部 |
| E4 | 🟢 P2 | L72-83 | **`_categorize()` 硬编码分类逻辑**：基于名称关键字匹配，无法覆盖新类型 ETF | 使用配置文件或数据库字典维护分类规则 |
| E5 | 🟢 P2 | L207 | **硬编码 limit=1486**：全量 ETF 数量写死在函数签名中 | 从配置读取或使用 `len(fetch_etf_spot())` 动态获取 |
| E6 | 🟢 P2 | L57-61 | **`_etf_prefix()` 逻辑与 `_market_for_code()` 不一致**：ETF 前缀判断规则（0/1/3→sz）与公司代码规则（0/3→sz, 6→sh）不同，但实现方式有差异 | 统一交易所判断逻辑为共享函数 |

**改进示例 (E1)**:
```python
# 当前：无异常处理
def fetch_etf_spot() -> list[dict]:
    logger.info("正在获取 ETF 实时行情 ...")
    df = ak.fund_etf_spot_em()  # 如果这里失败，整个 pipeline 崩溃
    ...

# 建议：增加异常处理
def fetch_etf_spot() -> list[dict]:
    logger.info("正在获取 ETF 实时行情 (fund_etf_spot_em) ...")
    try:
        df = ak.fund_etf_spot_em()
    except Exception as e:
        logger.error(f"ETF 实时行情获取失败: {e}", exc_info=True)
        return []
    
    if df is None or df.empty:
        logger.warning("ETF 实时行情返回空数据")
        return []
    
    ...
```

---

#### 11.2.5 cifang.py — 次方量化采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/cifang.py`

**✅ 优点**:
- **统一的 `_get()` 请求封装**：包含超时、状态码检查、异常处理
- **自定义字段映射函数**：`spot_to_etf_quote()`, `hist_to_etf_quote()`, `fund_list_to_etf()` 职责清晰
- **合理的 API 响应校验**：检查 `d.get("code") != 0`

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| C1 | 🟡 P1 | L265-294, L312-364, L379-427 | **三处数据库直连**：`upsert_etfs_from_cifang()`, `write_spot_to_etf_quotes()`, `backfill_hist()` 均绕过连接池 | 统一使用 `pg.get_conn()` |
| C2 | 🟢 P2 | L24 | **硬编码超时值**：`TIMEOUT = 15` 应来自配置 | 从 `config.py` 读取 `CIFANG_TIMEOUT` |
| C3 | 🟢 P2 | L155-166 | **`_normalize_fund_record()` 静默丢弃缺失字段**：`rec.get("code") or rec.get("fund_code", "")` 当两者都为空时返回空字符串，下游可能误判 | 增加空值校验，抛出 `ValueError` 或记录警告 |

---

#### 11.2.6 rsscast.py — RssCast MCP 采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/rsscast.py`

**✅ 优点**:
- **自定义异常层次**：`RssCastError`（请求失败）和 `RssCastNoData`（无数据）区分清晰
- **JSON-RPC 2.0 实现规范**：正确的 payload 格式、id 递增、错误处理
- **标准化输出接口**：`*_normalized()` 方法提供统一字段映射

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| R1 | 🟡 P1 | L257-270 | **全局状态 `_default_client`**：多线程环境下 `configure()` 可能导致竞态条件 | 改为实例化方式，通过参数传递 client |
| R2 | 🟢 P2 | L131-135, L180-185 | **原始文本解析脆弱**：`text.find("[{")` + `text.rfind("]")` 依赖响应格式，如果 RssCast 返回格式变化会导致解析失败 | 增加 JSON 解析的 fallback（如尝试 XML/CSV 格式） |
| R3 | 🟢 P2 | L43-44 | **配置检查使用 `RuntimeError`**：调用方需捕获特定异常类型 | 考虑使用自定义 `RssCastNotConfigured` 异常 |

---

#### 11.2.7 companies.py — 公司列表采集器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/companies.py`

**✅ 优点**:
- **批量 IN 查询优化**：先查已存在 codes，再分类处理（新增 vs 不变）
- **upsert 幂等写入**：`ON CONFLICT (code) DO UPDATE SET updated_at = now()`

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| CP1 | 🟡 P1 | L27 | **akshare 调用无异常处理**：`stock_info_a_code_name()` 失败直接抛出 | 增加 `try/except` |
| CP2 | 🟢 P2 | L59 | **数据库直连**：`sync_to_db()` 创建新连接而非使用连接池 | 统一使用 `pg.get_conn()` |
| CP3 | 🟢 P2 | L39 | **industry 字段始终为 None**：akshare `stock_info_a_code_name()` 不返回行业信息，但表结构有 industry 字段 | 考虑接入 akshare `stock_info_industry_list_em()` 补充 |

---

#### 11.2.8 etf_health_monitor.py — ETF 健康监控器

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/collector/etf_health_monitor.py`

**✅ 优点**:
- **多维度监控**：IOPV 折溢价、流动性、波动率、资金流向
- **警报分级**：warning/critical 两级，signal_type 区分正负信号
- **数据库持久化**：告警写入 `etf_health_alerts` 表

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| H1 | 🔴 P0 | L15 | **`sys.path.insert(0, ...)` 代码异味**：硬编码绝对路径，破坏模块导入规范 | 移除，通过 PYTHONPATH 或 pip install -e 管理 |
| H2 | 🟡 P1 | L61-64 | **数据库直连**：`__init__` 中创建独立连接，未使用连接池 | 注入 `pg.get_conn()` 或使用上下文管理器 |
| H3 | 🟡 P1 | L306-327 | **打印到 stdout 而非日志**：健康检查报告使用 `print()` 输出，不利于日志收集 | 改用 `logger.info()` 结构化输出 |
| H4 | 🟢 P2 | L34-39 | **硬编码阈值**：`IOPV_WARNING_THRESHOLD = 1.0` 等应来自配置 | 从 `config.py` 读取 |
| H5 | 🟢 P2 | L222-223 | **波动率计算使用 numpy**：导入 numpy 但仅用于 mean/std，可用 statistics 模块替代减少依赖 | 改用 `statistics.mean()` / `statistics.stdev()` |

---

### 11.3 数据校验与清洗分析

#### 11.3.1 `_nan_to_none()` 函数评估

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/loader/pg.py` L50-60

```python
def _nan_to_none(v):
    if v is None: return None
    try:
        if math.isnan(v) or math.isinf(v): return None
    except TypeError: pass
    return v  # sentinel -1 保留
```

**✅ 优点**:
- 正确处理 `None`、`NaN`、`Inf` 三种异常数值
- `TypeError` 捕获处理非数值类型（如字符串）

**❌ 问题**:

| # | 严重度 | 问题描述 | 改进建议 |
|---|--------|---------|---------|
| NV1 | 🟡 P1 | **不处理字符串形式的 "NaN"/"inf"**：如果 akshare 返回字符串 `"NaN"`，`math.isnan("NaN")` 抛出 `TypeError` 被静默忽略，原值保留 | 增加字符串检查：`if isinstance(v, str) and v.lower() in ("nan", "inf", "none"): return None` |
| NV2 | 🟡 P1 | **不处理 pandas NA/NaT**：pandas 的 `NA` 和 `NaT` 类型不被 `math.isnan()` 识别 | 增加 `pd.isna(v)` 前置检查 |
| NV3 | 🟢 P2 | **sentinel -1 保留逻辑与注释不一致**：注释说"调用方用 NULLIF(-1, -1) 转为 NULL"，但并非所有写入路径都使用此模式 | 统一在 SQL 层处理 sentinel，或在 `_nan_to_none` 中直接转换 |

**改进示例**:
```python
def _nan_to_none(v):
    """过滤 NaN/Inf/NA → None；保留 -1 sentinel 值"""
    if v is None:
        return None
    # 处理 pandas NA/NaT
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except (ImportError, TypeError):
        pass
    # 处理字符串形式的 NaN/Inf
    if isinstance(v, str) and v.lower() in ("nan", "inf", "-inf", "none", "null"):
        return None
    # 处理数值类型的 NaN/Inf
    try:
        if math.isnan(v) or math.isinf(v):
            return None
    except (TypeError, ValueError):
        pass
    return v
```

#### 11.3.2 `_normalize_date()` 函数评估

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/loader/pg.py` L63-68

```python
def _normalize_date(v) -> str | None:
    if v is None: return None
    if isinstance(v, str) and "T" in v: return v.split("T")[0]
    return v
```

**❌ 问题**:

| # | 严重度 | 问题描述 | 改进建议 |
|---|--------|---------|---------|
| DV1 | 🔴 P0 | **仅处理 ISO 格式（含 T）**：对 `"2026-06-03"`、`"2026/06/03"`、`datetime.date` 对象等常见格式无标准化，直接返回原始值 | 增加 `dateutil.parser.parse()` 或显式处理多种格式 |
| DV2 | 🟡 P1 | **不验证日期合法性**：如果输入 `"2026-13-45"`（无效日期），直接返回原字符串，可能导致数据库写入错误 | 增加日期验证：`datetime.strptime(v, "%Y-%m-%d")` |
| DV3 | 🟢 P2 | **不处理时区信息**：ISO 8601 带时区的日期（如 `"2026-06-03T10:00:00+08:00"`）仅截取前半部分，可能丢失时区语义 | 使用 `dateutil.parser` 解析后取 `.date()` |

**改进示例**:
```python
from datetime import date as date_type
import re

def _normalize_date(v) -> str | None:
    """标准化日期为 YYYY-MM-DD 格式"""
    if v is None:
        return None
    if isinstance(v, (date_type, datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str):
        # ISO 格式含 T
        if "T" in v:
            return v.split("T")[0]
        # 斜杠分隔
        v = v.replace("/", "-")
        # 验证日期合法性
        try:
            parsed = datetime.strptime(v[:10], "%Y-%m-%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            logger.warning(f"无法解析日期: {v!r}")
            return None
    return str(v)
```

#### 11.3.3 数据校验覆盖度总结

| 校验项 | 已实现 | 充分性 | 说明 |
|--------|:------:|:------:|------|
| NaN/Inf → None | ✅ | ⚠️ 基本 | 不处理字符串 NaN、pandas NA |
| 日期标准化 | ✅ | ⚠️ 基本 | 仅处理 ISO T 格式，无验证 |
| 字段类型转换 | ✅ | ⚠️ 部分 | quotes.py 有 float() 转换但静默失败 |
| 空值检查 | ✅ | ✅ | 各采集器对 None/empty 有检查 |
| 值域校验 | ❌ | — | 无价格>0、成交量>=0 等约束 |
| 跨字段一致性 | ❌ | — | 如 high >= open/close >= low 未检查 |
| Schema 版本 | ❌ | — | 无数据库 schema 迁移管理 |

---

### 11.4 错误处理机制分析

#### 11.4.1 异常捕获模式统计

| 采集器 | 裸 except Exception | 具体异常捕获 | 重试机制 | 降级策略 |
|--------|:------------------:|:-----------:|:--------:|:--------:|
| quotes.py | 1 处 (L53) | 0 | ❌ | 返回空列表 |
| financial.py | 3 处 (L41, L113, L175) | 0 | ❌ | 返回空列表/字典 |
| news.py | 1 处 (L19) | 0 | ❌ | 返回空列表 |
| etf.py | 2 处 (L128, L161) | 0 | ✅ fallback | 新浪→东财降级 |
| cifang.py | 1 处 (L41) | 1 (Timeout) | ❌ | 返回空字典 |
| rsscast.py | 1 处 (L73) | 2 (HTTPError, TimeoutError) | ❌ | 抛出 RssCastNoData |
| companies.py | 0 | 0 | ❌ | —（无异常处理）|

#### 11.4.2 日志规范评估

**✅ 优点**:
- 所有模块使用 `logging.getLogger(__name__)` 标准模式
- INFO/WARNING/ERROR 级别基本合理

**❌ 问题**:

| # | 严重度 | 问题描述 | 改进建议 |
|---|--------|---------|---------|
| L1 | 🟡 P1 | **日志格式不统一**：部分使用 f-string（`f"{symbol} 获取到 {len(records)} 条"`），部分使用 `%` 格式化（`logger.info("次方量化基金列表: %d 只", len(data))`） | 统一使用 `%` 格式化（性能更好，支持延迟求值） |
| L2 | 🟡 P1 | **DEBUG 级别滥用**：etf.py L129/162 用 DEBUG 记录 API 失败，生产环境默认不输出 DEBUG，导致故障排查困难 | 改为 WARNING 或 ERROR |
| L3 | 🟢 P2 | **缺少请求 ID/追踪 ID**：无法关联同一请求的日志链路 | 引入 `contextvars` 生成 request_id 注入日志 |
| L4 | 🟢 P2 | **异常堆栈未记录**：多数 `logger.warning(f"...: {e}")` 不输出完整堆栈 | 使用 `logger.exception()` 或 `exc_info=True` |

#### 11.4.3 错误处理改进建议

```python
# 推荐的统一异常处理模式
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class DataFetchError(Exception):
    """数据采集失败"""
    pass

class DataFetchRetryableError(DataFetchError):
    """可重试的采集失败（网络超时、5xx 等）"""
    pass

class DataFetchPermanentError(DataFetchError):
    """不可重试的采集失败（404、认证失败等）"""
    pass

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type(DataFetchRetryableError),
    reraise=True,
)
def fetch_quotes(stock_code: str, ...) -> list[dict]:
    try:
        df = ak.stock_zh_a_daily(...)
    except TimeoutError as e:
        logger.warning(f"{stock_code} 请求超时，将重试", exc_info=True)
        raise DataFetchRetryableError(f"timeout: {e}") from e
    except Exception as e:
        logger.error(f"{stock_code} 采集失败", exc_info=True)
        raise DataFetchPermanentError(f"fetch failed: {e}") from e
```

---

### 11.5 断点续传能力分析

#### 11.5.1 现有去重机制

| 数据类型 | 去重方式 | 实现位置 | 有效性 |
|---------|---------|---------|:------:|
| daily_quotes | `UNIQUE(company_id, trade_date)` + `ON CONFLICT DO UPDATE` | pg.py L119-125 | ✅ 有效 |
| financial_reports | `UNIQUE(company_id, report_date, report_type)` + `ON CONFLICT DO UPDATE` | pg.py L173-183 | ✅ 有效 |
| etf_quotes | `UNIQUE(etf_id, trade_date)` + `ON CONFLICT DO UPDATE` | pg.py L384-396 | ✅ 有效 |
| news_articles | `ON CONFLICT DO NOTHING`（无唯一约束指定） | pg.py L270 | ⚠️ 依赖隐式约束 |
| companies | `ON CONFLICT (code) DO UPDATE` | companies.py L81-84 | ✅ 有效 |

#### 11.5.2 断点续传缺口

| 缺口项 | 严重度 | 说明 | 影响 |
|--------|:------:|------|------|
| **无采集进度记录** | 🔴 P0 | `data_source_log` 表已定义但从未写入，无法知道上次采集到哪只股票/哪个日期 | 失败后需全量重采 |
| **无增量判断逻辑** | 🟡 P1 | pipeline 每次都从 `start_date` 开始采集，不检查数据库中是否已有数据 | 浪费 API 配额和存储 |
| **MinIO 无去重** | 🟢 P2 | MinIO 按日期存文件，同名文件会被覆盖，无法判断是否已存档 | 可能导致 Bronze 层数据丢失 |

#### 11.5.3 断点续传改进建议

```python
# 建议在 pipeline.py 中增加增量采集逻辑
def _get_last_trade_date(conn, table: str, code_col: str) -> Optional[date]:
    """获取某表最后交易日"""
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT MAX(trade_date) FROM {table}
            WHERE {code_col} = %s
        """, (stock_code,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

# 在 run_all() 中：
last_date = _get_last_trade_date(conn, "daily_quotes", "company_id")
if last_date:
    start_date = last_date + timedelta(days=1)  # 增量采集
    logger.info(f"增量采集从 {start_date} 开始（上次: {last_date}）")
else:
    start_date = today - timedelta(days=cc.quotes_history_days)
    logger.info(f"全量采集，从 {start_date} 开始")
```

---

### 11.6 配置管理分析

#### 11.6.1 config.py 评估

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/config.py`

**✅ 优点**:
- Dataclass 结构清晰，类型注解完整
- `__post_init__` 中校验必填环境变量（PG_PASSWORD, MINIO_SECRET_KEY, CIFANG_TOKEN）
- 提供 `env()` / `env_int()` / `env_float()` 辅助函数

**❌ 问题清单**:

| # | 严重度 | 位置 | 问题描述 | 改进建议 |
|---|--------|------|---------|---------|
| CG1 | 🟡 P1 | L8-9 | **`env()` 无类型校验**：返回空字符串时调用方可能误用 | 增加 `env_required()` 函数，未设置时抛出 `ValueError` |
| CG2 | 🟡 P1 | L43-44 | **密码明文存储在 URI 中**：`pg.uri` 包含完整密码，可能被日志/异常泄露 | 使用 `psycopg2.connect(dsn=pg.dsn)` 而非 URI 字符串 |
| CG3 | 🟢 P2 | — | **无 .env 文件加载**：`.env` 在 `bootstrap_runner.py` 中手动解析（L15-21），非标准做法 | 使用 `python-dotenv` 库统一加载 |
| CG4 | 🟢 P2 | L74 | **`stock_codes` 默认空列表**：pipeline 中 fallback 到全量公司列表，但无上限保护 | 增加 `MAX_STOCK_CODES` 配置项 |
| CG5 | 🟢 P2 | — | **无配置热更新**：运行时修改 `cc.quotes_history_days = days`（pipeline.py L82）影响全局状态 | 改为函数参数传递，避免副作用 |

#### 11.6.2 bootstrap_runner.py 中的 .env 解析问题

**文件路径**: `/home/claw/invest-infra/data-pipeline/src/bootstrap_runner.py` L15-21

```python
# 当前手动解析（有安全隐患）
for line in ENV_FILE.read_text().strip().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()  # 明文密码写入环境变量
```

**问题**:
- 手动解析不支持引号包裹的值（如 `PG_PASSWORD="my'pass"`）
- 不支持 `${VAR}` 变量引用
- 无文件权限检查

**建议**:
```python
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)
```

---

### 11.7 代码质量评分汇总

| 维度 | 评分 (1-5) | 说明 |
|------|:----------:|------|
| **异常处理规范性** | 2 | 多处裸 `except Exception`，无重试机制 |
| **日志规范** | 3 | 有日志但格式不统一，缺少堆栈信息 |
| **数据校验充分性** | 3 | NaN/日期处理基本覆盖，但缺乏值域和一致性校验 |
| **代码可维护性** | 4 | 模块职责清晰，函数命名规范 |
| **配置管理** | 3 | Dataclass 设计合理，但 .env 加载不规范 |
| **断点续传能力** | 2 | 无进度记录，依赖数据库唯一约束做幂等 |

---

### 11.8 改进建议优先级汇总

#### 🔴 P0 — 立即修复

| # | 问题 | 涉及文件 | 建议方案 |
|---|------|---------|---------|
| 1 | 裸 `except Exception` 吞异常 | quotes.py, financial.py(×3), news.py | 改为捕获具体异常类型 + `exc_info=True` |
| 2 | `fetch_etf_spot()` 无异常处理 | etf.py L23 | 增加 try/except，返回空列表 |
| 3 | `_nan_to_none` 不处理字符串 NaN/pandas NA | pg.py L50-60 | 增加 `pd.isna()` 和字符串检查 |
| 4 | `_normalize_date` 仅处理 ISO T 格式 | pg.py L63-68 | 使用 `dateutil.parser` + 日期验证 |

#### 🟡 P1 — 短期优化

| # | 问题 | 涉及文件 | 建议方案 |
|---|------|---------|---------|
| 5 | 数据库直连绕过连接池 | etf.py, cifang.py(×3), companies.py | 统一使用 `pg.get_conn()` |
| 6 | 涨跌幅计算逻辑错误 | quotes.py L85-86 | 使用 `pre_close` 计算标准涨跌幅 |
| 7 | 日志格式不统一 | 全局 | 统一使用 `%` 格式化 + 结构化字段 |
| 8 | 无重试机制 | 全局采集器 | 引入 `tenacity` 实现指数退避重试 |

#### 🟢 P2 — 中期规划

| # | 问题 | 涉及文件 | 建议方案 |
|---|------|---------|---------|
| 9 | .env 手动解析 | bootstrap_runner.py | 改用 `python-dotenv` |
| 10 | 全局状态 `_default_client` | rsscast.py | 改为实例化方式 |
| 11 | 硬编码阈值/超时 | etf_health_monitor.py, cifang.py | 移至 config.py |
| 12 | sys.path.insert 代码异味 | etf_health_monitor.py L15 | 移除，通过 PYTHONPATH 管理 |

---

*本报告由 code-quality-expert 基于源码静态分析生成，聚焦 Python 代码质量维度（异常处理、日志规范、数据校验、配置管理）。与 data-arch-eng 的架构评估报告互补。*

---

## 十二、调度与可观测性专项分析（sre-expert）

**评估人**: sre-expert (DevOps/SRE专家)  
**评估日期**: 2026-06-03  
**评估范围**: `/home/claw/invest-infra/data-pipeline/scripts/cron_*.py` + `health_check.sh` + `run_health_monitor.sh` + `docker-compose.yml` + `init-db/00_schema.sql`

---

### 12.1 调度机制分析

#### 12.1.1 现有 Cron 脚本清单

| 脚本 | 调度时间 | 职责 | 执行方式 |
|------|---------|------|---------|
| `cron_etf_alpha_daily.py` | 每日 21:00 | ETF FQIR 评分 + 候选池输出 | 外部 crontab / 手动 |
| `cron_index_end_of_day.py` | 交易日 16:00 | 指数+成分股+北向资金采集 | 外部 crontab / 手动 |
| `cron_morning_briefing.py` | 工作日 06:30 | Morning Briefing 任务下发（Redis Stream） | OpenClaw cron 触发 |
| `cron_etf_kline_evening.py` | 每日晚间 | ETF 历史 K 线增量回补 | 外部 crontab / 手动 |
| `cron_etf_spot_intraday.py` | 日内刷新 | ETF 实时行情盘中更新 | 外部 crontab / 手动 |
| `cron_etf_spot_morning.py` | 开盘前 | ETF 早盘行情采集 | 外部 crontab / 手动 |
| `cron_woa_monitor.py` | — | WOA 监控任务 | 未明确调度 |
| `cron_woa_status.py` | — | WOA 状态轮询 | 未明确调度 |
| `cron_briefing_dispatch.py` | — | Briefing 分发 | 未明确调度 |
| `cron_etf_arbitrage_signal.py` | — | ETF 套利信号计算 | 未明确调度 |
| `cron_industry_info.py` | — | 行业信息更新 | 未明确调度 |

**关键发现：共 11 个 cron 脚本，但仅 4 个有明确调度时间（其余 7 个调度方式不明）。**

#### 12.1.2 调度架构评估

| 维度 | 现状 | 评分 | 说明 |
|------|------|:----:|------|
| **集中化程度** | ❌ 分散 | 1/5 | 各脚本独立加载 `.env` + `.secrets/tokens.env`，无统一调度入口 |
| **任务依赖管理** | ❌ 缺失 | 1/5 | 无 DAG 定义，`cron_index_end_of_day.py`（16:00）与 `cron_morning_briefing.py`（06:30）的时序关系未显式声明 |
| **执行状态追踪** | ❌ 缺失 | 1/5 | `scheduler_jobs` 表已定义但从未被任何脚本写入/读取 |
| **失败重试** | ❌ 缺失 | 1/5 | 无外部重试机制（如 systemd timer retry、supervisor restart） |
| **并发控制** | ⚠️ 部分 | 3/5 | Redis Stream 的 Consumer Group 机制可防止重复消费，但 cron 脚本间无互斥锁 |

#### 12.1.3 `scheduler_jobs` 表形同虚设

```sql
-- init-db/00_schema.sql L322 — 调度配置表已定义
CREATE TABLE scheduler_jobs (
    id              SERIAL PRIMARY KEY,
    job_name        VARCHAR(100) NOT NULL UNIQUE,
    job_type        VARCHAR(30)  NOT NULL,
    cron_expr       VARCHAR(100),
    enabled         BOOLEAN      DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    run_count       INT          DEFAULT 0,
    last_status     VARCHAR(20),   -- success/failed/skipped
    last_error      TEXT,
    config_json     JSONB,
    created_at      TIMESTAMPTZ  DEFAULT now(),
    updated_at      TIMESTAMPTZ  DEFAULT now()
);
```

**问题**: 
- 表结构完整（含 `last_run_at`、`next_run_at`、`run_count`、`last_status`），但代码中无任何 INSERT/UPDATE 逻辑
- 无法回答"上次执行是什么时候？""执行成功了吗？""累计执行了多少次？"等运维基本问题

**建议**: 
- **短期**：在每个 cron 脚本的 `run()` 函数入口/出口写入 `scheduler_jobs` 表
- **中期**：引入 APScheduler（已在 `.venv` 中）作为统一调度器，替代外部 crontab

---

### 12.2 采集审计分析

#### 12.2.1 `data_source_log` 表形同虚设

```sql
-- init-db/00_schema.sql L296 — 审计日志表已定义
CREATE TABLE data_source_log (
    id              SERIAL PRIMARY KEY,
    source_name     VARCHAR(100) NOT NULL,
    data_type       VARCHAR(30)  NOT NULL,
    batch_id        VARCHAR(50),
    status          VARCHAR(20),   -- success/partial/failed
    records_fetched INT,
    records_written INT,
    error_detail    TEXT,
    duration_ms     BIGINT,
    raw_storage_path TEXT,
    started_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT now()
);
```

**问题**: 
- **无任何代码向该表写入数据** — 审计表形同虚设
- 无 `batch_id` 生成机制，无法关联一次采集的多个步骤
- 无链路追踪 ID（trace_id），失败时无法追溯完整采集链

#### 12.2.2 现有日志覆盖度评估

| 脚本 | 日志文件 | 轮转策略 | 结构化程度 | 评分 |
|------|---------|---------|-----------|:----:|
| `cron_etf_alpha_daily.py` | `logs/cron_etf_alpha.log` | RotatingFileHandler(10MB/5) | ⚠️ 文本格式 | 3/5 |
| `cron_index_end_of_day.py` | `logs/cron_index_end_of_day.log` | RotatingFileHandler(10MB/5) | ⚠️ 文本格式 | 3/5 |
| `cron_morning_briefing.py` | ❌ 无文件日志 | 仅 stderr | ❌ 无持久化 | 1/5 |
| `health_check.sh` | ❌ 无日志 | stdout | ❌ 无持久化 | 1/5 |
| `run_health_monitor.sh` | ❌ 无日志 | 调用 etf_health_monitor.py | ⚠️ 依赖子进程 | 2/5 |

**关键发现**: 
- **仅 2 个 cron 脚本配置了文件日志**，其余脚本（包括 Morning Briefing）仅输出到 stderr
- 日志格式为纯文本，无法被 ELK/Loki 等日志聚合系统直接解析
- 无统一日志格式规范（JSON vs 文本混用）

---

### 12.3 可观测性分析

#### 12.3.1 健康检查覆盖度

| 检查项 | 实现位置 | 检查内容 | 告警机制 | 评分 |
|--------|---------|---------|---------|:----:|
| **PostgreSQL** | `docker-compose.yml` | `pg_isready` | Docker 内置 | ✅ 有 |
| **Redis** | `docker-compose.yml` | `redis-cli ping` | Docker 内置 | ✅ 有 |
| **MinIO** | `docker-compose.yml` | `mc ready local` | Docker 内置 | ✅ 有 |
| **ETF 数据健康** | `health_check.sh` | 今日 ETF 数 + K 线条数 + 因子信号数 | ❌ 仅 stdout | 2/5 |
| **ETF 监控** | `run_health_monitor.sh` → `etf_health_monitor.py` | IOPV/流动性/波动率 | ❌ 仅 print() | 2/5 |

**关键发现**: 
- Docker 层面的健康检查（PG/Redis/MinIO）已配置，但**应用层健康检查严重不足**
- `health_check.sh` 仅查询数据库记录数，无法判断数据质量（如：字段值域、跨源一致性）
- `etf_health_monitor.py` 的告警仅 `print()` 到 stdout，未持久化到统一表

#### 12.3.2 缺失的可观测性组件

| 组件 | 现状 | 优先级 | 说明 |
|------|------|:------:|------|
| **Prometheus 指标暴露** | ❌ 缺失 | 🔴 P0 | 无 `/metrics` 端点，无法接入 Prometheus/Grafana |
| **告警规则** | ❌ 缺失 | 🔴 P0 | 无 Alertmanager 配置，采集失败无人知晓 |
| **日志聚合** | ❌ 缺失 | 🟡 P1 | 日志分散在 `logs/` 目录，无 ELK/Loki |
| **分布式追踪** | ❌ 缺失 | 🟡 P1 | 无 OpenTelemetry/Jaeger，无法追踪跨脚本调用链 |
| **SLO 仪表盘** | ❌ 缺失 | 🟡 P1 | 无采集成功率、延迟等 SLO 指标展示 |
| **运行时指标收集** | ⚠️ 部分 | 🟢 P2 | `cron_etf_alpha_daily.py` 记录步骤耗时，但仅日志输出 |

---

### 12.4 容错与恢复分析

#### 12.4.1 现有容错机制

| 脚本 | 容错策略 | 降级方案 | 重试机制 | 评分 |
|------|---------|---------|---------|:----:|
| `cron_etf_alpha_daily.py` Step 2 | 子进程隔离 + 60s 超时 | ✅ 使用默认值 50.0 | ❌ 无 | 3/5 |
| `cron_index_end_of_day.py` | 每步 try/except | ⚠️ 记录 error 后继续 | ❌ 无 | 3/5 |
| `cron_morning_briefing.py` | Redis 连接检查 | ⚠️ 返回 exit code 1 | ❌ 无 | 2/5 |
| `health_check.sh` | ❌ 无异常处理 | — | ❌ 无 | 1/5 |

**关键发现**: 
- **唯一有降级策略的是 `cron_etf_alpha_daily.py` Step 2**（东财行业情绪接口超时 → 使用默认值 50.0）
- 其他脚本的 try/except 仅记录错误，不执行任何降级或重试
- 无死信队列、无断点续传、无失败通知机制

#### 12.4.2 幂等性分析

| 写入操作 | 幂等方式 | 风险 |
|---------|---------|------|
| `daily_quotes` | `ON CONFLICT (company_id, trade_date) DO UPDATE` | ✅ 安全 |
| `financial_reports` | `ON CONFLICT (company_id, report_date, report_type) DO UPDATE` | ✅ 安全 |
| `etf_quotes` | `ON CONFLICT (etf_id, trade_date) DO UPDATE` | ✅ 安全 |
| `north_flow_hist` | `ON CONFLICT (calc_date) DO UPDATE` | ✅ 安全 |
| `etf_alpha_signals` | `ON CONFLICT (etf_id, calc_date) DO UPDATE` | ✅ 安全 |
| **MinIO 存储** | ❌ 无去重 | ⚠️ 同名文件覆盖，无法判断是否已存档 |

---

### 12.5 MinIO Bronze 层分析

#### 12.5.1 现有 Bucket 与存储策略

| Bucket | 用途 | 存储格式 | 生命周期策略 |
|--------|------|---------|------------|
| `bronze-quotes` | 股票/ETF 行情原始数据 | `{prefix}/{date}.json` | ❌ 无 TTL/归档 |
| `bronze-financial` | 财报原始数据 | `{prefix}/{date}.json` | ❌ 无 TTL/归档 |
| `bronze-news` | 新闻原始数据 | `{prefix}/{date}.json` | ❌ 无 TTL/归档 |

**缺失的 Bucket（schema 中已定义但未实现）**:
- `bronze-social` — 社交媒体/舆情数据
- `silver-processed` — 清洗后的银层数据
- `gold-factors` — 因子计算结果

#### 12.5.2 MinIO 运维风险

| 风险项 | 严重度 | 说明 |
|--------|:------:|------|
| **无生命周期策略** | 🔴 P0 | 原始数据无限增长，无 TTL/归档/删除规则 |
| **无版本控制** | 🟡 P1 | 同名文件覆盖，无法回滚到历史版本 |
| **无旧数据清理** | 🟡 P1 | `logs/` 目录仅 5 轮转，MinIO 无清理机制 |
| **无存储监控** | 🔴 P0 | 无 MinIO 容量告警，磁盘满时采集将失败 |
| **无数据校验** | 🟡 P1 | 存入 MinIO 的 JSON 文件未做完整性校验（如 checksum） |

---

### 12.6 综合评估与改进建议

#### 12.6.1 评分汇总

| 维度 | 评分 (1-5) | 状态 |
|------|:----------:|------|
| **调度集中化** | 1 | ❌ 严重不足 — 11 个脚本分散执行，无统一调度器 |
| **采集审计** | 1 | ❌ 严重不足 — `data_source_log` 表未使用 |
| **可观测性** | 2 | ❌ 不足 — 仅 Docker 健康检查，无应用层指标/告警 |
| **容错与恢复** | 2 | ❌ 不足 — 仅 1 个脚本有降级策略，无重试机制 |
| **MinIO 生命周期** | 1 | ❌ 严重不足 — 无 TTL、无版本控制、无清理策略 |

#### 12.6.2 改进建议（按优先级排序）

##### 🔴 P0 — 立即修复

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 1 | **`data_source_log` 未使用** | 无法追踪采集质量 | 在 pipeline 每步完成后写入审计日志 | 2人日 |
| 2 | **无 Prometheus 指标暴露** | 无法接入监控体系 | 增加 `/metrics` 端点（prometheus-client） | 3人日 |
| 3 | **MinIO 无生命周期策略** | 存储无限增长 | 配置 MinIO ILM 规则（90天归档/Glacier） | 1人日 |
| 4 | **无失败通知机制** | 故障无人知晓 | 实现 Webhook 告警适配器（飞书/钉钉） | 2人日 |

##### 🟡 P1 — 短期优化

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 5 | **调度分散** | 运维困难 | 引入 APScheduler 统一调度，替代外部 crontab | 3人日 |
| 6 | **日志格式不统一** | 难以集中检索 | JSON 格式 + RotatingFileHandler 全局配置 | 1人日 |
| 7 | **`scheduler_jobs` 未使用** | 无法追踪任务执行 | cron 脚本入口/出口写入调度记录 | 1人日 |
| 8 | **MinIO 无版本控制** | 无法回滚数据 | 启用 MinIO 版本控制（mc versioning enable） | 0.5人日 |

##### 🟢 P2 — 中期规划

| # | 问题 | 影响 | 建议方案 | 预估工作量 |
|---|------|------|---------|-----------|
| 9 | **无日志聚合** | 日志分散难检索 | 部署 Loki + Grafana 或 ELK Stack | 5人日 |
| 10 | **无分布式追踪** | 无法追踪跨脚本调用链 | 集成 OpenTelemetry | 5人日 |
| 11 | **SLO 仪表盘缺失** | 无法量化系统可靠性 | 定义采集成功率/延迟 SLO + Grafana 面板 | 3人日 |
| 12 | **MinIO 存储监控** | 磁盘满时采集失败 | MinIO Prometheus 指标 + 容量告警 | 2人日 |

#### 12.6.3 推荐架构演进路线

```
当前状态 (Phase 0)              Phase 1 (短期)               Phase 2 (中期)
─────────────                  ─────────────                ─────────────
┌──────────────────┐          ┌──────────────────┐        ┌──────────────────┐
│ 外部 crontab     │          │ APScheduler      │        │ 统一调度平台      │
│ 11 个独立脚本    │   →      │ + scheduler_jobs │   →    │ + DAG 依赖管理   │
│ 无审计日志       │          │ + data_source_log│        │ + 任务编排       │
├──────────────────┤          ├──────────────────┤        ├──────────────────┤
│ Docker 健康检查  │          │ + Prometheus     │        │ + Grafana SLO    │
│ 无应用指标       │   →      │ + Alertmanager   │   →    │ + 告警路由       │
│ 日志分散         │          │ + JSON 日志格式  │        │ + Loki/ELK       │
├──────────────────┤          ├──────────────────┤        ├──────────────────┤
│ MinIO 无策略     │          │ + ILM 规则       │        │ + 多集群复制     │
│ 无版本控制       │   →      │ + 版本控制       │   →    │ + 跨地域容灾     │
│ 无清理机制       │          │ + 存储监控       │        │ + 成本优化       │
└──────────────────┘          └──────────────────┘        └──────────────────┘
```

---

*本报告由 sre-expert 基于代码静态分析生成，聚焦调度机制、可观测性、容错恢复和 MinIO 生命周期管理。与 data-arch-eng 的架构评估报告、code-quality-expert 的代码质量报告互补，共同构成数据采集层全面评估。*
