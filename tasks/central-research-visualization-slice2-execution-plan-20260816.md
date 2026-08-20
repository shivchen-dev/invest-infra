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

## Task 2B：候选与外部机会摘要（已完成代码交付）

- 结果：中心分别返回内部 Candidate Pool 最新发布运行摘要与外部 Opportunity Radar 有界观察摘要；不改变既有 market/research 顶层状态。
- 验收：Candidate Pool、ExternalObservation、Admission 三类状态不混用；Candidate Pool 与 Opportunity Radar 各自使用 `available | empty | failed`；Opportunity Radar 查询固定 `limit=50`，仅投影数量、最新 `as_of` 和准入状态计数。
- 异常：Candidate Pool 查询/快照完整性异常与外部 SQLAlchemy 查询异常转换为脱敏失败状态；未知程序异常继续抛出。
- 验证：Application/API focused tests、全量 API tests、Ruff、OpenAPI drift、架构边界检查。
- 依赖：2A；复用既有查询服务和 DTO。

## Task 2C：中心首页整合（已完成代码交付）

- 结果：Dashboard 使用同一份 Research Center 查询展示 Candidate Pool 与 Opportunity Radar 只读摘要卡片，并分别进入既有详情页。
- 验收：两卡片覆盖 loading/empty/failed；Candidate Pool、ExternalObservation、Admission status 分层展示；不新增重复查询、不执行浏览器写操作、不泄漏运行身份或外部来源字段。
- 验证：Web 全量测试 201 passed（27 files）、typecheck、production build、独立代码审查通过。
- 依赖：2A、2B。

## Task 3A：交付链摘要

- 结果：中心分别呈现 Pipeline、Integration Health、Artifact/archive、Research Run 状态。
- 验收：归档成功、业务准入、研究完成保持独立；复用现有 API/Reader。
- 依赖：Checkpoint 2。

### Task 3A 拆分

1. **3A-API：交付链只读聚合**
   - 复用 `PipelineRunQueryService.get_latest_run()`、`ExternalWorkflowQueryService.health()` 及既有 Research Run / Artifact reader；不在中心模块直接访问数据库或 HTTP。
   - 只投影状态、计数、业务日期/时间和有界归档事实；不透传 artifact URI、payload、宿主路径、凭据或原始异常。
   - Pipeline、Integration、Archive、Research Run 保持独立子状态，单来源受控失败不得污染其他子状态。

2. **3A-Web：交付链摘要卡**
   - 使用 Research Center 单一聚合响应渲染交付链卡片，复用 `/operations`、`/automation`、Research History 等既有详情入口。
   - 覆盖 loading、empty、running、succeeded、partial、failed；不新增浏览器写操作和重复资源请求。

3. **3A-验收与收口**
   - API focused/full tests、Web focused/full tests、typecheck、production build、OpenAPI drift、架构边界检查和代码代理审查全部通过后，才标记 3A 完成。
   - 真实 WorkBuddy/JiuwenSwarm 链路仍属于 3C/Gate B，不以本地 mock 代替真实验收。

## Task 3B：可信度与异常状态

- 结果：交付链卡片补齐 freshness/quality/source/原因和脱敏异常展示。
- 验收：不泄漏宿主路径/凭据；cancelled orphan 可解释且不阻断其他卡片；刷新恢复。
- 依赖：3A。

### Task 3B 拆分

1. **3B-API：可信度与脱敏契约**
   - 在四个 delivery 子段（pipeline / integration / archive / research_runs）上新增最小兼容扩展：``freshness_at`` 锚点（基于真实 ``finished_at`` / ``latest_as_of`` / ``latest_finished_at``）和 ``source`` 标签（基于真实 ``trigger_type`` / ``producer`` / ``media_type`` / ``runner_key``）；不引入新的虚构字段，不修改既有 3A 字段含义。
   - 统一 reason / 错误展示：禁止宿主绝对路径、连接串、凭据、原始异常堆栈进入 API 响应；reason 仅取 3A 已有的稳定 token（``pipeline_query_failed`` / ``integration_health_query_failed`` / ``archive_query_failed`` / ``research_runs_query_failed``），新增 token 仅用于 ``capabilities.delivery`` 的 ``slice_3b_delivery_summary_available`` 升级。
   - cancelled / orphan pipeline run：保留 3A 的 ``partial`` 语义（``cancelled`` / 未知 terminal 状态），不再阻断其他 delivery 子段查询；任何子段失败仅污染自身槽位。
   - 失败恢复：每个调用都是 fresh materialisation，无内部缓存；下一次 refresh 即恢复，单元测试断言先 ``failed`` 再 ``available`` 的回放。
   - ``capabilities.delivery``：从 Slice 1 ``slice_3_not_implemented`` 占位升级到 ``available / slice_3b_delivery_summary_available``；``ResearchCenterCapabilityState`` Literal 最小扩展为 ``deferred | unavailable | available``。
2. **3B-Web：可信度与脱敏卡片**
   - 由 Web 团队后续切片处理；本次仅交付 API 与 OpenAPI 契约。
3. **3B-验收与收口**
   - API focused tests + 全量 API tests + ruff + OpenAPI drift + 架构边界检查 + 域/存储单元测试保持通过；任何子段失败原因字符串、``source`` 标签、``freshness_at`` 锚点都不允许泄漏 forbidden token（``postgres`` / ``postgresql`` / ``secret`` / ``password`` / ``/home/`` / ``Traceback`` / ``Connection refused``）。

## Task 3C：真实环境收口

- 结果：保留真实、stale/unavailable、外部交付异常三种验收证据并校准 Gate B。
- 阻碍：需要真实环境数据/WorkBuddy + JiuwenSwarm 组合根，代码本身不应伪造通过。
- 依赖：3B。

## 检查点

- Checkpoint 2A：API focused tests、OpenAPI drift、完整 diff 审查通过后再进入 2B（已通过）。
- Checkpoint 2：2A–2C 的 API/Web focused tests、typecheck、production build 通过后再进入 3A（已通过：API 347、Web 201、OpenAPI drift、架构边界检查均通过）。
- Gate B：3A–3C 证据齐全且用户审核通过后才宣称 MVP 完成。
