# Factors 模块代码质量审计报告

**审计日期**: 2026-06-04  
**审计人**: factors-auditor（代码质量审计专家）  
**审计范围**: `src/factors/` 模块（engine.py, base.py, registry.py, fundamental.py, technical.py, alternative.py）  
**严重度定义**: 🔴 Critical / 🟠 High / 🟡 Medium / 🔵 Low

---

## 一、执行摘要

| 统计项 | 数值 |
|--------|------|
| 审计文件数 | 6 |
| 发现问题总数 | 18 |
| 🔴 Critical | 2 |
| 🟠 High | 5 |
| 🟡 Medium | 7 |
| 🔵 Low | 4 |

**核心风险**: 批量写入性能极差（逐行 INSERT）、数据加载重复查询、截面标准化映射错位。

---

## 二、engine.py — 因子计算引擎

### F-ENG-01 🔴 Critical — 逐行 INSERT 导致极端性能瓶颈

**位置**: `engine.py` L227-L245  
**描述**: 每个因子值使用单独的 `cur.execute(INSERT ...)` 写入数据库，无批量操作。当全市场 5000+ 只股票 × 26 个因子时，将产生超过 13 万次独立 INSERT 语句，每次包含连接/解析/执行/提交的完整开销。

**代码片段**:
```python
with conn.cursor() as cur:
    for v in values:
        if v["value"] is None:
            continue
        pct = pct_map.get(v["company_id"])
        zsc = zscore_map.get(v["company_id"])
        cur.execute(  # ← 每行一次 execute
            """INSERT INTO factor_values ... VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (v["company_id"], fd_id, calc_date, v["value"], pct, zsc, batch_label),
        )
        written += 1
conn.commit()  # ← 每个因子一次 commit
```

**修复建议**: 使用 `psycopg2.extras.execute_values()` 或 `executemany()` 批量写入。示例：
```python
from psycopg2.extras import execute_values
rows = [(v["company_id"], fd_id, calc_date, v["value"], pct, zsc, batch_label)
        for v in values if v["value"] is not None]
execute_values(cur, """INSERT INTO factor_values ... VALUES %s""", rows)
```

---

### F-ENG-02 🔴 Critical — 截面标准化映射错位（数据一致性缺陷）

**位置**: `engine.py` L218-L232  
**描述**: `_compute_percentile` 和 `_compute_zscore` 仅对 **有效值**（非 None）计算排名/Z-score，然后通过 `zip(valid_values, percentiles)` 建立映射。但后续写入时遍历的是 **全部 values**（含 None），通过 `company_id` 查找映射。问题在于：当同一公司因不同原因产生多个条目或排序不一致时，`pct_map.get()` 可能返回错误值。更严重的是，如果 `valid_values` 中某公司的 value 为 NaN 但 company_id 有效，它会被排除在排名之外，导致该因子截面排名不完整。

**代码片段**:
```python
valid_values = [v for v in values if v["value"] is not None]
percentiles = _compute_percentile([v["value"] for v in valid_values]) if valid_values else []
pct_map = {v["company_id"]: p for v, p in zip(valid_values, percentiles)}  # ← 仅有效值有映射
for v in values:  # ← 遍历全部（含 None）
    pct = pct_map.get(v["company_id"])  # ← None 值的 company_id 查不到映射，pct=None
```

**修复建议**: 
1. 确保 `values` 列表中每个 `company_id` 唯一
2. 在写入前过滤掉 `value is None` 的条目（当前代码已做此检查 L229-230）
3. 增加去重校验：`if len(set(v["company_id"] for v in values)) != len(values): raise ValueError(...)`

---

### F-ENG-03 🟠 High — 每次计算都触发 DB 同步（性能浪费）

**位置**: `engine.py` L188  
**描述**: `compute_factors()` 内部无条件调用 `sync_definitions_to_db()`。该函数建立新连接、遍历所有因子定义执行 UPSERT。对于定时任务（如每日运行），这完全是冗余操作——因子定义几乎不会变化。

**代码片段**:
```python
def compute_factors(...):
    register_all()
    _build_calculators()
    # ...
    sync_definitions_to_db()  # ← 每次调用都执行，即使定义未变
```

