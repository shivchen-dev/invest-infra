# 投研系统计划审计报告

**审计日期**: 2026-06-07
**审计团队**: signals-auditor、factors-auditor、system-auditor
**审计范围**: 
- `planning/2026-06-05_critical_fix/` — 关键问题修复计划
- `planning/2026-06-07_sector_filter_design/` — 行业ETF板块筛选技术设计

---

## 一、2026-06-05_critical_fix 修复计划审计

### 1.1 计划完整性评估

| Phase | Issue | task_plan.md 修复描述 | findings.md 问题描述 | 对应性 |
|-------|-------|---------------------|---------------------|:------:|
| Phase 1 | S-CR03 | `MAX(change_pct)` → 区间收益率 | 动量计算逻辑错误 | ✅ 一致 |
| Phase 2 | S-CR04 | 阈值配置化 + net_gain 复用 | 套利置信度单位不一致 | ✅ 一致 |
| Phase 3 | S-CR05 | v*4 → 百分位排名 | 归一化失效 | ✅ 一致 |
| Phase 4 | S-HI01/S-HI02 | 1.04→1.0, 1.02→1.0 | 权重和偏差 | ✅ 一致 |
| Phase 5 | F-ENG-01 | execute_values() 批量写入 | 逐行INSERT性能问题 | ✅ 一致 |
| Phase 6 | F-TECH-01 | 共享 DataFrame cache | 重复查询 | ✅ 一致 |
| Phase 7 | F-FUND-01 | 按季度匹配而非按年 | 同比增幅匹配错误 | ✅ 一致 |
| Phase 8 | S-HI03 | 具体异常类型 + log | 异常吞掉bug | ✅ 一致 |

**结论：所有 8 个 Phase 与 9 个 Issue 均正确对应。**

### 1.2 修复状态汇总

| Issue | Severity | findings.md状态 | Commit | 验证结论 |
|-------|:--------:|----------------|--------|----------|
| S-CR03 | 🔴 Critical | ✅ 已修复 | `57a701a` | ✅ 已修复 |
| S-CR04 | 🟠 High | ✅ 已修复 | `fccdd0d` | ✅ 已修复 |
| S-CR05 | 🟠 High | ✅ 已修复 | `8e06efa` | ✅ 已修复 |
| S-HI01 | 🟠 High | ✅ 已修复 | `1263454` | ✅ 已修复 |
| S-HI02 | 🟡 Medium | ✅ 已修复 | `1263454` | ✅ 已修复 |
| S-HI03 | 🟡 Medium | ✅ 已修复 | `29f8fc3` | ✅ 已修复 |
| F-FUND-01 | 🔴 Critical | ✅ 已修复 | `dc6a73f` | ✅ 已修复 |
| F-ENG-01 | 🟠 High | ✅ 已修复 | `091369a` | ✅ 已修复 |
| F-TECH-01 | 🟠 High | ✅ 已修复 | `dd54658` + `e4cfc05` | ✅ 已修复 |

**9 个 Issue 全部已修复并 push 完成。**

### 1.3 需整改项

| 优先级 | 问题 | 建议 |
|:------:|------|------|
| 🔴 高 | progress.md 与 findings.md 状态不一致（Phase 7/8 标记为 pending 但实际已修复） | 更新 progress.md 文档 |
| 🟠 中 | 4 个 issue 严重度被低估（评估报告为 Critical，Claude Code 评为 High/Medium） | 修复后加强监控 |

### 1.4 严重度低估清单

| Issue | 评估报告严重度 | Claude Code 严重度 | 风险 |
|-------|:-------------:|:-----------------:|------|
| S-CR05 | 🔴 Critical | 🟠 High | 归一化失效影响评分准确性 |
| S-CR04 | 🔴 Critical | 🟠 High | 套利信号误判 |
| S-HI01 | 🔴 Critical | 🟠 High | 系统性偏差 |
| S-HI03 | 🔴 Critical | 🟡 Medium | 静默失败 |

---

## 二、2026-06-07_sector_filter_design 技术设计审计

### 2.1 架构设计评估

**整体流程**：Phase 1 → Phase 2 → Phase 3 → Phase 4

| 阶段 | 功能 | 工具 | 估算调用量 |
|------|------|------|-----------|
| Phase 1 | 强势行业识别 | sector_analysis | 1 次 |
| Phase 2 | 成分股获取 | stock_screener | 3 次 |
| Phase 3 | K线+估值数据 | kline + valuation_snapshot | 约 10 次 |
| Phase 4 | 本地计算筛选 | 本地脚本 | — |
| **合计** | | | | **约 14 次** |

**评估：架构流程清晰，API 调用量可控。**

### 2.2 关键问题（需修复后方可实施）

| 优先级 | 问题 | 状态 | 建议 |
|:------:|------|------|------|
| 🔴 P0 | **Phase 1-2 行业映射未验证**：`sector_analysis` 行业名与 `stock_screener.conceptKeywords` 可能不匹配 | ⬜ 需验证 | 实施前必须验证映射关系 |
| 🔴 P0 | **signal_strength 公式无下界保护**：偏离度超过 10% 时贡献为负数 | ⬜ 需修复 | 增加 `max(0, ...)` 下界保护 |
| 🟡 P1 | **分类标签逻辑重叠**：`稳健型` 和 `进取型` 在 `deviation_ma20 ∈ (0, 5)` 且 `pct_chg_20d > 0` 时同时满足 | ⬜ 需修复 | 重构 classify() 逻辑 |
| 🟡 P1 | **停牌股票处理缺失**：volume=0 时数据异常 | ⬜ 需补充 | 补充过滤逻辑 |

### 2.3 修复建议

#### signal_strength 下界保护
```python
signal_strength = max(0, 
    0.3 * max(0, 1 - abs(deviation_ma20) / 10) +
    0.3 * max(0, 1 - abs(pct_chg_20d) / 30) +
    0.2 * min(volume_ratio, 2) / 2 +
    0.2 * (1 if classification in ["稳健型", "进取型"] else 0.5)
)
```

#### 分类标签重构
```python
def classify(row):
    if row['deviation_ma20'] < -10:
        return "超跌型"
    elif abs(row['deviation_ma20']) <= 5 and abs(row['deviation_ma60']) <= 10:
        return "稳健型"
    elif row['pct_chg_20d'] > 0 and row['price'] > row['ma20']:
        return "进取型"
    else:
        return "震荡型"
```

---

## 三、综合审计结论

| 计划 | 状态 | 建议 |
|------|------|------|
| 2026-06-05_critical_fix | ✅ 计划完整、可行 | 整改 progress.md 后可进入准生产 |
| 2026-07_sector_filter_design | ⚠️ 需修复 P0 问题 | 修复后重新审计方可实施 |

### 立即行动项

- [ ] 更新 `planning/2026-06-05_critical_fix/progress.md`，标记 Phase 7/8 为已完成
- [ ] 验证 `sector_analysis` 与 `stock_screener` 行业映射关系
- [ ] 修复 `signal_strength` 公式的下界保护
- [ ] 重构 `classify()` 消除标签重叠逻辑
- [ ] 补充停牌股票过滤逻辑

---

## 四、审计历史归档

| 日期 | 审计类型 | 状态 |
|------|---------|------|
| 2026-06-04 | 综合审计报告 | ✅ 已归档 |
| 2026-06-05 | 复验报告 | ✅ 已归档 |
| 2026-06-07 | 计划审计 | 📌 当前报告 |

---

*本报告由投研系统审计团队于 2026-06-07 生成。*