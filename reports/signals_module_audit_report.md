# Signals 模块审计报告

**审计人**: signals-auditor  
**审计日期**: 2026-06-05  
**审计范围**: `data-pipeline/src/signals/` 模块（alpha.py, etf_alpha.py, scoring.py, etf_arbitrage.py）  
**问题来源**: 已有评估报告中的 4 个 Medium 级别未修复问题  

---

## 执行摘要

| 问题 ID | 描述 | 验证结论 | 优先级 | 预计工时 |
|---------|------|----------|--------|----------|
| S-MD01 | coverage 衰减导致评分分布不均匀 | ✅ 确认存在 | P2 (中) | 4h |
| S-MD02 | premium_rate NaN 值可能污染评分 | ✅ 确认存在 | P2 (中) | 2h |
| S-MD03 | etf 和 liquidity 维度完全相关 | ✅ 确认存在 | P1 (高) | 2h |
| S-MD04 | DEFAULT_FILTERS 注释与实际不匹配 | ✅ 确认存在 | P3 (低) | 1h |

---

## 详细审计结果

### S-MD01: Coverage 衰减导致评分分布不均匀

**文件**: `alpha.py`  
**函数**: `compute_alpha_scores()` (第 143-151 行)

#### 问题描述
当股票因子覆盖率（coverage）< 1.0 时，composite score 会被线性衰减：
```python
coverage = total_weight / expected_weight
composite = (raw_score - 50) * 2 * coverage
```

这导致数据缺失的股票天然处于劣势，评分分布向数据完备的股票倾斜。

#### 源码证据
```python
# alpha.py 第 143-151 行
expected_weight = sum(w["weight"] for w in weights)
if total_weight > 0 and expected_weight > 0:
    coverage = total_weight / expected_weight
    raw_score = weighted_sum / total_weight
    # 归一化到[0,100]，coverage<1 时直接线性衰减，不存在虚高空间
    composite = (raw_score - 50) * 2 * coverage
```

#### 验证结论
**问题确认存在**。模拟显示：
- raw_score=85, coverage=1.0 → composite=70.0
- raw_score=85, coverage=0.6 → composite=42.0（衰减 40%）
- raw_score=85, coverage=0.4 → composite=28.0（衰减 60%）

高分股票因数据缺失被严重低估，评分分布不均匀。

#### 修复建议
1. **短期**: 对 coverage < 0.7 的股票标记为"低置信度"，不纳入排名
2. **中期**: 使用插值或贝叶斯平滑估计缺失因子值
3. **长期**: 改进数据管道，提高因子覆盖率

#### 优先级: P2 (中) — 影响评分公平性，但非紧急

---

### S-MD02: premium_rate NaN 值可能污染评分

**文件**: `scoring.py`  
**函数**: `score_etf()` (第 607-634 行)

#### 问题描述
`score_etf()` 使用 `if record.get("abs_premium") is not None` 过滤 NaN，但：
1. `pd.NA`、`np.nan`、`float('nan')` 在 Python 中 `is not None` 为 True
2. `etf_alpha.py` 第 365 行有正确防护：`not (isinstance(v, float) and np.isnan(v))`
3. `scoring.py` 的 `score_etf()` 缺少此防护

#### 源码证据
```python
# scoring.py 第 624-626 行 — 缺少 NaN 防护
ap = record.get("abs_premium")
if ap is not None:  # np.nan is not None → True!
    scores["reversal"] = max(0, min(100, 50 - ap * 10))  # NaN * 10 = NaN
```

#### 验证结论
**问题确认存在**。当 `abs_premium` 为 `np.nan` 时：
- `ap is not None` → True（NaN 不是 None）
- `50 - np.nan * 10` → NaN
- `max(0, min(100, NaN))` → NaN（Python 的 max/min 对 NaN 行为未定义）

#### 修复建议
```python
# 修复方案：添加 NaN 检查
import numpy as np

ap = record.get("abs_premium")
if ap is not None and not (isinstance(ap, float) and np.isnan(ap)):
    scores["reversal"] = max(0, min(100, 50 - float(ap) * 10))
```

#### 优先级: P2 (中) — 可能导致评分计算异常

---

### S-MD03: etf 和 liquidity 维度完全相关（多重共线性）

**文件**: `scoring.py`  
**函数**: `score_etf()` (第 613-615 行)

#### 问题描述
`scores["etf"]` 和 `scores["liquidity"]` 使用完全相同的计算逻辑：
```python
scores["etf"] = max(0, min(100, record["liquidity_score"] * 100))
scores["liquidity"] = max(0, min(100, record["liquidity_score"] * 100))
```

在 `ETFS_WEIGHTS` 中，这两个维度权重分别为 30% 和 15%，导致流动性信息被双重加权（45%）。

