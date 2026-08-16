# 中心投研可视化 Slice 2/3 执行拆分（2026-08-16）

## 目标

在既有 Slice 1 市场状态代码之上，逐步把已有只读 Research、Candidate Pool、Opportunity Radar、Integration/Artifact 查询接入中心入口；不新增业务写操作，不制造模拟数据，不改变详情页职责。

## 依赖顺序

```text
2A Research Center ← ResearchQueryService.get_dashboard()
  ↓
2B Candidate/Opportunity Center summary ← existing read-only query services
  ↓
2C Dashboard cards and detail links
  ↓
3A Pipeline/Integration/Archive summary
  ↓
3B delivery confidence and redacted failure states
  ↓
3C real-environment acceptance record and Gate B closeout
```

## Task 2A：研究摘要聚合（已完成代码交付）

- 结果：`research-center` 返回 Research Case/Run/Evidence 摘要，状态可区分 available/empty/failed；市场顶层状态继续独立保留 partial。
- 来源：既有 `ResearchQueryService.get_dashboard()`，不直接访问数据库，不新增表。
- 验收：count、latest case、run/evidence 状态来自真实 Reader；数据库查询异常转为稳定失败状态；策略/持仓字段不混入。
- 验证：API application/endpoint focused tests；OpenAPI 生成与 drift check。

## Task 2B：候选与外部机会摘要

- 结果：中心分别展示内部 Candidate Pool 与外部 Opportunity Radar 的摘要和来源状态。
- 验收：CandidatePool、ExternalObservation、Admission 三类状态不混用；空/部分/失败可解释。
- 依赖：2A；复用既有查询服务和 DTO。

## Task 2C：中心首页整合

- 结果：Dashboard 仅展示摘要卡片，每项进入现有详情页；Research Center API 成为中心聚合来源。
- 验收：loading/empty/partial/stale/failed；浏览器无写操作；无宿主机路径；Web focused tests、typecheck、build。
- 依赖：2A、2B。

## Task 3A：交付链摘要

- 结果：中心分别呈现 Pipeline、Integration Health、Artifact/archive、Research Run 状态。
- 验收：归档成功、业务准入、研究完成保持独立；复用现有 API/Reader。
- 依赖：Checkpoint 2。

## Task 3B：可信度与异常状态

- 结果：交付链卡片补齐 freshness/quality/source/原因和脱敏异常展示。
- 验收：不泄漏宿主路径/凭据；cancelled orphan 可解释且不阻断其他卡片；刷新恢复。
- 依赖：3A。

## Task 3C：真实环境收口

- 结果：保留真实、stale/unavailable、外部交付异常三种验收证据并校准 Todo/Gate B。
- 阻碍：需要真实环境数据/WorkBuddy + JiuwenSwarm 组合根，代码本身不应伪造通过。
- 依赖：3B。

## 检查点

- Checkpoint 2A：API focused tests、OpenAPI drift、完整 diff 审查通过后再进入 2B。
- Checkpoint 2：2A–2C 的 API/Web focused tests、typecheck、production build 通过后再进入 3A。
- Gate B：3A–3C 证据齐全且用户审核通过后才宣称 MVP 完成。