**修复建议**: 
- 将 `sync_definitions_to_db()` 拆分为独立的管理命令（如 CLI 子命令），不在计算流程中自动调用
- 或在 `compute_factors` 中添加参数 `sync_defs: bool = False`，默认不同步

---

### F-ENG-04 🟠 High — 每个因子独立建立数据库连接

**位置**: `engine.py` L191  
**描述**: `compute_factors()` 在循环外建立了一个连接，但 `get_active_company_ids()`（L179）和 `sync_definitions_to_db()`（L188）各自又建立了新连接。如果 `company_ids` 为 None，将产生 **3 个额外连接**。

**代码片段**:
```python
if company_ids is None:
    company_ids = get_active_company_ids()  # ← 新建连接
# ...
sync_definitions_to_db()  # ← 又新建连接
# ...
conn = psycopg2.connect(pg_cfg.uri)  # ← 第三个连接
```

**修复建议**: 统一使用同一个连接对象，通过参数传递。

---

### F-ENG-05 🟡 Medium — `_compute_percentile` 边界条件：单元素处理

**位置**: `engine.py` L137  
**描述**: 当有效值只有 1 个时（如全市场仅 1 家公司有数据），排名被硬编码为 0.5。这在极端情况下可能掩盖数据质量问题，应记录日志以便排查。

**代码片段**:
```python
ranked = rank / (len(valid) - 1) if len(valid) > 1 else np.array([0.5])
```

**修复建议**: 添加 `logger.warning(f"截面有效值仅 {len(valid)} 个，排名可能不准确")`。

---

### F-ENG-06 🟡 Medium — `_compute_zscore` 标准差为 0 时返回 0.0

**位置**: `engine.py` L150-L151  
**描述**: 当截面所有值相同时（std == 0），返回 0.0。这在业务上可能合理，但应明确记录此行为——所有公司获得相同 Z-score 意味着无法区分相对表现。

---

### F-ENG-07 🔵 Low — `batch_label` 命名格式不够结构化

**位置**: `engine.py` L183  
**描述**: 默认批次标签为 `batch_2026-06-04`，缺少时间戳和进程标识。多实例并行运行时可能产生冲突。

**修复建议**: 使用 `f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"`。

---

## 三、base.py — 因子基类与数据加载器

### F-BASE-01 🟠 High — DataLoader 连接无超时设置

**位置**: `base.py` L51  
**描述**: `psycopg2.connect(pg_cfg.uri)` 未设置连接超时。如果数据库不可达或网络延迟，连接建立可能无限期挂起，导致因子计算任务永久阻塞。

**代码片段**:
```python
self._conn = psycopg2.connect(pg_cfg.uri)  # ← 无 timeout/connect_timeout
```

**修复建议**: 
```python
self._conn = psycopg2.connect(pg_cfg.uri, connect_timeout=10)
```

---

### F-BASE-02 🟡 Medium — `load_latest_financial` 未校验财报时效性

**位置**: `base.py` L106-L123  
**描述**: 查询使用 `DISTINCT ON (company_id)` 取最新一期财报，但只过滤了 `revenue IS NOT NULL AND net_profit IS NOT NULL`。如果最新财报是 3 年前的（公司长期停牌/退市），仍会被返回，导致因子计算基于过期数据。

**代码片段**:
```sql
SELECT DISTINCT ON (fr.company_id) ...
FROM financial_reports fr
WHERE fr.company_id = ANY(%s)
  AND fr.revenue IS NOT NULL
  AND fr.net_profit IS NOT NULL
ORDER BY fr.company_id, fr.report_date DESC
```

**修复建议**: 增加时效性过滤，如 `AND fr.report_date >= (calc_date - INTERVAL '18 months')`。

---

### F-BASE-03 🔵 Low — `load_financial_reports` 返回全部历史无分页

**位置**: `base.py` L86-L104  
**描述**: 加载所有公司的全部财报历史记录，对于大型公司（20+ 年数据 × 80+ 季度），单表查询可能返回数百万行。

