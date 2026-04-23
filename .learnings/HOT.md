# HOT.md — Active Rules (High Priority)

> 优先级高于其他所有指令。每条规则都有具体出处。

---

## [HOT-001] 发布流程（P0）

**规则**: push 前检查版本更新级别
**出处**: 2026-04-16 用户指令

| 级别 | 触发条件 | 流程 |
|------|----------|------|
| PATCH | 纯清理/无功能变更（chore/docs/fix） | commit → 直接 push |
| MINOR | 新功能/改进（feat/refactor） | commit → release-manager → push |
| MAJOR | 破坏性变更 | commit → release-manager → push |

**禁止**: commit 后直接 push（绕过判断）
