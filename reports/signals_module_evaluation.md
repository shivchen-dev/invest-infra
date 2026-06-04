# Signals 模块代码质量审计报告

**审计日期**: 2026-06-04  
**审计范围**: `src/signals/` 目录下全部 4 个源文件  
**审计人**: signals-auditor (代码质量审计专家)  

---

## 摘要

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 Critical | 5 | 直接影响计算结果正确性，需立即修复 |
| 🟠 High | 4 | 可能导致评分偏差或运行时异常 |
| 🟡 Medium | 4 | 代码质量/可维护性问题 |
| 🟢 Low | 2 | 优化建议 |

**总计**: 15 个问题

---

## 🔴 Critical（严重）

### CRIT-001: alpha.py — Category 内不同方向因子的归一化方向错误

**位置**: `alpha.py` 第 134-138 行  
**描述**: `compute_alpha_scores()` 中，每个 category 内的所有因子使用同一个 `norm_direction`（取 `cat_weights[0]["norm_direction"]`）。但 momentum 类别中同时包含正向因子（momentum_5d, direction=1）和反向因子（reversal_5d, reversal_20d, direction=-1）。反向因子会被错误地按正向处理，导致评分完全颠倒。

**代码片段**:
```python
# alpha.py:134-138
for cat, cat_weights in categories.items():
    cat_raw = {w["factor_key"]: factors[w["factor_key"]] for w in cat_weights
               if w["factor_key"] in factors and factors[w["factor_key"]] is not None}
    if cat_raw:
        normed = normalize_factor(cat_raw, cat_weights[0]["norm_direction"])  # ← 只取第一个方向
```

**影响**: reversal_5d（预期：价格下跌越多得分越高）会被当作正向因子处理，导致超跌股得分反而低。

**修复建议**: 对每个因子单独使用其对应的 `norm_direction` 进行归一化，而非整个 category 共用一个方向。

---

### CRIT-002: etf_alpha.py — Category 内不同方向因子的归一化方向错误

**位置**: `etf_alpha.py` 第 373-381 行  
**描述**: 与 CRIT-001 相同的问题。liquidity 类别中包含正向因子（amount_ma5, direction=1）和反向因子（bid_ask_spread, direction=-1）。反向因子会被错误处理。

**代码片段**:
```python
# etf_alpha.py:376-381
for cat, cat_ws in categories.items():
    ...
    if cat_raw:
        direction = cat_ws[0]["norm_direction"]  # ← 只取第一个方向
        normed = normalize(cat_raw, direction)
```

**影响**: bid_ask_spread（预期：价差越小得分越高）会被当作正向因子处理，导致买卖价差大的 ETF 得分反而高。

**修复建议**: 同 CRIT-001，对每个因子单独使用其对应的 `norm_direction`。

---

### CRIT-003: scoring.py — fetch_stock_factor_matrix 中动量计算逻辑错误

**位置**: `scoring.py` 第 303-311 行  
**描述**: 使用 `MAX(d.change_pct)` 计算 5日/20日/60日动量。这是期间内的**最大单日涨跌幅**，而非真正的**区间动量**（期末价格/期初价格 - 1）。

**代码片段**:
```python
# scoring.py:303-311
mom AS (
    SELECT d.company_id,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_5d,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_20d,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_60d
    FROM daily_quotes d
```

**影响**: 所有基于动量的评分（momentum 维度、alpha 信号）都是错误的。例如一只股票 5 天内涨跌幅为 [1%, -2%, 3%, -1%, 2%]，MAX=3% 但实际区间动量约为 4.1%。

**修复建议**: 改用 `LAST(d.close_price)` / `FIRST(d.close_price) - 1` 或窗口函数计算区间收益率。

---

### CRIT-004: etf_arbitrage.py — _assess_confidence 中净收益计算单位不一致

**位置**: `etf_arbitrage.py` 第 175-182 行  
**描述**: `abs_premium / 100.0` 将百分比转换为比率（如 0.5% → 0.005），但 `total_cost_pct` 在 ArbitrageSignal 中已经是百分比值（如 0.15 表示 0.15%）。两者单位不一致，导致净收益计算完全错误。

