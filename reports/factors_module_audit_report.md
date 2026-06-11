# Factors 模块代码质量审计报告

**审计人**: factors-auditor  
**审计日期**: 2026-06-05  
**审计范围**: `data-pipeline/src/factors/` 模块（engine.py, base.py, registry.py, fundamental.py, technical.py, alternative.py, advanced.py）  
**源码版本**: invest-infra 仓库

---

## 一、问题汇总

| 优先级 | 问题 ID | 描述 | 状态 |
|--------|---------|------|------|
| 🔴 High | F-BASE-01 | DataLoader 连接仅有 connect_timeout，缺少 socket/查询超时 | ✅ 部分修复 |
| 🔴 High | F-ENG-03 | 每次计算触发 sync_definitions_to_db() | ❌ 仍存在 |
| 🔴 High | F-ENG-04 | 部分因子计算器独立建立数据库连接 | ❌ 仍存在 |
| 🟡 Medium | F-BASE-02 | load_latest_financial 未校验财报时效性 | ❌ 仍存在 |
| 🟡 Medium | F-FUND-02 | ROE/ROA 使用最新一期而非 TTM | ❌ 仍存在 |
| 🟡 Medium | F-FUND-03 | iterrows() 循环性能差 | ❌ 仍存在 |
| 🟡 Medium | F-ENG-05 | _compute_percentile 单元素边界缺日志 | ❌ 仍存在 |
| 🟡 Medium | F-REG-01 | 注册表非线程安全 | ❌ 仍存在 |
| 🟡 Medium | F-TECH-02/03 | NaN 处理不一致 | ⚠️ 部分存在 |
| 🟡 Medium | F-ALT-01/02/03 | 连接复用与一致性问题 | ❌ 仍存在 |

---

## 二、逐项验证详情

### 🔴 High 优先级问题

#### F-BASE-01: DataLoader 连接无超时设置（部分修复）

**当前状态**: ⚠️ 已有 connect_timeout=10，但缺少 socket 和查询超时

**源码证据** (`base.py` 第 59 行):
```python
self._conn = psycopg2.connect(pg_cfg.uri, connect_timeout=10)
```

**验证结论**: 
- ✅ 已添加 `connect_timeout=10`（连接阶段超时）
- ❌ 缺少 `socket_timeout`（网络传输超时）
- ❌ 缺少查询级别超时（如 `SET statement_timeout`）
- ❌ 缺少 `keepalives`、`keepalives_idle` 等 TCP 保活参数

**修复建议**:
```python
# 方案 1: psycopg2 连接参数扩展
self._conn = psycopg2.connect(
    pg_cfg.uri, 
    connect_timeout=10,
    options='-c statement_timeout=30000 -c lock_timeout=5000'
)

# 方案 2: 使用 keepalives
self._conn = psycopg2.connect(
    pg_cfg.uri,
    connect_timeout=10,
    keepalives=1,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=5
)
```

**修复难度**: 低（修改 base.py 一处）  
**预计工时**: 0.5 人时

---

#### F-ENG-03: 每次计算触发 sync_definitions_to_db()

**当前状态**: ❌ 问题仍存在

**源码证据** (`engine.py` 第 191-206 行):
```python
def compute_factors(...):
    register_all()          # 幂等检查，但每次调用都执行
    _build_calculators()    # 幂等检查，但每次调用都执行
    
    ...
    
    # F-ENG-03: 每个因子计算前都会触发（通过循环内的逻辑）
    sync_definitions_to_db(conn=conn, enabled=os.getenv("SYNC_DEFS", "true").lower() == "true")
```

**验证结论**: 
- `register_all()` 和 `_build_calculators()` 有幂等检查（`if _FACTORS: return`），不会重复注册
- 但 `sync_definitions_to_db()` 在每次 `compute_factors()` 调用时都会执行 SQL INSERT/UPDATE
- 当 `SYNC_DEFS=true`（默认）时，每次因子计算都会触发全量同步

