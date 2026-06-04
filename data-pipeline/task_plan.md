# Task Plan: factors 模块修复

## 评估报告 vs Claude Code 审计对比
- 评估报告：4个缺陷（P0×1, P1×2, P2×1）
- Claude Code：9个缺陷（P0×1, P1×5, P2×3）
- **新增发现**：E04 UPSERT遗漏3字段、B01复权说明缺失、R01同源问题

---

## 合并缺陷清单（8项）

| # | 文件 | 严重度 | 缺陷 | 来源 |
|---|------|--------|------|------|
| 1 | engine.py | 🔴P0 | 迭代器索引错位（E01） | 共同 |
| 2 | engine.py | 🟡P1 | std=0时zscore返回错误（E02） | 共同 |
| 3 | engine.py | 🟡P1 | rank字段永不更新（E03） | 共同 |
| 4 | engine.py | 🟡P1 | UPSERT遗漏3字段（E04） | Claude Code新发现 |
| 5 | base.py | 🟡P1 | load_quotes缺复权说明（B01） | Claude Code新发现 |
| 6 | registry.py | 🟡P1 | sync UPSERT遗漏3字段（R01） | Claude Code新发现 |
| 7 | base.py | 🟢P2 | conn生命周期注释缺失（B02） | Claude Code |
| 8 | base.py | 🟢P2 | docstring歧义（B03） | Claude Code |

---

## Batch 1: engine.py（核心修复）
- [ ] E01: 迭代器索引错位 → 改用 company_id 字典映射
- [ ] E02: std=0时zscore应返回全0
- [ ] E03: rank字段写入/移除
- [ ] E04: UPSERT补全formula_desc/data_source/frequency
- **Status:** pending

## Batch 2: base.py + registry.py（P1/P2）
- [ ] B01: load_quotes复权说明
- [ ] R01: sync UPSERT补全3字段
- [ ] B02: conn生命周期注释
- [ ] B03: docstring补充
- **Status:** pending

---

## 工作流
- [x] 评估报告审计
- [x] Claude Code 审计
- [x] 对比分析
- [ ] Batch 1 执行中
- [ ] Batch 2
- [ ] git commit
- [ ] 归档 reports/audit_comparison_2026-06-04.md