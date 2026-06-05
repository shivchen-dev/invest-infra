# Task Plan: invest-infra Critical Issues Fix

**Project:** invest-infra signals + factors 模块修复  
**Date:** 2026-06-05  
**Goal:** 修复 9 个 Critical/High 问题，进入准生产可用状态

---

## Phases

### Phase 1: S-CR03 — Momentum 计算逻辑修复
- [x] scoring.py L305-307: `MAX(change_pct)` → 区间收益率
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 2: S-CR04 — 套利置信度单位修复
- [ ] etf_arbitrage.py L175-188: 阈值配置化 + net_gain 复用
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 3: S-CR05 — Fundamental 归一化修复
- [ ] scoring.py L485-490: 百分位排名替代固定倍数
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 4: S-HI01/S-HI02 — 权重归一化
- [ ] alpha.py: 权重和 1.04 → 1.0
- [ ] etf_alpha.py: 权重和 1.02 → 1.0
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 5: F-ENG-01 — 批量写入
- [ ] engine.py: execute_values() 批量 INSERT
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 6: F-TECH-01 — 数据预加载
- [ ] technical.py: 共享 DataFrame cache
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 7: F-FUND-01 — 同比增幅匹配修复
- [ ] fundamental.py: 按季度匹配而非按年
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

### Phase 8: S-HI03 — normalize() 异常处理
- [ ] etf_alpha.py: `except Exception` → 具体异常类型 + log
- [ ] Claude Code review 通过
- [ ] 端到端验证
- [ ] git commit

---

## Issue Summary

| ID | Severity | 文件 | 问题 |
|----|:--------:|------|------|
| S-CR03 | 🔴 Critical | scoring.py | 动量 MAX(change_pct) 而非区间收益率 |
| F-FUND-01 | 🔴 Critical | fundamental.py | 同比增幅按年匹配，忽略季度 |
| S-CR05 | 🟠 High | scoring.py | fundamental v*4 归一化失效 |
| S-CR04 | 🟠 High | etf_arbitrage.py | 置信度单位不一致 |
| S-HI01 | 🟠 High | alpha.py | 权重和 1.04 |
| F-ENG-01 | 🟠 High | engine.py | 逐行 INSERT |
| F-TECH-01 | 🟠 High | technical.py | 重复查询 |
| S-HI02 | 🟡 Medium | etf_alpha.py | 权重和 1.02 |
| S-HI03 | 🟡 Medium | etf_alpha.py | normalize() except Exception |

---

## Workflow

```
Step 2 审计 ✅ → Step 4 Planning files ✅ → Step 5 分批修复 → Step 6 验收
```

**Superpowers 声明规范：**
```text
Use Claude Code's Superpowers mode to refactor the code.
```