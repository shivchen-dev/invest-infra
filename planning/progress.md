# Progress: invest-infra Critical Issues Fix

## Session Log

### 2026-06-05

| 时间 | 阶段 | 操作 | 结果 |
|------|------|------|------|
| 12:25 | Phase 1 | S-CR03 Momentum | ✅ committed & pushed (57a701a) |
| 12:30 | Phase 2 | S-CR04 套利置信度 | ✅ committed & pushed (fccdd0d) |
| 13:02 | Phase 3 | S-CR05 Fundamental归一化 | ✅ 代码已修复（commit 8e06efa）|
| 13:10 | Phase 4 | S-HI01/S-HI02 权重归一化 | ✅ committed & pushed (1263454) |
| 13:11 | Phase 4 | S-HI03 normalize异常 | ✅ committed & pushed (29f8fc3) |
| 13:12 | Phase 4 | F-FUND-01 同比增幅匹配 | ✅ committed & pushed (dc6a73f) |

---

## Phase Status

| Phase | Issue | 状态 |
|-------|-------|------|
| Phase 1 | S-CR03 Momentum | ✅ committed & pushed (57a701a) |
| Phase 2 | S-CR04 套利置信度 | ✅ committed & pushed (fccdd0d) |
| Phase 3 | S-CR05 Fundamental归一化 | ✅ 代码已修复（commit 8e06efa）|
| Phase 4 | S-HI01/S-HI02/S-HI03/F-FUND-01 | ✅ all done (1263454/29f8fc3/dc6a73f) |
| Phase 5 | F-ENG-01 批量写入 | ⏳ pending |
| Phase 6 | F-TECH-01 数据预加载 | ⏳ pending |
| Phase 7 | F-FUND-01 同比增幅匹配 | pending |
| Phase 8 | S-HI03 normalize异常 | pending |

---

## 待核对清单

⚠️ findings.md 状态落后于代码，评估报告里的缺陷可能已被修复。需逐项核对：

| Issue | findings.md 状态 | 代码实际 | 需更新? |
|-------|----------------|---------|--------|
| S-CR05 | pending | ✅ 已修复（8e06efa `_normalize_fundamentals`） | ✅ |
| S-CR04 | pending | ✅ 已修复（fccdd0d） | ✅ |
| S-HI01 | pending | ⚠️ 需核对 alpha.py | pending |
| S-HI02 | pending | ⚠️ 需核对 alpha.py | pending |
| S-HI03 | pending | ⚠️ 需核对 | pending |
| F-ENG-01 | pending | ⚠️ 需核对 | pending |
| F-TECH-01 | pending | ⚠️ 需核对 | pending |
| F-FUND-01 | pending | ⚠️ 需核对 | pending |

---

## 测试状态

- pytest：18 failed（全部是 CIFANG_TOKEN env var 缺失，非本次修复引起）
- 本次 S-CR03/S-CR04 修复为 SQL 逻辑变更，测试环境需额外配置才能跑

---

## S-CR03 修复内容

**文件：** `data-pipeline/src/signals/scoring.py` L305-330

**改动：** mom CTE 从 `MAX(change_pct)` 改为区间收益率：
```sql
-- 旧（错误）：
MAX(d.change_pct) FILTER(WHERE d.trade_date BETWEEN %s AND %s) AS mom_5d

-- 新（正确）：
(ld.close_price / NULLIF(e5.close_price, 0)) - 1 AS mom_5d
```

commit: 57a701a

---

## S-CR04 修复内容

**文件：** `data-pipeline/src/signals/etf_arbitrage.py` L182

**改动：** `_assess_confidence` 中 net_gain 计算单位修复：
```python
# 旧（错误）：abs_premium 已除100，total_cost_pct 没除
net_gain = (float(abs_premium) / 100.0) - total_cost_pct

# 新（正确）：两者都是 % 单位，相减后除100转小数
net_gain = (abs_premium - total_cost_pct) / 100.0
```

commit: fccdd0d

---

## S-CR05 修复内容（已存在）

**文件：** `data-pipeline/src/signals/scoring.py`

**已修复于 commit 8e06efa：**
- 新增 `_normalize_fundamentals` 函数（L38-69），使用 `scipy.stats.rankdata` 对 batch 内所有 fundamental 指标做百分位排名
- `score_stock` 改用 `record["fundamental_pct"]` 而非原始 `v*4`
- 注释写明：`避免固定乘数 (v*4) 对不同量纲数据的扭曲`

---

## 下一步

逐项核对 findings.md 和当前代码状态，确认每个 pending 项的真实状态