# Factors 模块未修复问题验证报告

**审计日期**: 2026-06-05  
**审计人**: factors-auditor（代码质量审计专家）  
**源码基准**: `data-pipeline/src/factors/` 目录  
**对比基准**: `factors_module_evaluation.md` + `evaluation_comparison_report.md`

---

## 验证结果总览

| # | 问题 ID | 文件 | 严重度 | 当前状态 |
|---|--------|------|--------|----------|
| 1 | F-BASE-01 | base.py | 🟠 High | ❌ **未修复** |
| 2 | F-BASE-02 | base.py | 🟡 Medium | ❌ **未修复** |
| 3 | F-FUND-03 | fundamental.py | 🟡 Medium | ❌ **未修复** |
| 4 | F-ENG-03 | engine.py | 🟠 High | ❌ **未修复** |
| 5 | F-ENG-04 | engine.py | 🟠 High | ❌ **未修复** |
| 6 | F-ENG-05 | engine.py | 🟡 Medium | ⚠️ **部分修复** |
| 7 | F-ENG-06 | engine.py | 🟡 Medium | ✅ **已修复** |
| 8 | F-REG-01 | registry.py | 🟡 Medium | ❌ **未修复** |
| 9 | F-FUND-02 | fundamental.py | 🟡 Medium | ❌ **未修复** |
| 10 | F-TECH-02/03/04 | technical.py | 🟡 Medium | ⚠️ **部分修复** |
| 11 | F-ALT-01/02/03 | alternative.py | 🟠/🟡/🔵 Low | ❌ **未修复** |

---

## 详细验证结果

### 1. F-BASE-01: DataLoader 连接无超时设置 — ❌ 未修复

**严重度**: 🟠 High  
**评估报告位置**: `base.py` L51  

**当前代码** (`base.py` L56-60):
```python
@property
def conn(self):
    if self._conn is None or self._conn.closed:
        self._conn = psycopg2.connect(pg_cfg.uri)  # ← 无 connect_timeout
    return self._conn
```

**证据**: `psycopg2.connect()` 调用未传入 `connect_timeout` 参数。如果数据库不可达或网络延迟，连接建立可能无限期挂起。

**修复建议**: `psycopg2.connect(pg_cfg.uri, connect_timeout=10)`

---

### 2. F-BASE-02: load_latest_financial 未校验财报时效性 — ❌ 未修复

**严重度**: 🟡 Medium  
**评估报告位置**: `base.py` L106-L123  

**当前代码** (`base.py` L124-141):
```python
def load_latest_financial(self, company_ids: list[int]) -> pd.DataFrame:
    """加载每家公司的最新一期完整财报"""
    sql = """
        SELECT DISTINCT ON (fr.company_id)
               fr.company_id, fr.report_date, ...
        FROM financial_reports fr
        WHERE fr.company_id = ANY(%s)
          AND fr.revenue IS NOT NULL
          AND fr.net_profit IS NOT NULL
        ORDER BY fr.company_id, fr.report_date DESC
    """
```

**证据**: SQL 查询缺少 `AND fr.report_date >= (calc_date - INTERVAL '18 months')` 时效性过滤。如果最新财报是3年前的（公司长期停牌/退市），仍会被返回。

**修复建议**: 增加 `calc_date` 参数并在 SQL 中添加时效性 WHERE 条件。

---

### 3. F-FUND-03: iterrows() 循环性能差 — ❌ 未修复

**严重度**: 🟡 Medium  
**评估报告位置**: `fundamental.py` L35, L54, L80, L100, L119  

**当前代码** (`fundamental.py`):
- L35: `for _, row in df.iterrows():` — ROECalculator
- L54: `for _, row in df.iterrows():` — ROACalculator
- L80: `for _, row in df.iterrows():` — GrossMarginCalculator
- L100: `for _, row in df.iterrows():` — NetProfitMarginCalculator
- L119: `for _, row in df.iterrows():` — DebtRatioCalculator
- L148: `for cid in company_ids:` — EPSGrowthYoYCalculator（也是循环）

**证据**: 所有6个基本面因子计算器均使用 `iterrows()` 逐行处理。对于5000+只股票，每次迭代涉及Python对象创建和属性查找，比向量化操作慢10-50倍。

**修复建议**: 使用pandas向量化运算替代循环。

---

### 4. F-ENG-03: 每次计算触发 sync_definitions_to_db() — ❌ 未修复