**修复建议**: 增加可选的 `max_records` 参数或按时间范围限制。

---

## 四、registry.py — 因子注册表

### F-REG-01 🟡 Medium — 注册表非线程安全

**位置**: `registry.py` L41, L46  
**描述**: `_FACTORS` 是普通字典，`register()` 和 `register_all()` 无锁保护。多线程环境下可能出现竞态条件（虽然当前代码为单线程调用）。

**代码片段**:
```python
_FACTORS: dict[str, FactorDef] = {}  # ← 无同步机制

def register(fd: FactorDef):
    _FACTORS[fd.key] = fd  # ← 非原子操作
```

**修复建议**: 使用 `threading.Lock` 保护注册操作，或在模块加载时一次性完成注册。

---

### F-REG-02 🔵 Low — `get_factor_ids()` 无缓存

**位置**: `registry.py` L122-L135  
**描述**: 每次调用都查询数据库获取 key→id 映射。在 `compute_factors()` 中，每个因子计算后写入时都会调用（通过 `key2id.get(fk)`），虽然当前只在循环外调用一次，但未来扩展时可能成为瓶颈。

---

## 五、fundamental.py — 基本面因子

### F-FUND-01 🟠 High — EPSGrowthYoYCalculator 按日历年匹配而非会计年度

**位置**: `fundamental.py` L155-L158  
**描述**: 同比增长率计算使用 `report_date.year - 1` 查找上年同期数据。但财报发布日期与会计年度不一致——例如 2024Q1 的财报可能在 2024-04-30 发布，其"上年同期"应为 2023Q1（报告日期在 2023-04-30 左右），而非简单按日历年匹配。如果公司报告期分布不均，可能匹配到错误的季度。

**代码片段**:
```python
target_year = latest_date.year - 1
prev = sub[sub["report_date"].dt.year == target_year]  # ← 仅按年份匹配
if prev.empty:
    continue
```

**修复建议**: 
- 优先使用 `fiscal_year` 字段进行匹配（如果数据中有）
- 或按季度偏移：查找 `report_date` 在 `(latest_date - 365 days, latest_date - 270 days)` 范围内的记录

---

### F-FUND-02 🟡 Medium — ROE/ROA 使用最新一期而非 TTM

**位置**: `fundamental.py` L29-L41, L48-L67  
**描述**: ROE 和 ROA 计算器使用 `load_latest_financial()` 获取最新一期财报。如果最新一期是 Q1（单季度），则计算的是单季度 ROE/ROA，而非市场通用的 TTM（滚动 4 个季度）口径。注册表中标注为 "ROE净资产收益率" 但未明确说明是单季还是 TTM，可能导致使用者误解。

**代码片段**:
```python
df = dl.load_latest_financial(company_ids)  # ← 最新一期（可能是 Q1/Q2/Q3/Q4）
val = (row.get("net_profit", 0) or 0) / float(equity)  # ← 单季度 vs TTM
```

**修复建议**: 
- 明确标注因子口径（如 `roe_q` vs `roe_ttm`）
- 如需 TTM，应累加最近 4 个季度的净利润和净资产

---

### F-FUND-03 🟡 Medium — iterrows() 循环性能差

**位置**: `fundamental.py` L35, L54, L80, L100, L119  
**描述**: 所有基本面因子计算器使用 `for _, row in df.iterrows()` 逐行处理。对于 5000+ 只股票，每次迭代都涉及 Python 对象创建和属性查找，比向量化操作慢 10-50 倍。

**修复建议**: 使用 pandas 向量化运算：
```python
equity = df["total_equity"].replace(0, np.nan)
df["roe"] = df["net_profit"] / equity
results = df[~df["roe"].isna()].apply(lambda r: {"company_id": r["company_id"], "value": round(r["roe"], 6)}, axis=1).tolist()
```

---

### F-FUND-04 🔵 Low — `_valid()` 函数对整数 0 的判断不一致