**代码片段**:
```python
# etf_arbitrage.py:175-182
def _assess_confidence(abs_premium: float, liquidity_score: float, total_cost_pct: float, cfg: ArbitrageConfig) -> str:
    net_gain = (float(abs_premium) / 100.0) - total_cost_pct  # ← 单位不一致！
    if abs_premium > 0.5 and liquidity_score > 0.8 and net_gain > cfg.min_profit_threshold:
        return "high"
```

**示例**: abs_premium=0.5（0.5%），total_cost_pct=0.15（0.15%）：
- 当前计算: `0.5/100 - 0.15 = 0.005 - 0.15 = -0.145` → 错误地判定为亏损
- 正确计算: `(0.5 - 0.15) / 100 = 0.0035` → 实际盈利

**影响**: 置信度评估完全错误，可能导致高置信度信号被误判为低置信度。

**修复建议**: 统一单位后再相减：`net_gain = (abs_premium - total_cost_pct) / 100.0`

---

### CRIT-005: scoring.py — score_stock 中 fundamental 维度归一化方法错误

**位置**: `scoring.py` 第 485-490 行  
**描述**: 使用 `v * 4` 将因子值映射到 [0, 100]，假设因子值在 [0, 25] 范围内。但 roe、roa、gross_margin、net_profit_margin 等财务指标通常远小于 25（roe 通常在 0-0.5 之间）。

**代码片段**:
```python
# scoring.py:485-490
for _, key in [("roe", "roe"), ("roa", "roa"),
               ("gross_margin", "gross_margin"), ("net_profit_margin", "net_profit_margin")]:
    v = _f(record.get(key))
    if v is not None:
        scores["fundamental"] = scores.get("fundamental", 0) + max(0, min(100, v * 4)) / 4
```

**示例**: roe=0.2（20%）→ `max(0, min(100, 0.2*4))/4 = 0.8/4 = 0.2` → fundamental 维度得分仅 0.2/4 ≈ 0.05

**影响**: fundamental 维度评分几乎总是接近 0，导致质量因子在综合评分中完全失效。

**修复建议**: 使用百分位排名（percentile rank）或 Z-score 标准化替代固定倍数映射。

---

## 🟠 High（高）

### HIGH-001: alpha.py — DEFAULT_WEIGHTS 总权重为 0.99，非 1.0

**位置**: `alpha.py` 第 19-39 行  
**描述**: 所有因子权重之和为 0.99（而非 1.0），导致加权求和时总分偏低约 1%。

```
0.07+0.08+0.05+0.05+0.03+0.06+0.04+0.05+0.05+0.05+0.12+0.08+0.05+0.05+0.03+0.02+0.06+0.06+0.04 = 0.99
```

**影响**: 综合评分系统性偏低约 1%，可能影响信号阈值判断。

**修复建议**: 调整某个因子权重使总和为 1.0，或在计算时归一化权重。

---

### HIGH-002: etf_alpha.py — ETF_DEFAULT_WEIGHTS 总权重为 1.04，超过 1.0

**位置**: `etf_alpha.py` 第 25-55 行  
**描述**: 所有因子权重之和为 1.04（超过 1.0），导致加权求和时总分偏高约 4%。

```
0.08+0.08+0.06+0.04+0.04+0.05+0.05+0.03+0.06+0.03+0.02+0.01+0.08+0.06+0.04+0.02+0.05+0.04+0.03+0.05+0.04+0.03+0.02+0.01 = 1.04
```

**影响**: ETF 综合评分系统性偏高约 4%，可能导致过多 ETF 被标记为正向信号。

**修复建议**: 调整权重使总和为 1.0，或在计算时归一化权重。

---

### HIGH-003: etf_alpha.py — normalize() 中 catch 所有 Exception

**位置**: `etf_alpha.py` 第 295-300 行  
**描述**: `try/except Exception` 捕获了所有异常，包括 `KeyboardInterrupt` 和 `SystemExit`。这会阻止用户通过 Ctrl+C 中断程序。

