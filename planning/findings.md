# Findings: invest-infra Critical Issues

## Audit Source

**Claude Code Superpowers Audit** (2026-06-05)  
**Scope:** signals/ + factors/ modules  
**Reference commit:** `5b0893b` (2026-06-04 21:20)

---

## S-CR03: Momentum 计算逻辑错误

**文件:** scoring.py L305-307  
**严重度:** 🔴 Critical

### 问题
```sql
MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_5d
```
`MAX(change_pct)` 取期间最大单日涨幅，而非区间收益率。股票A某天涨10%但其他日子平淡，股票B稳步上涨15%但无单日超2%——反而A的动量得分更高。

### 修复方向
```sql
(LAST_VALUE(close_price) OVER / FIRST_VALUE(close_price) OVER) - 1
```
使用窗口函数计算区间收益率。

---

## F-FUND-01: 同比增幅按年匹配错误

**文件:** fundamental.py L148-159  
**严重度:** 🔴 Critical

### 问题
```python
target_year = latest_date.year - 1
prev = sub[sub["report_date"].dt.year == target_year]
```
只按年匹配，会拿 Q2 2025 对比 Q4 2024 年度报告（跨了2个季度），导致同比增幅完全错误。

### 修复方向
按季度匹配：
```python
prev = sub[(sub["report_date"].dt.year == target_year) & 
           (sub["report_date"].dt.quarter == latest_date.quarter)]
```

---

## S-CR05: Fundamental 归一化失效

**文件:** scoring.py L485-490  
**严重度:** 🟠 High

### 问题
`v * 4` 假设因子范围 [0,25]，但：
- ROE 20% → 0.8/4 = 0.2（接近0）
- Gross Margin 50% → cap at 100 → 25/4 = 6.25（总是顶满）

### 修复方向
横截面百分位排名，或针对每个指标用不同 scaling factor。

---

## S-CR04: 套利置信度单位不一致

**文件:** etf_arbitrage.py L175-188  
**严重度:** 🟠 High

### 问题
```python
net_gain = (float(abs_premium) / 100.0) - total_cost_pct
```
- `abs_premium` = 0.5 (0.5%，已除100)
- `total_cost_pct` = 0.15 (小数形式)
- 正确: `(0.5 - 0.15) / 100 = 0.0035`
- 当前: `0.005 - 0.15 = -0.145`（误判为亏损）

且 `_assess_confidence` 不使用 `cfg` 中已有阈值，重新定义了一套。

### 修复方向
阈值移入 `ArbitrageConfig`，复用 `generate_arbitrage_signals` 已计算的 `net_gain_pct`。

---

## S-HI01: alpha.py 权重和 1.04

**文件:** alpha.py L19-39  
**严重度:** 🟠 High

### 问题
19 个因子权重和 = 1.04，已有 workaround 修正，但覆盖因子不完全时仍有系统性偏差。

### 修复方向
统一缩放至 1.0：每个权重 × (1/1.04)。

---

## S-HI02: etf_alpha.py 权重和 1.02

**文件:** etf_alpha.py L25-55  
**严重度:** 🟡 Medium

### 问题
24 个因子权重和 = 1.02，且无 `expected_weight` coverage 修正。

### 修复方向
统一缩放至 1.0。

---

## S-HI03: normalize() 捕获所有异常

**文件:** etf_alpha.py L295-300  
**严重度:** 🟡 Medium

### 问题
`except Exception` 不捕获 SystemExit/KeyboardInterrupt（继承自 BaseException），但会吞掉 TypeError/ValueError 等真实 bug，silent fallback 无日志。

### 修复方向
```python
except (TypeError, ValueError) as e:
    logger.warning("zscore_norm failed (%s), falling back", e)
    return _min_max_norm(raw_values, direction)
```

---

## F-ENG-01: 逐行 INSERT

**文件:** engine.py L227-244  
**严重度:** 🟠 High

### 问题
5000股×26因子 = 13万次独立 INSERT，每次网络往返。

### 修复方向
`psycopg2.extras.execute_values()` 批量写入，单次 commit。

---

## F-TECH-01: 重复查询

**文件:** technical.py 每个 `compute()`  
**严重度:** 🟠 High

### 问题
26 个技术因子各自调用 `DataLoader.load_quotes()`，重复查询 `daily_quotes` 表 ~15 次。

### 修复方向
`engine.py` 一次加载最大 lookback（130天），传递给各 calculator 复用。

---

## 对比：评估报告 vs Claude Code

| ID | 评估报告严重度 | Claude Code 严重度 | 差异 |
|----|:-------------:|:-----------------:|:----:|
| S-CR03 | 🔴 Critical | 🔴 Critical | 一致 |
| F-FUND-01 | 🔴 Critical | 🔴 Critical | 一致 |
| S-CR05 | 🔴 Critical | 🟠 High | Claude 低估 |
| S-CR04 | 🔴 Critical | 🟠 High | Claude 低估 |
| S-HI01 | 🔴 Critical | 🟠 High | Claude 低估 |
| S-HI02 | 🟠 High | 🟡 Medium | Claude 低估 |
| S-HI03 | 🔴 Critical | 🟡 Medium | Claude 低估 |
| F-ENG-01 | 🟠 High | 🟠 High | 一致 |
| F-TECH-01 | 🟠 High | 🟠 High | 一致 |