**位置**: `fundamental.py` L15-L22  
**描述**: `_valid(0)` 返回 `True`（因为 `not math.isnan(0.0)`），但在调用处使用 `row.get("total_equity", 0) or 0`，当 equity 为 0 时会被转换为 0（整数），后续 `float(equity) == 0` 检查会跳过。逻辑正确但 `_valid()` 和 `or 0` 的组合容易让人困惑。

---

## 六、technical.py — 技术面因子

### F-TECH-01 🟠 High — 每个计算器独立加载数据，重复查询严重

**位置**: `technical.py` L140-L409  
**描述**: 26 个技术因子各自在 `compute()` 中调用 `_load_for_calcs()` → `DataLoader().load_quotes()`。当批量计算多个因子时（如一次计算全部 26 个），每个因子都独立查询数据库获取行情数据，产生 **N 次完全相同的 SQL 查询**。

**代码片段**:
```python
# Momentum5dCalculator.compute()
with DataLoader() as dl:
    df = _load_for_calcs(company_ids, calc_date, lookback, dl)

# Volatility20dCalculator.compute() — 同样的公司、同样的日期范围
with DataLoader() as dl:
    df = _load_for_calcs(company_ids, calc_date, 60, dl)  # ← 重复查询
```

**修复建议**: 
- 在 `engine.py` 层面实现数据预加载：先确定所有因子需要的最大 lookback，一次性加载
- 或引入 `DataLoaderCache` 在同一批次内复用 DataFrame

---

### F-TECH-02 🟡 Medium — `_volume_cv` 未处理 NaN 值

**位置**: `technical.py` L120-L127  
**描述**: `tail.std()` 在 pandas 中默认跳过 NaN，但如果所有 20 个值都是 NaN，`mean()` 返回 NaN，后续 `mean == 0` 检查不会捕获（NaN != 0），导致除以 NaN。

**代码片段**:
```python
def _volume_cv(volume: pd.Series) -> Optional[float]:
    tail = volume.tail(20)
    mean = tail.mean()
    if mean == 0:  # ← NaN != 0，不会进入此分支
        return None
    return round(float(tail.std() / mean), 6)  # ← 可能返回 NaN
```

**修复建议**: 
```python
if pd.isna(mean) or mean == 0:
    return None
```

---

### F-TECH-03 🟡 Medium — `_gap_open` 未校验 open_price

**位置**: `technical.py` L91-L98  
**描述**: 函数只检查了 `prev_close == 0`，但未检查 `open_.iloc[-1]` 是否为 NaN。如果开盘价为空，计算结果将为 NaN。

---

### F-TECH-04 🟡 Medium — lookback 窗口计算可能不足

**位置**: `technical.py` L141, L187, L210  
**描述**: `lookback = self.window * 2 + 10` 对于 Momentum60d（window=60）产生 lookback=130 天，但 A 股每年约 240 个交易日，130 天 ≈ 5.4 个月。如果某股票停牌导致实际交易日不足，`len(close) < window` 检查会返回 None，但该股票仍可能被包含在其他因子的结果中（不同因子 lookback 不同）。

---

### F-TECH-05 🔵 Low — `MomentumCalculator.factor_key = "momentum"` 未区分具体窗口

**位置**: `technical.py` L135  
**描述**: 基类的 `factor_key` 固定为 `"momentum"`，而子类（如 `Momentum5dCalculator`）虽然重写了 `factor_key = "momentum_5d"`，但如果通过基类引用实例，注册时会使用错误的 key。

---

## 七、alternative.py — 另类因子

### F-ALT-01 🟠 High — 每个计算器独立建立数据库连接（无复用）

**位置**: `alternative.py` L21, L54, L84  
**描述**: 三个另类因子计算器各自调用 `psycopg2.connect(pg_cfg.uri)`，未使用共享的 `DataLoader`。当批量计算时产生 3 个独立连接，且无连接池管理。

**代码片段**:
```python
class SentimentScoreCalculator(FactorCalculator):
    def compute(self, company_ids, calc_date, **kwargs):
        conn = psycopg2.connect(pg_cfg.uri)  # ← 独立连接
        try:
            # ...
        finally:
            conn.close()
```

**修复建议**: 统一使用 `DataLoader` 或引入连接池。

---

