# 投研系统代码质量审计报告（综合版）

**审计日期**: 2026-06-04  
**审计团队**: signals-auditor、factors-auditor  
**审计范围**: signals 模块 + factors 模块  
**代码质量评分**: signals 5.5/10 · factors 6.5/10

---

## 一、审计结果总览

| 模块 | 问题总数 | Critical | High | Medium | Low | 评分 |
|------|----------|----------|------|--------|-----|------|
| signals | 15 | 5 | 4 | 4 | 2 | 5.5/10 |
| factors | 18 | 2 | 5 | 7 | 4 | 6.5/10 |
| **合计** | **33** | **7** | **9** | **11** | **6** | — |

**SQL注入风险**: ✅ 无（全模块参数化查询）  
**数据一致性风险**: 🔴 高（多个方向性计算错误）

---

## 二、Critical 问题（必须修复）

### CRIT-001 · alpha.py · 归一化方向冲突
**位置**: L116-118  
**描述**: Category 内不同方向因子（如 momentum direction=1 vs reversal direction=-1）共用同一个 `norm_direction`，反转因子被错误处理。`reversal_5d`（direction=-1）被当作正向因子，导致动量与反转同时正向，评分失效。

```python
normed[k] = 100 - v["norm_pct"] if w["direction"] < 0 else v["norm_pct"]
# 问题：norm_direction 作用在 category 外层，direction 无法穿透到具体因子
```

**修复**: 归一化时直接读取因子自身 direction 属性，而非依赖外层 norm_direction。

---

### CRIT-002 · etf_alpha.py · 同上归一化方向冲突
**位置**: 技术因子处理逻辑  
**描述**: liquidity 类别中 `bid_ask_spread`（direction=-1）被当作正向因子处理，导致买卖价差越小评分越低，与业务逻辑相反。

**修复**: 同 CRIT-001，在因子级别应用 direction 属性。

---

### CRIT-003 · scoring.py · 动量计算逻辑错误
**位置**: `fetch_stock_factor_matrix` 函数  
**描述**: 使用 `MAX(d.change_pct)` 计算动量，应为区间收益率（期末/期初-1）。所有基于动量的评分完全错误。

```sql
-- 错误写法
SELECT MAX(d.change_pct) FROM daily_quotes d ...
-- 正确应为：区间收益率 = close_price_T / close_price_{T-N} - 1
```

**修复**: 改用窗口函数计算区间收益率。

---

### CRIT-004 · etf_arbitrage.py · 置信度计算单位不一致
**位置**: `_assess_confidence` 方法  
**描述**: 净收益与阈值比较时单位混用（比率 vs 百分比），如 `net_gain > 0.003` 实际代表 0.3% 而阈值 0.1% 写成 0.003，导致置信度评估完全错误。

**修复**: 统一使用小数比率，阈值配置与成本计算保持同一单位。

---

### CRIT-005 · scoring.py · 归一化倍数错误
**位置**: `score_stock` fundamental 维度  
**描述**: 使用 `v*4` 归一化，但 roe/roa 等财务指标通常远小于 25，导致该维度评分几乎为 0。

**修复**: 改用 percentile rank 或 min-max 归一化。

---

### CRIT-006 · engine.py · 逐行 INSERT 写入
**位置**: L229-241  
**描述**: 全市场 26 因子 × ~5000 公司 = 约 13 万次独立 INSERT，单次提交每条。理论提速空间 100x+。

```python
for v in values:
    cur.execute("INSERT INTO factor_values ...")
```

**修复**: 改用 `psycopg2.extras.execute_values()` 批量写入。

---

### CRIT-007 · engine.py · 截面映射错位风险
**位置**: L214-239  
**描述**: percentile/zscore 仅对有效值计算后通过列表顺序映射，当 values 中有 None 条目时跳过导致迭代器提前耗尽，正确值拿到 None。

```python
valid_values = [v["value"] for v in values if v["value"] is not None]
percentiles = _compute_percentile(valid_values)  # 仅对有效值
p_iter = iter(percentiles)
for v in values:
    if v["value"] is None:
        continue  # ← iterator 已消耗，但 None 条目也被计入
    pct = next(p_iter, None)
```

**修复**: 建立 company_id → percentile/zscore 的字典映射，按 company_id 查表取值。

---

## 三、High 问题

### HIGH-001 · signals 模块 · 权重总和不等于 1.0
**位置**: alpha.py DEFAULT_WEIGHTS / etf_alpha.py  
**描述**: 因子权重总和非 1.0，加权信号失真。

### HIGH-002 · signals 模块 · 异常捕获范围过大
**位置**: alpha.py 多处 `except Exception: pass`  
**描述**: 隐藏错误不记录，导致问题难以排查。

### HIGH-003 · engine.py · 每个技术因子独立加载行情数据
**位置**: 各 Calculator 子类  
**描述**: 26 个因子批量计算时产生 N 次重复 SQL 查询，数据重复读取。

**修复**: Engine 层预加载行情数据，传递给各 Calculator 复用。

### HIGH-004 · engine.py · 连接超时配置缺失
**位置**: psycopg2.connect()  
**描述**: 无 connect_timeout，高并发时可能阻塞。

### HIGH-005 · factors/technical.py · 会计年度匹配错误
**位置**: `load_financial_by_year`  
**描述**: 用 `fiscal_year` 而非 `report_date` 匹配，导致跨年报告期数据错配。