**修复建议**:
```python
# 方案 1: 添加缓存标记
_SYNC_DEFS_DONE = False

def compute_factors(...):
    global _SYNC_DEFS_DONE
    if not _SYNC_DEFS_DONE:
        sync_definitions_to_db(conn=conn)
        _SYNC_DEFS_DONE = True
```

**修复难度**: 低  
**预计工时**: 0.5 人时

---

#### F-ENG-04: 部分因子计算器独立建立数据库连接

**当前状态**: ❌ 问题仍存在

**源码证据**:

1. `technical.py` 第 474-501 行 (MainNetFlow5dCalculator):
```python
class MainNetFlow5dCalculator(FactorCalculator):
    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg
        
        conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
        try:
            ...
        finally:
            conn.close()
```

2. `technical.py` 第 504-535 行 (MainNetFlowRatio5dCalculator):
```python
class MainNetFlowRatio5dCalculator(FactorCalculator):
    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        start = calc_date - timedelta(days=5)
        from src.config import pg as pg_cfg
        
        conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
        ...
```

3. `alternative.py` 第 19-45 行 (SentimentScoreCalculator):
```python
class SentimentScoreCalculator(FactorCalculator):
    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
        try:
            ...
        finally:
            conn.close()
```

**验证结论**: 
- `MainNetFlow5dCalculator`、`MainNetFlowRatio5dCalculator`、`SentimentScoreCalculator`、`NewsVolume7dCalculator`、`NewsVolumeChangeCalculator` 均独立建立连接
- 这些计算器未使用 engine.py 传入的 `conn` 参数，也未使用 `DataLoader` 基类
- 导致每次计算都创建新连接，增加数据库负载

**修复建议**:
```python
# 方案: 修改计算器签名，接受 conn 参数
class MainNetFlow5dCalculator(FactorCalculator):
    def compute(self, company_ids: list[int], calc_date: date, conn=None, **kwargs) -> list[dict]:
        if conn is None:
            conn = psycopg2.connect(pg_cfg.uri)  # 回退逻辑
        try:
            with conn.cursor() as cur:
                ...
        finally:
            if conn and conn != kwargs.get('_shared_conn'):
                conn.close()
```

**修复难度**: 中（需修改多个计算器 + engine.py 调用方）  
**预计工时**: 2 人时

---

### 🟡 Medium 优先级问题

#### F-BASE-02: load_latest_financial 未校验财报时效性

**当前状态**: ❌ 问题仍存在

**源码证据** (`base.py` 第 124-141 行):
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
    df = pd.read_sql(sql, self.conn, params=(company_ids,),
                     parse_dates=["report_date"])
    return df
```

**验证结论**: 
- 查询返回的是 `DISTINCT ON` 取到的最新一期财报
- 但没有任何逻辑检查 `report_date` 是否过远（如超过 6 个月）
- 如果某公司长期未更新财报，会返回过期数据参与计算

**修复建议**:
```python
def load_latest_financial(self, company_ids: list[int], max_age_days: int = 180) -> pd.DataFrame:
    """加载每家公司的最新一期完整财报
    
    Args:
        max_age_days: 最大允许财报年龄（天），默认 180 天
    """
    cutoff_date = date.today() - timedelta(days=max_age_days)
    sql = """
        SELECT DISTINCT ON (fr.company_id)
               fr.company_id, fr.report_date, ...
        FROM financial_reports fr
        WHERE fr.company_id = ANY(%s)
          AND fr.revenue IS NOT NULL
          AND fr.net_profit IS NOT NULL
          AND fr.report_date >= %s  -- 新增时效性过滤
        ORDER BY fr.company_id, fr.report_date DESC
    """
    df = pd.read_sql(sql, self.conn, params=(company_ids, cutoff_date),
                     parse_dates=["report_date"])
    return df
