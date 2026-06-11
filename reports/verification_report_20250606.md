# 投研系统验收报告

**验收日期**: 2026-06-06  
**验收依据**: comprehensive_audit_report.md（2026-06-04）  
**验收范围**: signals 模块 + factors 模块  
**验收方式**: 代码静态审查

---

## 一、验收结论总览

| 类别 | 问题数 | 已修复 | 未修复 | 修复率 |
|------|--------|--------|--------|--------|
| **Critical** | 7 | 5 | 2 | 71% |
| **High** | 4 | 4 | 0 | 100% |
| **Medium** | 2 | 1 | 1 | 50% |
| **合计** | **13** | **10** | **3** | **77%** |

**核心遗留问题**: 2 个 Critical 级别的归一化方向错误尚未修复，直接影响动量/反转因子的评分正确性。

---

## 二、Critical 问题验收详情

### ✅ CRIT-003 — 动量计算逻辑错误

**位置**: `signals/scoring.py` L345-349  
**原问题**: 使用 `MAX(d.change_pct)` 计算动量（最大单日涨跌幅），而非区间收益率  
**修复验证**:
```python
# 当前代码（已修复）
(ld.close_price / NULLIF(e5.close_price, 0)) - 1 AS mom_5d,
(ld.close_price / NULLIF(e20.close_price, 0)) - 1 AS mom_20d,
(ld.close_price / NULLIF(e60.close_price, 0)) - 1 AS mom_60d
```
✅ 改用窗口函数计算期末/期初价格比率，正确计算区间收益率

---

### ✅ CRIT-004 — 套利置信度单位不一致

**位置**: `signals/etf_arbitrage.py` L184  
**原问题**: `abs_premium / 100.0 - total_cost_pct`，单位混用（比率 vs 百分比）  
**修复验证**:
```python
# 当前代码（已修复）
net_gain = (float(abs_premium) - float(total_cost_pct)) / 100.0
```
✅ 统一为 % 单位后再转小数，与 `cfg.min_profit_threshold`（小数）正确比较

---

### ✅ CRIT-005 — Fundamental 归一化方法错误

**位置**: `signals/scoring.py` L38-70  
**原问题**: 使用 `v * 4` 归一化，roe 等指标通常远小于 25 导致评分几乎为 0  
**修复验证**:
```python
# 当前代码（已修复）
def _normalize_fundamentals(records: list[dict]) -> None:
    for key in _FUNDAMENTAL_METRICS:
        pairs: list[tuple[int, float]] = []
        for idx, rec in enumerate(records):
            v = rec.get(key)
            if v is not None:
                f = float(v)
                if f == f:  # filter NaN
                    pairs.append((idx, f))
        if len(pairs) < 2:
            for idx, _ in pairs:
                records[idx]["fundamental_pct"] = {...}
            continue
        indices, vals = zip(*pairs)
        ranks = rankdata(vals, method="average")
        percentiles = {i: (r / len(vals)) * 100.0 for i, r in zip(indices, ranks)}
```
✅ 改用 `scipy.stats.rankdata` 百分位排名，避免固定乘数对不同量纲数据的扭曲

---

### ✅ CRIT-006 — 逐行 INSERT 性能瓶颈

**位置**: `factors/engine.py` L261-272  
**原问题**: 每个因子值单独 INSERT，全市场 5000+ 公司 × 26 因子 = 13 万次独立 SQL  
**修复验证**:
```python
# 当前代码（已修复）
rows = [
    (v["company_id"], fd_id, calc_date, v["value"],
     pct_map.get(v["company_id"]), zscore_map.get(v["company_id"]), batch_label)
    for v in values if v["value"] is not None
]
if rows:
    psycopg2.extras.execute_values(
        cur,
        """INSERT INTO factor_values ... VALUES %s ...""",
        rows,
    )
```
✅ 改用 `execute_values()` 批量写入，理论提速 100x+

---

### ✅ CRIT-007 — 截面标准化映射错位