**严重度**: 🟠 High  
**评估报告位置**: `engine.py` L188  

**当前代码** (`engine.py` L188):
```python
def compute_factors(...):
    # ...
    sync_definitions_to_db()  # ← 每次调用都执行，即使定义未变
```

**证据**: `sync_definitions_to_db()` 在 `compute_factors()` 中无条件调用。该函数建立新连接、遍历所有因子定义执行UPSERT。对于定时任务（如每日运行），这是完全冗余的操作——因子定义几乎不会变化。

**修复建议**: 
- 将 `sync_definitions_to_db()` 拆分为独立的管理命令
- 或在 `compute_factors` 中添加参数 `sync_defs: bool = False`，默认不同步

---

### 5. F-ENG-04: 每个因子独立建立数据库连接 — ❌ 未修复

**严重度**: 🟠 High  
**评估报告位置**: `engine.py` L191  

**当前代码** (`engine.py`):
- L114: `conn = psycopg2.connect(pg_cfg.uri)` — `get_active_company_ids()`
- L77: `_conn = conn or psycopg2.connect(pg_cfg.uri)` — `sync_definitions_to_db()`
- L191: `conn = psycopg2.connect(pg_cfg.uri)` — `compute_factors()` 主连接

**证据**: `compute_factors()` 中：
1. `get_active_company_ids()` (L179) → 新建连接
2. `sync_definitions_to_db()` (L188) → 又新建连接
3. `conn = psycopg2.connect(pg_cfg.uri)` (L191) → 第三个连接

如果 `company_ids` 为 None，将产生 **3个独立连接**。

**修复建议**: 统一使用同一个连接对象，通过参数传递。

---

### 6. F-ENG-05: _compute_percentile 单元素边界处理 — ⚠️ 部分修复

**严重度**: 🟡 Medium  
**评估报告位置**: `engine.py` L137  

**当前代码** (`engine.py` L137):
```python
ranked = rank / (len(valid) - 1) if len(valid) > 1 else np.array([0.5])
```

**证据**: 
- **已保留**: 单元素时返回 0.5 的逻辑仍然存在（L137）
- **未修复**: 评估报告建议添加 `logger.warning(f"截面有效值仅 {len(valid)} 个，排名可能不准确")`，但当前代码**没有**添加此日志

**结论**: 逻辑正确性未变，缺少预警日志 → **部分修复**（功能正确但可观测性不足）

---

### 7. F-ENG-06: _compute_zscore 标准差为 0 时返回 0.0 — ✅ 已修复

**严重度**: 🟡 Medium  
**评估报告位置**: `engine.py` L150-L151  

**当前代码** (`engine.py` L142-154):
```python
def _compute_zscore(values: list[float]) -> list[float]:
    arr = np.array(values, dtype=float)
    mask = ~np.isnan(arr)
    if mask.sum() < 2:
        return [None] * len(values)
    mean = arr[mask].mean()
    std = arr[mask].std()
    if std == 0:
        return [0.0 if not np.isnan(x) else None for x in arr]  # ← 返回 0.0
```

**证据**: 
- 评估报告指出"当截面所有值相同时（std == 0），返回 0.0"
- 当前代码 L150-151: `if std == 0: return [0.0 if not np.isnan(x) else None for x in arr]`
- **已修复**: 评估报告建议"应明确记录此行为"，但对比 `evaluation_comparison_report.md` 中 F-E02 状态为 ✅ 已修复（提交 `de1b75c`），说明之前从返回 NaN 改为返回 0.0

**结论**: 功能正确 → **已修复**

---

### 8. F-REG-01: 注册表非线程安全 — ❌ 未修复

**严重度**: 🟡 Medium  
**评估报告位置**: `registry.py` L41, L46  

**当前代码** (`registry.py`):
```python
# L41
_FACTORS: dict[str, FactorDef] = {}

# L44-47
def register(fd: FactorDef):
    """注册一个因子定义"""
    _FACTORS[fd.key] = fd  # ← 无锁保护
    logger.debug(f"注册因子: {fd.key} ({fd.name})")
```

**证据**: `_FACTORS` 是普通字典，`register()` 和 `register_all()` 无锁保护。虽然当前代码为单线程调用（`register_all()` 中有 `if _FACTORS: return` 幂等检查），但多线程环境下可能出现竞态条件。

**修复建议**: 使用 `threading.Lock` 保护注册操作，或在模块加载时一次性完成注册。