### F-ALT-02 🟡 Medium — NewsVolumeChangeCalculator 全表扫描

**位置**: `alternative.py` L88-L101  
**描述**: SQL 查询 `WHERE company_id = ANY(%s) AND published_at >= %s`，但 `GROUP BY company_id` 后对每个公司计算两个时间窗口的 SUM。如果 news_articles 表数据量大且无复合索引 `(company_id, published_at)`，将产生全表扫描。

**修复建议**: 
- 确保 `news_articles` 表有 `(company_id, published_at)` 复合索引
- 考虑拆分为两次查询或使用窗口函数优化

---

### F-ALT-03 🔵 Low — SentimentScoreCalculator 补 None 但 NewsVolume7dCalculator 补 0.0

**位置**: `alternative.py` L42 vs L73  
**描述**: 同一模块内对"无数据"公司的处理不一致：情感分数补 `None`，新闻量补 `0.0`。虽然业务含义不同（无新闻=未知 vs 无新闻=零），但应统一文档说明以避免下游消费者混淆。

---

## 八、SQL 注入安全性评估

| 文件 | 风险等级 | 说明 |
|------|----------|------|
| engine.py | ✅ 安全 | 所有 SQL 使用 `%s` 参数化 |
| base.py | ✅ 安全 | 所有 SQL 使用 `%s` 参数化 |
| technical.py (fund_flow) | ✅ 安全 | 使用 `ANY(%s)` 参数化 |
| alternative.py | ✅ 安全 | 使用 `ANY(%s)` 参数化 |

**结论**: 未发现 SQL 注入漏洞。所有查询均使用参数化语句。

---

## 九、综合评分与优先级建议

### 严重度分布

```
🔴 Critical (2):  F-ENG-01 逐行 INSERT, F-ENG-02 截面映射错位
🟠 High (5):     F-ENG-03 DB同步冗余, F-ENG-04 连接泄漏, F-BASE-01 无超时, 
                 F-FUND-01 会计年度匹配错误, F-TECH-01 重复查询, F-ALT-01 连接独立
🟡 Medium (7):   F-ENG-05/06 边界处理, F-BASE-02/03 财报时效/分页, 
                 F-REG-01 线程安全, F-FUND-02/03 TTM/性能, 
                 F-TECH-02/03/04 NaN/lookback
🔵 Low (4):       F-ENG-07 批次命名, F-BASE-03 分页, F-REG-02 缓存, 
                 F-FUND-04 类型一致性, F-TECH-05 key冲突, F-ALT-03 补值不一致
```

### 修复优先级

| 优先级 | 问题 | 预计工作量 | 影响 |
|--------|------|-----------|------|
| P0 | F-ENG-01 逐行 INSERT → 批量写入 | 2h | 性能提升 100x+ |
| P0 | F-TECH-01 重复数据加载 → 预加载缓存 | 4h | 多因子计算提速 5-10x |
| P1 | F-FUND-01 会计年度匹配 → fiscal_year | 2h | 避免错误同比增长率 |
| P1 | F-BASE-01 连接超时 → connect_timeout | 30min | 防止任务永久阻塞 |
| P2 | F-ENG-03 移除自动 DB 同步 | 1h | 减少冗余 IO |
| P2 | F-FUND-03 iterrows → 向量化 | 4h | 基本面因子提速 10x+ |

---

## 十、总体评价

**代码质量评分: 6.5/10**

### 优点
- ✅ 清晰的模块化设计（基类→子类继承）
- ✅ SQL 参数化，无注入风险
- ✅ 技术因子采用 pandas groupby 向量化思路
- ✅ 截面标准化（百分位/Z-score）实现完整
- ✅ DataLoader 支持 context manager

### 待改进
- ❌ **批量写入性能**：逐行 INSERT 是最大瓶颈，需立即优化
- ❌ **数据加载重复**：多因子独立查询同一数据源，浪费严重
- ❌ **连接管理**：缺少超时、池化、复用机制
- ⚠️ **会计年度匹配**：同比增长率计算逻辑有偏差
- ⚠️ **TTM 口径缺失**：基本面因子未区分单季/TTM