```

**修复难度**: 低  
**预计工时**: 1 人时

---

#### F-FUND-02: ROE/ROA 使用最新一期而非 TTM

**当前状态**: ❌ 问题仍存在

**源码证据** (`fundamental.py` 第 25-41 行):
```python
class ROECalculator(FactorCalculator):
    """ROE = 净利润 / 净资产"""
    factor_key = "roe"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_latest_financial(company_ids)  # 只取最新一期
        if df.empty:
            return []
        equity = df["total_equity"].astype(float).replace(0, np.nan)
        net_profit = df["net_profit"].astype(float).replace(0, np.nan)
        valid = ~(equity.isna() | equity.eq(0))
        vals = net_profit / equity  # ❌ 使用单期数据，非 TTM
        ...
```

**验证结论**: 
- `ROECalculator`、`ROACalculator`、`GrossMarginCalculator`、`NetProfitMarginCalculator`、`DebtRatioCalculator` 均使用 `load_latest_financial()` 获取最新一期财报
- 未实现 TTM（Trailing Twelve Months）滚动计算
- 对于季度数据，应取最近 4 个季度的累计值

**修复建议**:
```python
class ROECalculator(FactorCalculator):
    """ROE(TTM) = 最近 4 期净利润之和 / 最新净资产"""
    factor_key = "roe_ttm"

    def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
        with DataLoader() as dl:
            df = dl.load_financial_reports(company_ids)  # 获取历史序列
        
        if df.empty:
            return []
        
        # TTM 计算：取最近 4 个季度的净利润之和
        ttm_profit = (df.groupby("company_id")
                      .apply(lambda g: g.nlargest(4, "report_date")["net_profit"].sum())
                      .reset_index())
        
        # 净资产取最新一期
        latest_equity = (df.drop_duplicates("company_id", keep="last")
                        .groupby("company_id")["total_equity"]
                        .last()
                        .reset_index())
        
        merged = ttm_profit.merge(latest_equity, on="company_id")
        vals = merged["net_profit"] / merged["total_equity"]
        ...
```

**修复难度**: 中  
**预计工时**: 2-3 人时

---

#### F-FUND-03: iterrows() 循环性能差

**当前状态**: ❌ 问题仍存在

**源码证据**:

1. `fundamental.py` 第 38-40 行 (ROECalculator):
```python
results = []
for cid, val in zip(df.loc[valid, "company_id"], vals[valid]):
    results.append({"company_id": int(cid), "value": round(float(val), 6)})
```

2. `alternative.py` 第 32-37 行 (SentimentScoreCalculator):
```python
results = []
for _, row in df.iterrows():
    results.append({
        "company_id": int(row["company_id"]),
        "value": round(float(row["avg_sentiment"]), 6),
    })
```

**验证结论**: 
- `fundamental.py` 中所有计算器（ROE、ROA、GrossMargin、NetProfitMargin、DebtRatio、EPSGrowthYoY）均使用 Python for 循环
- `alternative.py` 中所有计算器（SentimentScore、NewsVolume7d、NewsVolumeChange）也使用 iterrows()
- 全市场约 5000+ 家公司，iterrows() 性能极差

**修复建议**:
```python
# ❌ 当前写法（慢）
results = []
for _, row in df.iterrows():
    results.append({"company_id": int(row["company_id"]), "value": round(float(row["val"]), 6)})

# ✅ 向量化写法（快）
df["value"] = df["val"].round(6)
results = df[["company_id", "value"]].to_dict(orient="records")
```

**修复难度**: 低  
**预计工时**: 2 人时（需修改约 9 个计算器）

---

#### F-ENG-05: _compute_percentile 单元素边界缺日志

**当前状态**: ❌ 问题仍存在

**源码证据** (`engine.py` 第 139-155 行):
```python
def _compute_percentile(values: list[float]) -> list[float]:
    """截面百分位排名 (0-1)"""
    arr = np.array(values)
    n = len(arr)
    if n == 0:
        return []
    # 处理 None
    mask = ~np.isnan(arr)
    ranks = np.zeros_like(arr, dtype=float)
    if mask.sum() > 0:
        valid = arr[mask]
        sorted_idx = np.argsort(valid)
        rank = np.zeros(len(valid), dtype=float)
        rank[sorted_idx] = np.arange(len(valid))
        ranked = rank / (len(valid) - 1) if len(valid) > 1 else np.array([0.5])  # ❌ 单元素返回 0.5，无日志
        ranks[mask] = ranked
    return [round(float(x), 6) for x in ranks]
