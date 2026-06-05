# 投研系统评估报告对比分析

**生成日期**: 2026-06-04 21:50  
**评估人**: Arc  
**对比基准**: `data_collection_layer_evaluation.md` (2026-06-03) / `factors_module_evaluation.md` (2026-06-04) / `signals_module_evaluation.md` (2026-06-04)  
**源码基准**: `invest-infra/` commit `5b0893b` (2026-06-04 21:20)

---

## 一、评估摘要

三份评估报告共发现 **69 个问题**，分布在三个模块：

| 模块 | Critical | High | Medium | Low | 合计 |
|------|:--------:|:----:|:------:|:---:|:----:|
| **数据采集层** | 4 | 5 | 9 | 6 | 24 |
| **Factors 模块** | 2 | 5 | 7 | 4 | 18 |
| **Signals 模块** | 5 | 4 | 4 | 2 | 15 |
| **合计** | 11 | 14 | 20 | 12 | **57** |

> 注: 数据采集层评估报告含大量重复统计（如"重试机制缺失"在不同节反复提及），去重后实际独立问题约 24 个。

---

## 二、修复状态追踪

### 2.1 Signals 模块 — 已修复 3 项

| 问题 ID | 描述 | 状态 | 提交 |
|--------|------|:----:|------|
| **S-A01** | alpha.py ON CONFLICT 补全 norm_* 字段 | ✅ 已修复 | `8e06efa` |
| **S-A02** | 反向因子归一化方向错误（reversal rank 翻转） | ✅ 已修复 | `8e06efa` |
| **S-A03** | raw_weights 字段重命名为 cat_scores_json | ✅ 已修复 | `8e06efa` |
| **S-B01** | etf_alpha.py IOPV 除零保护 | ✅ 已修复 | `8e06efa` |
| **S-B03** | etf_alpha ON CONFLICT 补全多维评分字段 | ✅ 已修复 | `8e06efa` |
| **S-B04** | etf_alpha 阈值注释明确 | ✅ 已修复 | `8e06efa` |
| **S-C01** | 套利信号补充印花税注释 | ✅ 已修复 | `8e06efa` |
| **S-C02** | 套利阈值配置化 | ✅ 已修复 | `8e06efa` |
| **S-C03** | etf_arbitrage ON CONFLICT 补全成本字段 | ✅ 已修复 | `8e06efa` |
| **S-C04** | 拼写修正 | ✅ 已修复 | `8e06efa` |

### 2.2 Factors 模块 — 已修复 4 项

| 问题 ID | 描述 | 状态 | 提交 |
|--------|------|:----:|------|
| **F-E01** | 截面标准化迭代器 vs company_id 映射错位 | ✅ 已修复 | `de1b75c` |
| **F-E02** | std=0 时 zscore 返回 NaN → 应返回 0.0 | ✅ 已修复 | `de1b75c` |
| **F-E03** | INSERT 移除 rank 列（永不更新） | ✅ 已修复 | `de1b75c` |
| **F-E04** | sync_definitions UPSERT 补全 formula_desc/data_source/frequency | ✅ 已修复 | `de1b75c` |
| **F-B01** | load_quotes docstring 补充复权说明 | ✅ 已修复 | `de1b75c` |
| **F-B02** | DataLoader 类 docstring 补充生命周期说明 | ✅ 已修复 | `de1b75c` |
| **F-B03** | load_financial_reports docstring 补充历史记录说明 | ✅ 已修复 | `de1b75c` |

---

## 三、未修复问题清单

### 🔴 Critical — 需立即修复（影响交易决策正确性）

#### Signals 模块

| # | 问题 ID | 文件 | 描述 | 当前状态 | 风险 |
|---|--------|------|------|:--------:|------|
| 1 | **S-CR03** | `scoring.py` L303-311 | **动量计算逻辑错误**：使用 `MAX(change_pct)` 而非区间收益率 `LAST/FIRST - 1` | ❌ 未修复 | 动量评分完全错误 |
| 2 | **S-CR04** | `etf_arbitrage.py` L175 | **置信度单位不一致**：`abs_premium/100 - total_cost_pct`，0.5% 和 0.15 直接相减，单位不统一导致净收益计算错误 | ❌ 未修复 | 套利置信度误判 |
| 3 | **S-CR05** | `scoring.py` L485-490 | **fundamental 归一化错误**：`v*4` 假设因子范围 [0,25]，但 roe=0.2 → 得分仅 0.05，基本面因子几乎失效 | ❌ 未修复 | 质量因子评分失效 |
| 4 | **S-HI01** | `alpha.py` L19-39 | **权重总和不等于 1.0**：DEFAULT_WEIGHTS 总和 = 0.99 | ❌ 未修复 | 综合评分系统性偏低 1% |
| 5 | **S-HI02** | `etf_alpha.py` L25-55 | **权重总和不等于 1.0**：ETF_DEFAULT_WEIGHTS 总和 = 1.04 | ❌ 未修复 | ETF 评分系统性偏高 4% |
| 6 | **S-HI03** | `etf_alpha.py` L295-300 | **normalize() catch 所有 Exception** 捕获 KeyboardInterrupt/SystemExit | ❌ 未修复 | 程序无法正常中断 |