**位置**: `factors/engine.py` L248-249  
**原问题**: 迭代器顺序映射，当 values 含 None 时导致 company_id 与 percentile/zscore 错位  
**修复验证**:
```python
# 当前代码（已修复）
pct_map = {v["company_id"]: p for v, p in zip(valid_values, percentiles)}
zscore_map = {v["company_id"]: z for v, z in zip(valid_values, zscores)}
# 写入时按 company_id 查表
rows = [
    (v["company_id"], fd_id, calc_date, v["value"],
     pct_map.get(v["company_id"]), zscore_map.get(v["company_id"]), batch_label)
    for v in values if v["value"] is not None
]
```
✅ 建立 company_id → percentile/zscore 字典映射，消除迭代器错位风险

---

### ❌ CRIT-001 — Category 归一化方向冲突（未修复）

**位置**: `signals/alpha.py` L134-138  
**原问题**: momentum 类别中同时包含正向因子（momentum_5d, direction=1）和反向因子（reversal_5d, reversal_20d, direction=-1），但共用 `cat_weights[0]["norm_direction"]`  
**当前代码**:
```python
for cat, cat_weights in categories.items():
    cat_raw = {w["factor_key"]: factors[w["factor_key"]] for w in cat_weights
               if w["factor_key"] in factors and factors[w["factor_key"]] is not None}
    if cat_raw:
        normed = normalize_factor(cat_raw, cat_weights[0]["norm_direction"])
        # ↑ 整个 category 使用同一个 direction，reversal_5d (direction=-1) 被错误处理
```

**影响**: reversal_5d（预期：价格下跌越多得分越高）被当作正向因子处理，导致超跌股得分反而低。**此问题直接影响 alpha 信号的正确性。**

**修复建议**: 对每个因子单独使用其对应的 `norm_direction` 进行归一化：
```python
# 方案：在 normalize_factor 内部按因子应用 direction
def normalize_factor(raw_values, weights):
    # raw_values: {factor_key: value}
    # weights: [{factor_key, norm_direction, weight}, ...]
    normed = {}
    for w in weights:
        fk = w["factor_key"]
        if fk in raw_values and raw_values[fk] is not None:
            # 对每个因子单独归一化
            normed[fk] = _normalize_single(raw_values[fk], w["norm_direction"])
    return normed
```

---

### ❌ CRIT-002 — Category 归一化方向冲突（未修复）

**位置**: `signals/etf_alpha.py` L375-381  
**原问题**: 与 CRIT-001 相同。liquidity 类别中包含正向因子（amount_ma5, direction=1）和反向因子（bid_ask_spread, direction=-1），共用 `cat_ws[0]["norm_direction"]`  
**当前代码**:
```python
for cat, cat_ws in categories.items():
    cat_raw = {w["factor_key"]: factors[w["factor_key"]]
               for w in cat_ws if w["factor_key"] in factors}
    if cat_raw:
        direction = cat_ws[0]["norm_direction"]  # ← 只取第一个方向
        normed = normalize(cat_raw, direction)
        # ↑ bid_ask_spread (direction=-1) 被错误处理
```

**影响**: bid_ask_spread（预期：价差越小得分越高）被当作正向因子处理，导致买卖价差大的 ETF 得分反而高。

---

## 三、High 问题验收详情

| 问题ID | 状态 | 验证结果 |
|--------|------|----------|
| HIGH-001 权重总和非 1.0 | ✅ 已修复 | alpha.py L19-39 权重总和已修正为 1.0 |
| HIGH-002 权重总和非 1.0 | ✅ 已修复 | etf_alpha.py L25-55 权重总和已修正为 1.0 |
| HIGH-003 裸 except Exception | ✅ 已修复 | etf_alpha.py L299 改为 `except (TypeError, ValueError)` |
| HIGH-004 close_now 使用 MAX() | ✅ 合理 | GROUP BY + ORDER BY DESC LIMIT 1 语义正确 |

---

## 四、Medium 问题验收详情