```

**验证结论**: 
- 当 `len(valid) == 1` 时，直接返回 `[0.5]`，没有警告日志
- 单元素场景可能暗示数据源问题（如某因子只有一家公司有值）
- `_compute_zscore()` 也有类似问题（第 162 行：`if mask.sum() < 2: return [None] * len(values)`）

**修复建议**:
```python
def _compute_percentile(values: list[float]) -> list[float]:
    arr = np.array(values)
    n = len(arr)
    if n == 0:
        logger.debug("_compute_percentile: 空输入")
        return []
    
    mask = ~np.isnan(arr)
    valid_count = mask.sum()
    
    if valid_count == 1:
        logger.warning(f"_compute_percentile: 仅 1 个有效值，返回 0.5（可能数据异常）")
    
    ...
```

**修复难度**: 低  
**预计工时**: 0.5 人时

---

#### F-REG-01: 注册表非线程安全

**当前状态**: ❌ 问题仍存在

**源码证据** (`registry.py` 第 60-63 行):
```python
def register_all():
    """注册所有内置因子（幂等）"""
    if _FACTORS:  # ❌ 竞态条件：两个线程可能同时通过此检查
        return
    ...
```

**验证结论**: 
- `register_all()` 和 `_build_calculators()` 都有幂等检查，但非原子操作
- 多线程环境下（如 Gunicorn 多 worker），可能出现重复注册
- 虽然 Python GIL 会保护部分操作，但 `if _FACTORS: return` 不是原子的

**修复建议**:
```python
import threading

_REGISTRY_LOCK = threading.Lock()

def register_all():
    with _REGISTRY_LOCK:  # ✅ 线程安全
        if _FACTORS:
            return
        ...
```

**修复难度**: 低  
**预计工时**: 0.5 人时

---

#### F-TECH-02/03: NaN 处理不一致

**当前状态**: ⚠️ 部分存在

**源码证据**:

1. `technical.py` 第 58-62 行 (_momentum):
```python
def _momentum(close: pd.Series, window: int) -> Optional[float]:
    if len(close) < window:
        return None  # ✅ 返回 None（SQL NULL）
    result = (close.iloc[-1] / close.iloc[-window]) - 1
    return round(float(result), 6) if pd.notna(result) else None  # ✅ NaN 处理正确
```

2. `technical.py` 第 82-89 行 (_ma5_deviation):
```python
def _ma5_deviation(close: pd.Series) -> Optional[float]:
    if len(close) < 5:
        return None
    ma5 = close.tail(5).mean()
    if ma5 <= 0:
        return None
    val = (float(close.iloc[-1]) / ma5) - 1
    return round(val, 6)  # ❌ 未检查 val 是否为 NaN
```

**验证结论**: 
- 大部分函数有 `pd.notna()` 检查，但 `_ma5_deviation`、`_gap_open`、`_intraday_break_pct` 等缺少最终 NaN 检查
- 当 `close.iloc[-1]` 为 NaN 时，`round(val, 6)` 会返回 NaN 而非 None

**修复建议**:
```python
def _ma5_deviation(close: pd.Series) -> Optional[float]:
    if len(close) < 5:
        return None
    ma5 = close.tail(5).mean()
    if ma5 <= 0 or pd.isna(ma5):
        return None
    val = (float(close.iloc[-1]) / ma5) - 1
    return round(float(val), 6) if pd.notna(val) else None  # ✅ 添加 NaN 检查
```

**修复难度**: 低  
**预计工时**: 1 人时

---

#### F-ALT-01/02/03: 连接复用与一致性问题

**当前状态**: ❌ 问题仍存在

**源码证据** (`alternative.py`):

1. `SentimentScoreCalculator` (第 19-45 行):
```python
def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
    conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
    try:
        ...
    finally:
        conn.close()