**代码片段**:
```python
# etf_alpha.py:295-300
def normalize(raw_values, direction):
    try:
        return _zscore_norm(raw_values, direction)
    except Exception:  # ← 捕获所有异常，包括 KeyboardInterrupt
        return _min_max_norm(raw_values, direction)
```

**影响**: 程序无法被正常中断；掩盖了潜在的编程错误。

**修复建议**: 仅捕获预期的异常类型：`except (ZeroDivisionError, ValueError):`

---

### HIGH-004: scoring.py — fetch_stock_factor_matrix 中 close_now 使用 MAX()

**位置**: `scoring.py` 第 313-314 行  
**描述**: `MAX(d.close_price) FILTER(WHERE d.trade_date = %s)` 在 calc_date 有多条记录（如盘中数据）时可能返回非收盘价。

**代码片段**:
```python
# scoring.py:313-314
trend AS (
    SELECT d.company_id,
           MAX(d.close_price) FILTER(WHERE d.trade_date = %s) AS close_now,  # ← 应为收盘价
```

**影响**: 如果 daily_quotes 包含盘中快照数据，close_now 可能不是真实收盘价。

**修复建议**: 使用 `LAST(d.close_price)` 或按时间排序取最后一条记录。

---

## 🟡 Medium（中）

### MED-001: alpha.py — composite_score 的 coverage 衰减导致评分分布不均匀

**位置**: `alpha.py` 第 143-150 行  
**描述**: 当某些因子缺失时，`coverage = total_weight / expected_weight < 1`，composite 被线性衰减。这导致因子缺失多的公司评分范围缩小，可能产生不公平的排名。

**代码片段**:
```python
# alpha.py:143-150
expected_weight = sum(w["weight"] for w in weights)
if total_weight > 0 and expected_weight > 0:
    coverage = total_weight / expected_weight
    raw_score = weighted_sum / total_weight
    composite = (raw_score - 50) * 2 * coverage  # ← coverage < 1 时范围缩小
```

**影响**: 因子数据缺失多的公司评分被压缩，可能无法反映真实质量。

**修复建议**: 考虑使用插值填充缺失因子，或明确标注低覆盖率公司的评分置信度。

---

### MED-002: etf_alpha.py — compute_etf_indicators 中 premium_rate 可能返回 NaN

**位置**: `etf_alpha.py` 第 203 行  
**描述**: `g["premium_rate"].iloc[-1]` 如果该列为 NaN，会返回 NaN 而非 None。后续计算中可能导致数值问题。

**代码片段**:
```python
# etf_alpha.py:203
premium = g["premium_rate"].iloc[-1]  # ← 可能为 NaN
```

**影响**: NaN 值在后续计算中传播，可能导致评分异常。

**修复建议**: 添加 `if pd.isna(premium): premium = None` 处理。

---

### MED-003: scoring.py — score_etf 中 etf 和 liquidity 维度完全相关

**位置**: `scoring.py` 第 548-550 行  
**描述**: `scores["etf"]` 和 `scores["liquidity"]` 被设置为相同的值，导致这两个维度完全相关。

**代码片段**:
```python
# scoring.py:548-550
if record.get("liquidity_score") is not None:
    scores["etf"] = max(0, min(100, record["liquidity_score"] * 100))
    scores["liquidity"] = max(0, min(100, record["liquidity_score"] * 100))  # ← 与 etf 相同
```

**影响**: ETF 评分中流动性维度被重复计算，实际权重翻倍。

**修复建议**: 为 `scores["etf"]` 使用不同的计算逻辑（如溢价率、IOPV 偏离度等）。

---

### MED-004: scoring.py — DEFAULT_FILTERS 注释与实际值不匹配

**位置**: `scoring.py` 第 229-233 行  
**描述**: 注释称"当前数据 score 范围仅 1~4；数据完备后应调回 60+"，但 `min_composite=0.0` 会包含所有记录。

**代码片段**:
```python
# scoring.py:229-233
DEFAULT_FILTERS = {
    "min_composite":   0.0,    # 综合评分 ≥ 0（当前数据 score 范围仅 1~4；数据完备后应调回 60+）
    ...
}
```