| 问题ID | 状态 | 验证结果 |
|--------|------|----------|
| MED-003 etf/liquidity 维度重复 | ❌ 未修复 | scoring.py L613-615 两维度使用完全相同的 `liquidity_score * 100` |
| MED-004 临时值未清理 | ✅ 合理 | scoring.py L271 已有 FIXME 注释标注 |

---

## 五、其他修复验证

| 问题ID | 位置 | 状态 | 验证结果 |
|--------|------|------|----------|
| F-BASE-01 连接超时 | factors/base.py L59 | ✅ 已修复 | `connect_timeout=10` |
| F-TECH-01 重复数据加载 | factors/engine.py L210-219 | ✅ 已修复 | 预加载 DataLoader，复用 130d 行情数据 |
| F-FUND-01 会计年度匹配 | factors/fundamental.py L141-160 | ✅ 已修复 | 改用 `fiscal_year` + `quarter` 匹配 |
| HIGH-005 连接超时配置 | factors/base.py | ✅ 已修复 | 同 F-BASE-01 |

---

## 六、遗留问题汇总

### 🔴 Critical — 需立即修复

| 优先级 | 问题ID | 描述 | 预计工时 |
|--------|--------|------|----------|
| P0 | CRIT-001 | alpha.py 归一化方向冲突（momentum 类别） | 2h |
| P0 | CRIT-002 | etf_alpha.py 归一化方向冲突（liquidity 类别） | 1h |

### 🟡 Medium — 建议迭代修复

| 优先级 | 问题ID | 描述 | 预计工时 |
|--------|--------|------|----------|
| P2 | MED-003 | scoring.py ETF 评分中 etf/liquidity 维度重复计算 | 1h |

---

## 七、风险评估

| 风险项 | 严重度 | 说明 |
|--------|--------|------|
| **反转因子评分失效** | 🔴 高 | CRIT-001 导致 reversal_5d/reversal_20d 方向错误，超跌信号失真 |
| **ETF 买卖价差评分反向** | 🔴 高 | CRIT-002 导致 bid_ask_spread 评分反向，流动性评估失效 |
| **ETF 评分维度重复** | 🟡 中 | MED-003 导致流动性维度权重实际翻倍，影响评分准确性 |

---

## 八、修复状态对比

```
评估报告声明修复   9 项（2026-06-05）
代码验证实际修复   10 项
未修复            3 项（CRIT-001, CRIT-002, MED-003）

差异原因：
1. CRIT-001/CRIT-002 评估报告声明已修复 commit `1263454`，但代码审查发现未修复
2. MED-003 为新发现遗留问题
```

---

## 九、建议

1. **立即修复 CRIT-001 和 CRIT-002**：这两个问题直接影响信号正确性，建议在重新上线前修复
2. **修复后重新验证**：修复完成后需重新运行 `run_alpha.sh` 和 `run_factor.sh` 验证
3. **补充单元测试**：建议为 normalize_factor 和 normalize 函数补充针对方向处理的测试用例

---

*本报告由 code-quality-expert 基于代码静态分析生成，验证日期 2026-06-06。*

---

## 十、审计归档

### 归档状态

| 日期 | 审计类型 | 状态 | 归档人 | 归档日期 |
|------|---------|------|--------|----------|
| 2026-06-06 | 验收报告 | ✅ 已归档 | system-auditor | 2026-06-07 |

### 后续验证（2026-06-07 源码级审计）

2026-06-07 专家团队对原验收报告中标记为"未修复"的问题进行了源码级复审，确认：

| 问题ID | 原状态 | 最终验证 | 备注 |
|--------|--------|----------|------|
| CRIT-001 | ❌ 未修复 | ✅ **已修复** | `normalize_factor` 支持 per-factor direction，`reversal_5d/20d` 正确应用 `direction=-1` |
| CRIT-002 | ❌ 未修复 | ✅ **已修复** | `normalize` 函数支持 dict 类型的 direction，`bid_ask_spread` 正确应用 `direction=-1` |
| MED-003 | ❌ 未修复 | ✅ **已修复** | `score_etf` 函数不再计算重复的 `etf` 维度 |

**结论：验收报告中原 3 个未修复问题，经源码级审计确认均已正确修复。**