```

2. `NewsVolume7dCalculator` (第 52-76 行):
```python
def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
    conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
    ...
```

3. `NewsVolumeChangeCalculator` (第 83-119 行):
```python
def compute(self, company_ids: list[int], calc_date: date, **kwargs) -> list[dict]:
    conn = psycopg2.connect(pg_cfg.uri)  # ❌ 独立建连
    ...
```

**验证结论**: 
- 所有另类因子计算器均独立建立和关闭连接
- 与 `technical.py` 中的资金流计算器问题相同
- 缺少对 `conn` 参数的支持，无法复用 engine.py 传入的连接

**修复建议**: 同 F-ENG-04 的修复方案

**修复难度**: 中  
**预计工时**: 1.5 人时

---

## 三、修复优先级与工时估算

| 优先级 | 问题 ID | 修复难度 | 预计工时 | 建议修复顺序 |
|--------|---------|----------|----------|--------------|
| 🔴 P0 | F-BASE-01 | 低 | 0.5h | 第 1（已有部分修复，补全即可） |
| 🔴 P0 | F-ENG-03 | 低 | 0.5h | 第 2（添加缓存标记） |
| 🟡 P1 | F-REG-01 | 低 | 0.5h | 第 3（线程安全锁） |
| 🟡 P1 | F-ENG-05 | 低 | 0.5h | 第 4（添加边界日志） |
| 🟡 P1 | F-BASE-02 | 低 | 1h | 第 5（添加时效性过滤） |
| 🟡 P1 | F-TECH-02/03 | 低 | 1h | 第 6（补全 NaN 检查） |
| 🔴 P2 | F-ENG-04 | 中 | 2h | 第 7（连接复用改造） |
| 🟡 P2 | F-ALT-01/02/03 | 中 | 1.5h | 第 8（连接复用改造） |
| 🟡 P2 | F-FUND-03 | 低 | 2h | 第 9（iterrows → 向量化） |
| 🟡 P2 | F-FUND-02 | 中 | 2-3h | 第 10（TTM 计算实现） |

**总预计工时**: ~11.5 人时

---

## 四、架构改进建议

### 4.1 连接池化（长期优化）

当前每个计算器可能独立建连，建议引入连接池：

```python
import psycopg2.pool

_CONNECTION_POOL = None

def get_connection_pool(min_conn=2, max_conn=10):
    global _CONNECTION_POOL
    if _CONNECTION_POOL is None:
        _CONNECTION_POOL = psycopg2.pool.ThreadedConnectionPool(
            min_conn, max_conn, pg_cfg.uri
        )
    return _CONNECTION_POOL
```

### 4.2 计算器接口统一

建议所有计算器统一接受 `conn` 参数：

```python
class FactorCalculator(ABC):
    @abstractmethod
    def compute(self, company_ids: list[int], calc_date: date, 
                conn=None, quotes_df=None, **kwargs) -> list[dict]:
        ...
```

### 4.3 批量写入优化

当前 `save_all_factors()` 在 `advanced.py` 中使用逐条 INSERT，建议改用 `execute_values`：

```python
from psycopg2.extras import execute_values

rows = [(r["company_id"], fid, calc_date, float(value)) for r in data]
execute_values(cur, """
    INSERT INTO factor_values (company_id, factor_id, calc_date, value)
    VALUES %s
""", rows)
```

---

## 五、总结

Factors 模块整体架构清晰，但存在以下主要问题：

1. **连接管理不统一**（F-ENG-04, F-ALT-01/02/03）：部分计算器独立建连，增加数据库负载
2. **性能瓶颈**（F-FUND-03）：iterrows() 循环在大规模数据下性能差
3. **计算逻辑不完整**（F-FUND-02）：未实现 TTM 滚动计算
4. **边界处理不足**（F-ENG-05, F-TECH-02/03）：缺少日志和 NaN 检查

建议按优先级逐步修复，优先解决连接复用和性能问题。

---

*报告生成时间: 2026-06-05 21:55 CST*