#### 源码证据
```python
# scoring.py 第 613-615 行
if record.get("liquidity_score") is not None:
    scores["etf"] = max(0, min(100, record["liquidity_score"] * 100))
    scores["liquidity"] = max(0, min(100, record["liquidity_score"] * 100))

# ETFS_WEIGHTS (第 88-96 行)
ETFS_WEIGHTS = {
    "etf":         0.30,   # ETF 特有维度
    "momentum":    0.20,
    "trend":       0.10,
    "liquidity":   0.15,   # 流动性维度 — 与 etf 完全重复！
    ...
}
```

#### 验证结论
**问题确认存在**。`etf` 和 `liquidity` 维度的相关系数 = 1.0（完全正相关）。

影响：
- 流动性信息被双重加权：30% + 15% = 45%
- momentum 维度（20%）被相对稀释
- 评分对流动性过度敏感

#### 修复建议
**方案 A（推荐）**: 删除 `scores["liquidity"]`，仅保留 `scores["etf"]`
```python
if record.get("liquidity_score") is not None:
    scores["etf"] = max(0, min(100, record["liquidity_score"] * 100))
    # 删除 scores["liquidity"] = ...
```

**方案 B**: 将 `liquidity_score` 用于独立的 liquidity 维度，etf 维度改用其他指标（如溢价率、IOPV 偏离度）

#### 优先级: P1 (高) — 多重共线性严重影响评分有效性

---

### S-MD04: DEFAULT_FILTERS 注释与实际不匹配

**文件**: `scoring.py`  
**位置**: 第 269-274 行（DEFAULT_FILTERS 定义）和第 280 行（函数 docstring）

#### 问题描述
函数 docstring 声称的默认值与 `DEFAULT_FILTERS` 实际值不一致：

| 字段 | 注释值 | 实际值 | 差异 |
|------|--------|--------|------|
| min_composite | ≥65 | ≥0.0 | 宽松 65 分 |
| max_risk | ≤40 | ≤60.0 | 宽松 20 分 |
| min_amount | ≥500 万 | ≥500 万 | 一致 |

#### 源码证据
```python
# scoring.py 第 269-274 行 — DEFAULT_FILTERS 定义
DEFAULT_FILTERS = {
    # FIXME: 数据完备后恢复 min_composite=60.0, max_risk=40.0（当前为临时宽松值）
    "min_composite":   0.0,    # 综合评分 ≥ 0（临时宽松值，待数据完备后调整为 60）
    "min_amount":    5_000_000, # 日均成交额 ≥ 500 万
    "max_risk":       60.0,   # 风险评分 ≤ 60（临时宽松值，待数据完备后调整为 40）
}

# scoring.py 第 280 行 — 函数 docstring（与实际不符）
def filter_candidate_pool(...):
    """筛选 Top ETF 候选池（默认：score≥65，成交额≥500 万，风险≤40）"""
```

#### 验证结论
**问题确认存在**。2/3 的过滤条件注释与实际值不匹配。

风险：
- 调用者根据 docstring 编写测试/预期，但实际行为不同
- FIXME 注释表明这是"临时"设置，但无自动恢复机制
- 可能导致低质量 ETF 进入候选池

#### 修复建议
1. **短期**: 更新 docstring 以匹配实际值（1h）
2. **中期**: 恢复严格值（min_composite=60, max_risk=40）并移除 FIXME
3. **长期**: 添加配置开关支持开发/生产环境切换

#### 优先级: P3 (低) — 文档问题，不影响功能正确性

---

## 修复计划建议

### 第一阶段（本周）— P1 高优先级
- [ ] **S-MD03**: 消除 etf/liquidity 多重共线性（2h）
  - 删除 `score_etf()` 中的 `scores["liquidity"]` 赋值
  - 更新测试用例

### 第二阶段（下周）— P2 中优先级
- [ ] **S-MD02**: 添加 NaN 防护（2h）
  - 在 `score_etf()` 中添加 `np.isnan()` 检查
  - 统一使用 `_f()` 工具函数处理数值转换
- [ ] **S-MD01**: Coverage 衰减改进（4h）
  - 对 coverage < 0.7 的股票标记低置信度
  - 评估是否需要插值平滑

### 第三阶段（本月）— P3 低优先级
- [ ] **S-MD04**: 修复注释不一致（1h）
  - 更新 docstring 或恢复严格过滤值

---

## 附录：源码引用索引

| 文件 | 关键行号 | 涉及问题 |
|------|----------|----------|
| `alpha.py` | 143-151 | S-MD01 |
| `scoring.py` | 613-615 | S-MD03 |
| `scoring.py` | 624-626 | S-MD02 |
| `scoring.py` | 269-274, 280 | S-MD04 |
| `etf_alpha.py` | 365 | S-MD02（正确防护示例） |

---

*报告生成时间: 2026-06-05 21:55 CST*