#### Factors 模块

| # | 问题 ID | 文件 | 描述 | 当前状态 | 风险 |
|---|--------|------|------|:--------:|------|
| 7 | **F-ENG-01** | `engine.py` L227-245 | **逐行 INSERT**：5000股×26因子=13万次独立 INSERT，性能极差 | ❌ 未修复 | 因子计算性能瓶颈 |
| 8 | **F-TECH-01** | `technical.py` | **每个因子独立重复查询相同数据**：26个因子各自调用 `_load_for_calcs()`，重复 SQL 查询 N 次 | ❌ 未修复 | 多因子计算效率极低 |
| 9 | **F-FUND-01** | `fundamental.py` L155-158 | **同比增长率按日历年而非会计年度匹配**：可能匹配到错误季度 | ❌ 未修复 | 财务因子计算偏差 |

### 🟡 Medium — 短期优化

#### Signals 模块

| # | 问题 ID | 文件 | 描述 | 当前状态 |
|---|--------|------|------|:--------:|
| 10 | **S-MD01** | `alpha.py` L143-150 | coverage 衰减导致评分分布不均匀 | ❌ 未修复 |
| 11 | **S-MD02** | `etf_alpha.py` L203 | premium_rate 可能返回 NaN | ❌ 未修复 |
| 12 | **S-MD03** | `scoring.py` L548-550 | etf 和 liquidity 维度完全相关（相同值） | ❌ 未修复 |
| 13 | **S-MD04** | `scoring.py` L229-233 | DEFAULT_FILTERS 注释与实际值不匹配 | ❌ 未修复 |

#### Factors 模块

| # | 问题 ID | 文件 | 描述 | 当前状态 |
|---|--------|------|------|:--------:|
| 14 | **F-BASE-01** | `base.py` L51 | DataLoader 连接无超时设置 | ❌ 未修复 |
| 15 | **F-BASE-02** | `base.py` L106-123 | load_latest_financial 未校验财报时效性（可能返回 3 年前数据） | ❌ 未修复 |
| 16 | **F-FUND-03** | `fundamental.py` | iterrows() 循环性能差，应使用向量化 | ❌ 未修复 |
| 17 | **F-ENG-03** | `engine.py` L188 | 每次计算都触发 sync_definitions_to_db()（冗余） | ❌ 未修复 |

### 数据采集层 — 可靠性缺失

| # | 问题 | 优先级 | 当前状态 |
|---|------|:------:|:--------:|
| 18 | 所有采集器裸 `except Exception` 吞掉异常，无重试 | 🔴 P0 | ❌ 未修复 |
| 19 | Pipeline 无错误隔离，单步失败导致全量中断 | 🔴 P0 | ❌ 未修复 |
| 20 | data_source_log / scheduler_jobs 表未使用 | 🔴 P0 | ❌ 未修复 |
| 21 | 无告警通知机制 | 🔴 P0 | ❌ 未修复 |
| 22 | 全串行采集，无并发控制 | 🟡 P1 | ❌ 未修复 |
| 23 | Loader 连接池管理不统一（部分绕过连接池） | 🟡 P1 | ❌ 未修复 |
| 24 | 跨源一致性校验缺失 | 🟡 P1 | ❌ 未修复 |

---

## 四、修复进度统计

### 按模块

| 模块 | 已修复 | 待修复 | 进度 |
|------|:------:|:------:|:----:|
| Signals（15项） | 10 | 6 | **67%** |
| Factors（18项） | 7 | 11 | **39%** |
| 数据采集层（24项） | 0 | 24 | **0%** |
| **合计** | **17** | **41** | **29%** |

### 按严重度

| 严重度 | 已修复 | 待修复 | 进度 |
|:------:|:------:|:------:|:----:|
| 🔴 Critical（11项） | 0 | 9 | **0%** ❌ |
| 🟠 High（14项） | 0 | 14 | **0%** ❌ |
| 🟡 Medium（20项） | 7 | 13 | **35%** |
| 🟢 Low（12项） | 10 | 5 | **83%** ✅ |

---

## 五、Critical 问题详细分析

### S-CR03: 动量计算逻辑错误

**文件**: `scoring.py` L303-311

```python
# 当前错误实现
mom AS (
    SELECT d.company_id,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_5d,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_20d,
           MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_60d
    FROM daily_quotes d
```

**问题**: `MAX(change_pct)` 是期间内最大单日涨幅，而非区间收益率。

**示例**: 5 天涨跌幅 `[+1%, -2%, +3%, -1%, +2%]`
- MAX = 3%（最大单日）
- 区间动量 = `close_last / close_first - 1` ≈ 实际区间收益