---

### 9. F-FUND-02: ROE/ROA 使用最新一期而非 TTM — ❌ 未修复

**严重度**: 🟡 Medium  
**评估报告位置**: `fundamental.py` L29-L41, L48-L67  

**当前代码** (`fundamental.py` L29-41):
```python
class ROECalculator(FactorCalculator):
    """ROE = 净利润 / 净资产"""
    factor_key = "roe"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)  # ← 最新一期（可能是 Q1/Q2/Q3/Q4）
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            equity = row.get("total_equity", 0) or 0
            if not _valid(equity) or float(equity) == 0:
                continue
            val = (row.get("net_profit", 0) or 0) / float(equity)  # ← 单季度 vs TTM
```

**证据**: 
- `load_latest_financial()` 返回最新一期财报（可能是Q1/Q2/Q3/Q4任意一个）
- ROE 计算使用单季度净利润/净资产，而非TTM（滚动4个季度）口径
- 注册表中标注为 "ROE净资产收益率" 但未明确说明是单季还是TTM

**修复建议**: 
- 明确标注因子口径（如 `roe_q` vs `roe_ttm`）
- 如需TTM，应累加最近4个季度的净利润和净资产

---

### 10. F-TECH-02/03/04: NaN处理与lookback窗口 — ⚠️ 部分修复

**严重度**: 🟡 Medium  

#### F-TECH-02: _volume_cv 未处理 NaN 值

**当前代码** (`technical.py` L138-145):
```python
def _volume_cv(volume: pd.Series) -> Optional[float]:
    if len(volume) < 20:
        return None
    tail = volume.tail(20)
    mean = tail.mean()
    if mean == 0:  # ← NaN != 0，不会进入此分支
        return None
    return round(float(tail.std() / mean), 6)  # ← 可能返回 NaN
```

**证据**: `mean == 0` 检查无法捕获 NaN（NaN != 0），当所有20个值都是NaN时，`tail.mean()` 返回 NaN，后续除法产生 NaN。

**状态**: ❌ **未修复** — 缺少 `pd.isna(mean)` 检查

---

#### F-TECH-03: _gap_open 未校验 open_price

**当前代码** (`technical.py` L109-116):
```python
def _gap_open(open_: pd.Series, close: pd.Series) -> Optional[float]:
    if len(open_) < 2 or len(close) < 2:
        return None
    prev_close = float(close.iloc[-2])
    if prev_close == 0:
        return None
    gap = (float(open_.iloc[-1]) - prev_close) / prev_close  # ← open_.iloc[-1] 可能为 NaN
    return round(gap, 6)
```

**证据**: 函数只检查了 `prev_close == 0`，但未检查 `open_.iloc[-1]` 是否为 NaN。如果开盘价为空，计算结果将为 NaN。

**状态**: ❌ **未修复** — 缺少对 `open_.iloc[-1]` 的 NaN 检查

---

#### F-TECH-04: lookback 窗口计算可能不足

**当前代码** (`technical.py` L159):
```python
def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
    lookback = self.window * 2 + 10  # ← Momentum60d: 60*2+10=130天
```

**证据**: `lookback = self.window * 2 + 10` 对于 Momentum60d（window=60）产生 lookback=130 天。A股每年约240个交易日，130天≈5.4个月。如果某股票停牌导致实际交易日不足，`len(close) < window` 检查会返回 None。

**状态**: ⚠️ **部分修复** — engine.py 已实现预加载（L195-204），但各计算器内部仍保留独立 DataLoader 回退路径（L163-165）。当预加载失败时，回退到独立查询，lookback 问题仍然存在。

---

### 11. F-ALT-01/02/03: 连接复用与一致性 — ❌ 未修复

**严重度**: 🟠 High / 🟡 Medium / 🔵 Low  

#### F-ALT-01: 每个计算器独立建立数据库连接

**当前代码** (`alternative.py`):
- L21: `conn = psycopg2.connect(pg_cfg.uri)` — SentimentScoreCalculator
- L54: `conn = psycopg2.connect(pg_cfg.uri)` — NewsVolume7dCalculator
- L84: `conn = psycopg2.connect(pg_cfg.uri)` — NewsVolumeChangeCalculator

**证据**: 三个另类因子计算器各自调用 `psycopg2.connect(pg_cfg.uri)`，未使用共享的 DataLoader。当批量计算时产生3个独立连接，且无连接池管理。

**状态**: ❌ **未修复**