**影响**: 临时值未清理，可能导致筛选出大量低质量标的。

**修复建议**: 更新注释或设置明确的 TODO 标记，避免临时值长期存在。

---

## 🟢 Low（低）

### LOW-001: alpha.py — normalize_factor 中 direction=1 时多余的 percentile_rank 调用

**位置**: `alpha.py` 第 73-82 行  
**描述**: 当 `direction=1` 时，先调用 `percentile_rank(vals)` 计算一次，但返回值未被使用（因为后续没有进入 `if direction == -1` 分支）。虽然不影响正确性，但浪费了一次计算。

**代码片段**:
```python
# alpha.py:73-82
def normalize_factor(raw_values, direction):
    ...
    pct_ranks = percentile_rank(vals)  # ← direction=1 时此调用结果被直接使用，无浪费
    if direction == -1:
        sr = pd.Series(vals, dtype=float)
        pct_ranks = sr.rank(pct=True, ascending=False, method="average").fillna(50).tolist()
```

**说明**: 实际上 `pct_ranks` 在 direction=1 时会被使用，所以这不是真正的浪费。但代码结构可以更清晰。

**修复建议**: 重构为更清晰的分支结构。

---

### LOW-002: etf_alpha.py — compute_etf_alpha 中 cat_score 计算的生成器表达式效率问题

**位置**: `etf_alpha.py` 第 381 行  
**描述**: 生成器表达式 `for k in cat_raw for w in cat_ws if w["factor_key"] == k` 对每个因子都遍历整个 `cat_ws` 列表查找匹配项。如果 category 内因子较多，效率较低。

**代码片段**:
```python
# etf_alpha.py:381
cat_score = sum(normed[k] * w["weight"] for k in cat_raw for w in cat_ws if w["factor_key"] == k and k in normed)
```

**影响**: 当 category 内因子较多时，时间复杂度从 O(n) 升至 O(n²)。

**修复建议**: 预构建 factor_key → weight 的字典映射。

---

## 跨文件一致性检查

### 评分模型不一致

| 模块 | 归一化方法 | 方向处理 | 权重总和 |
|------|-----------|---------|---------|
| alpha.py | percentile rank | ❌ category 级别（错误） | 0.99 |
| etf_alpha.py | Z-score / min-max | ❌ category 级别（错误） | 1.04 |
| scoring.py | 固定倍数映射 | ✅ 因子级别 | N/A |

**问题**: 三个模块使用不同的归一化方法，导致同一因子在不同模块中的评分可能不一致。建议统一归一化策略。

---

## 安全审计

| 项目 | 状态 | 说明 |
|------|------|------|
| SQL 注入 | ✅ 安全 | 所有查询均使用参数化（%s） |
| 异常处理 | ⚠️ 部分风险 | etf_alpha.py 中 catch 所有 Exception |
| 连接管理 | ✅ 安全 | 所有 DB 连接均在 finally 块中关闭 |
| 输入验证 | ⚠️ 部分风险 | CLI 参数未做范围校验 |

---

## 性能审计

| 模块 | 风险点 | 建议 |
|------|--------|------|
| alpha.py | 单公司循环内多次字典查找 | 预构建 factor_key → weight 映射 |
| etf_alpha.py | compute_etf_indicators 中 groupby + 循环 | 考虑向量化计算 |
| scoring.py | fetch_stock_factor_matrix 中 CTE 链较长 | 评估执行计划，考虑物化视图 |

---

## 修复优先级建议

1. **立即修复**（影响交易决策正确性）:
   - CRIT-003: 动量计算逻辑错误
   - CRIT-004: 套利置信度计算单位不一致
   - CRIT-005: fundamental 归一化方法错误

2. **本周修复**（影响评分准确性）:
   - CRIT-001, CRIT-002: Category 方向处理错误
   - HIGH-001, HIGH-002: 权重总和不等于 1.0

3. **迭代优化**（代码质量提升）:
   - HIGH-003: Exception 捕获范围
   - MED-001 ~ MED-004: 评分分布、NaN 处理、维度重复、临时值清理

---

*报告结束*