**影响**: 所有基于动量的评分（momentum 维度、alpha 信号）全部错误。

**修复方向**: 改用窗口函数计算区间收益率：
```sql
FIRST_VALUE(d.close_price) OVER (PARTITION BY d.company_id ORDER BY d.trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)
LAST_VALUE(d.close_price) OVER (PARTITION BY d.company_id ORDER BY d.trade_date ROWS BETWEEN 0 FOLLOWING AND 0 FOLLOWING)
-- 或使用 RANGE / ROWS UNBOUNDED PRECEDING
```

---

### S-CR04: 套利置信度单位不一致

**文件**: `etf_arbitrage.py` L175-182

```python
def _assess_confidence(abs_premium: float, liquidity_score: float, total_cost_pct: float, cfg: ArbitrageConfig) -> str:
    net_gain = (float(abs_premium) / 100.0) - total_cost_pct  # ← 单位不一致
```

**问题**:
- `abs_premium`: 0.5 = 0.5%（已除以100）
- `total_cost_pct`: 0.15 = 0.15%（已是小数形式）

**正确计算**: `net_gain = (abs_premium - total_cost_pct) / 100.0`

**当前结果**: abs_premium=0.5, total_cost_pct=0.15 → `0.005 - 0.15 = -0.145` → 错误地判定为亏损  
**正确结果**: `(0.5 - 0.15) / 100 = 0.0035` → 实际盈利

**影响**: 高置信度套利信号被误判为低置信度。

---

### S-CR05: fundamental 归一化错误

**文件**: `scoring.py` L485-490

```python
for _, key in [("roe", "roe"), ("roa", "roa"),
               ("gross_margin", "gross_margin"), ("net_profit_margin", "net_profit_margin")]:
    v = _f(record.get(key))
    if v is not None:
        scores["fundamental"] = scores.get("fundamental", 0) + max(0, min(100, v * 4)) / 4
```

**问题**: 假设 `v * 4` 能映射到 [0, 100]，但 roe 通常在 [0, 0.5]（0-50%）。

**示例**:
- roe = 0.2（20%）→ `max(0, min(100, 0.2*4)) / 4 = 0.8 / 4 = 0.2`
- 4 个指标各贡献 0.2 → fundamental 维度得分 = 0.2（满分 100）

**影响**: fundamental 维度评分几乎总是接近 0，质量因子在综合评分中完全失效。

**修复方向**: 使用百分位排名替代固定倍数映射。

---

### F-ENG-01: 逐行 INSERT 性能极差

**文件**: `engine.py` L227-245

```python
for v in values:
    if v["value"] is None:
        continue
    pct = pct_map.get(v["company_id"])
    zsc = zscore_map.get(v["company_id"])
    cur.execute(
        """INSERT INTO factor_values ... VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (v["company_id"], fd_id, calc_date, v["value"], pct, zsc, batch_label),
    )
    written += 1
conn.commit()  # 每个因子一次 commit
```

**影响**: 5000股 × 26因子 = 13万次独立 INSERT，每次包含连接/解析/执行/提交开销。

**修复方向**: 使用 `psycopg2.extras.execute_values()` 批量写入：
```python
from psycopg2.extras import execute_values
rows = [(v["company_id"], fd_id, calc_date, v["value"], pct, zsc, batch_label)
        for v in values if v["value"] is not None]
execute_values(cur, """INSERT INTO factor_values ... VALUES %s""", rows)
conn.commit()  # 一次 commit
```

---

## 六、修复优先级建议

```
立即修复（影响交易决策正确性）:
  [1] S-CR03 动量计算逻辑
  [2] S-CR04 套利置信度单位
  [3] S-CR05 fundamental 归一化
  [4] F-ENG-01 批量写入

本周修复（影响评分准确性）:
  [5] S-HI01/S-HI02 权重归一化
  [6] F-TECH-01 数据预加载缓存

短期优化（可靠性）:
  [7] 数据采集层重试机制 + 错误隔离
  [8] 审计日志 + 告警通知
  [9] F-BASE-01 连接超时设置
```

---

## 七、结论

- **已修复**: 17/57 (29%)，主要集中在 Signals 的 ON CONFLICT 补全和 Factors 的 engine.py 基础修复
- **Critical 问题**: 0/11 已修复（0%），全部 9 个 Critical 问题仍未解决
- **最大风险**: 
  1. Signals 模块 CRIT-003/004/005 影响交易决策正确性
  2. Factors 模块 F-ENG-01 逐行 INSERT 性能极差
  3. 数据采集层全面缺失重试/告警/审计机制

**建议**: 优先修复 9 个 Critical 问题，这些是系统性风险。Critical 问题修复后，整体投研系统可进入准生产可用状态。

---

*本报告基于评估报告与源码 git diff 对比生成，生成时间 2026-06-04 21:50。*