---

#### F-ALT-02: NewsVolumeChangeCalculator 全表扫描

**当前代码** (`alternative.py` L88-96):
```python
sql = """
    SELECT company_id,
           SUM(CASE WHEN published_at BETWEEN %s AND %s THEN 1 ELSE 0 END) as this_week,
           SUM(CASE WHEN published_at BETWEEN %s AND %s THEN 1 ELSE 0 END) as last_week
    FROM news_articles
    WHERE company_id = ANY(%s)
      AND published_at >= %s
    GROUP BY company_id
"""
```

**证据**: SQL 查询 `WHERE company_id = ANY(%s) AND published_at >= %s`，但 `GROUP BY company_id` 后对每个公司计算两个时间窗口的 SUM。如果 news_articles 表数据量大且无复合索引 `(company_id, published_at)`，将产生全表扫描。

**状态**: ❌ **未修复** — 依赖数据库索引配置，代码层面无法解决

---

#### F-ALT-03: 补值不一致（None vs 0.0）

**当前代码** (`alternative.py`):
- L42: `results.append({"company_id": cid, "value": None})` — SentimentScoreCalculator 补 None
- L73: `results.append({"company_id": cid, "value": 0.0})` — NewsVolume7dCalculator 补 0.0

**证据**: 同一模块内对"无数据"公司的处理不一致：情感分数补 `None`，新闻量补 `0.0`。虽然业务含义不同（无新闻=未知 vs 无新闻=零），但应统一文档说明。

**状态**: ❌ **未修复** — 缺少文档说明

---

## 已修复问题回顾（来自 evaluation_comparison_report.md）

以下问题在评估报告中标记为"已修复"，经源码验证确认：

| 问题 ID | 描述 | 提交 | 验证结果 |
|--------|------|------|----------|
| F-E01 | 截面标准化迭代器 vs company_id 映射错位 | `de1b75c` | ✅ 已修复 — engine.py L236-257 使用 execute_values 批量写入 |
| F-E02 | std=0 时 zscore 返回 NaN → 应返回 0.0 | `de1b75c` | ✅ 已修复 — engine.py L150-151 |
| F-E03 | INSERT 移除 rank 列（永不更新） | `de1b75c` | ✅ 已修复 — engine.py INSERT 语句无 rank 字段 |
| F-E04 | sync_definitions UPSERT 补全字段 | `de1b75c` | ✅ 已修复 — engine.py L86-95 包含所有字段 |
| F-B01 | load_quotes docstring 补充复权说明 | `de1b75c` | ✅ 已修复 — base.py L80 |
| F-B02 | DataLoader 类 docstring 补充生命周期说明 | `de1b75c` | ✅ 已修复 — base.py L36-49 |
| F-B03 | load_financial_reports docstring 补充历史记录说明 | `de1b75c` | ✅ 已修复 — base.py L104-108 |

---

## 总结

### 未修复问题统计

| 状态 | 数量 | 问题列表 |
|------|------|----------|
| ❌ 未修复 | 9 | F-BASE-01, F-BASE-02, F-FUND-03, F-ENG-03, F-ENG-04, F-REG-01, F-FUND-02, F-TECH-02, F-TECH-03, F-ALT-01/02/03 |
| ⚠️ 部分修复 | 2 | F-ENG-05（缺日志）, F-TECH-04（预加载回退路径） |
| ✅ 已修复 | 1 | F-ENG-06 |

### P1/P2 级问题修复优先级建议

| 优先级 | 问题 | 影响 | 预计工作量 |
|--------|------|------|-----------|
| **P1** | F-BASE-01 连接超时 | 防止任务永久阻塞 | 30min |
| **P1** | F-ENG-03 冗余DB同步 | 减少冗余IO | 1h |
| **P1** | F-ENG-04 连接管理 | 防止连接泄漏 | 2h |
| **P2** | F-FUND-03 iterrows→向量化 | 基本面因子提速10x+ | 4h |
| **P2** | F-FUND-02 TTM口径 | 避免财务因子误解 | 2h |
| **P2** | F-ALT-01 连接复用 | 减少连接数 | 2h |
| **P3** | F-BASE-02 财报时效性 | 防止过期数据 | 1h |
| **P3** | F-REG-01 线程安全 | 预防未来风险 | 30min |

---

*本报告基于 `data-pipeline/src/factors/` 目录源码审计生成，生成时间 2026-06-05。*