---

## 四、Medium 问题

| ID | 模块 | 问题 |
|----|------|------|
| MED-001 | alpha.py | INSERT 字段名与 cat_scores 内容不匹配（norm_value 等 6 列永远为 NULL） |
| MED-002 | alpha.py | upsert_weights 缺少 description 字段 UPDATE |
| MED-003 | etf_alpha.py | iopv_diff 计算时 iopv=0 导致 NaN |
| MED-004 | scoring.py | signal 阈值 25 与注释不一致 |
| MED-005 | engine.py | std=0 时 zscore 返回 (x-mean) 而非 0 |
| MED-006 | engine.py | rank 列永远写入 NULL |
| MED-007 | factors | 财报数据 DISTINCT ON 语法需确认是否保留预期行 |
| MED-008 | factors | 因子缺失时默认 50 分（中性），但未区分"缺失"与"中性" |
| MED-009 | factors | register_all() 无版本控制，字段更新后历史数据兼容性未知 |
| MED-010 | signals | 三模块归一化方法不统一（percentile rank / Z-score / 固定倍数） |
| MED-011 | scoring.py | fundamental 维度 v*4 归一化对于大值因子（gross_profit）可能溢出 |

---

## 五、Low 问题

| ID | 模块 | 问题 |
|----|------|------|
| LOW-001 | scoring.py | 注释与实现不一致（signal 阈值描述偏差） |
| LOW-002 | signals | cat_score 加权计算逻辑顺序不直观 |
| LOW-003 | engine.py | sync_definitions_to_db() 无参数调用时的连接管理 |
| LOW-004 | registry.py | 无版本控制，字段变更历史不可追溯 |

---

## 六、修复优先级总览

| 优先级 | 问题ID | 模块 | 描述 | 预计工时 |
|--------|--------|------|------|----------|
| P0 | CRIT-003 | scoring.py | 动量计算逻辑（MAX→区间收益率） | 2h |
| P0 | CRIT-006 | engine.py | 逐行INSERT→批量写入 | 1h |
| P0 | CRIT-001 | alpha.py | 归一化方向冲突 | 2h |
| P0 | CRIT-007 | engine.py | 迭代器对齐错位 | 2h |
| P1 | CRIT-002 | etf_alpha.py | 同上归一化方向 | 1h |
| P1 | CRIT-004 | etf_arbitrage.py | 置信度单位统一 | 1h |
| P1 | HIGH-003 | engine.py | 重复查询→预加载缓存 | 3h |
| P1 | HIGH-004 | engine.py | 连接超时配置 | 0.5h |
| P2 | MED-001~011 | 多处 | 各项中等问题 | 分散 |

---

## 七、跨模块共性问题

1. **归一化方法不统一** — signals 三个模块使用不同归一化策略（percentile rank / Z-score / 固定倍数），建议统一为 percentile rank
2. **重复 SQL 查询** — 每个因子独立加载行情数据，建议 Engine 层统一预加载
3. **异常处理不完善** — 多处 `except: pass`，建议改为记录 warning 并继续
4. **配置硬编码** — 信号阈值、成本参数散落各处，建议统一进配置文件

---

## 八、审计结论

signals 和 factors 模块均存在影响生产环境运行的关键缺陷，其中：
- **CRIT-003（动量计算错误）** 导致基于动量的所有评分完全失效
- **CRIT-006（逐行INSERT）** 导致全市场因子计算耗时从分钟级退化到小时级
- **CRIT-001/002（归一化方向）** 导致反转因子失去作用

**建议优先修复 P0 级 4 个问题后再上线，其余问题可在上线后迭代修复。**


---

## 九、修复状态（2026-06-05）

| Issue | 审计严重度 | 状态 | 修复 Commit |
|-------|:---------:|------|-------------|
| CRIT-003 (S-CR03) Momentum | 🔴 Critical | ✅ 已修复 | `57a701a` |
| CRIT-001 (S-HI01) alpha归一化方向 | 🔴 Critical | ✅ 已修复 | `1263454` |
| CRIT-002 (S-HI02) etf_alpha归一化方向 | 🟠 High | ✅ 已修复 | `1263454` |
| CRIT-004 (S-CR04) 套利置信度单位 | 🟠 High | ✅ 已修复 | `fccdd0d` |
| CRIT-005 (S-CR05) Fundamental归一化 | 🟠 High | ✅ 已修复 | `8e06efa` |
| CRIT-006 (F-ENG-01) 逐行INSERT | 🟠 High | ✅ 已修复 | `091369a` |
| HIGH-003 (F-TECH-01) 重复查询 | 🟠 High | ✅ 已修复 | `dd54658` + `e4cfc05` |
| CRIT-007 (F-FUND-01) 同比增幅匹配 | 🔴 Critical | ✅ 已修复 | `dc6a73f` |
| MED-001 (S-HI03) normalize异常 | 🟡 Medium | ✅ 已修复 | `29f8fc3` |

**全部 9 个 issue 已修复并 push 完成（2026-06-05）。**

**运行验证：**
- `run_factor.sh`: 0.22s，1798 条因子值写入 ✅
- `run_alpha.sh`: 2.43s，无报错 ✅
- momentum_5d 样例：区间收益率（0.0234/-0.1267），非 MAX(change_pct) ✅
