# Stage 4D MVP 分阶段执行计划

> 文档版本：v1.0
> 文档状态：ACTIVE（当前范围为 Stage 4D 收口）
> 计划治理：`docs/plan/README.md`
> 制定日期：2026-08-14
> 上位蓝图：`docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md`
> 当前范围：Stage 4D MVP（D0–D5 + D7–D8）
> 后续承接：中心投研可视化平台的业务定位、信息架构与新增实施任务，以 `docs/plan/invest-infra-central-research-visualization-mvp-plan-v1.0.md` 为准；本计划已完成的只读工作台事实继续有效，不再扩展为回测、自动交易或通用流程平台。

## 0.1 当前执行修正（2026-08-23）

本计划继续有效，但当前执行从“继续增加可靠性功能”切换为“Gate 1
真实链路验收”。已完成的共享目录代码能力包括：候选导入诊断、标的解析、
`processing/` 残留恢复、`.tmp` 防护和生命周期事件；这些提交不等同于 Gate 1
通过。

当前只推进以下事项：

1. 使用真实 WorkBuddy 2.0.0 Candidate JSON 完成可复现导入演示；
2. 核对共享目录路径、权限、原子 rename、失败包和凭据脱敏；
3. 核对本地分支与远端 `origin/main`，补齐验收证据；
4. Gate 1 通过前不启动 Inbox API、不引入日志平台、不新增消息队列或持久化状态表。

若真实样本尚不可用，只记录为 Gate 1 阻塞项，不用模拟样本替代真实验收。

## 0.2 Gate 3 数据执行边界修正（2026-09-03）

Gate 1/2 和已完成的策略治理事实继续有效。Gate 3 不再要求 MiniMax-M3 通过长 Prompt 解释正式策略并自行生成 StageResult/Candidate，改为：

```text
invest-infra 生成 DataRequest
→ WorkBuddy 调用获准金融 MCP 并交付 DataBundle
→ invest-infra 校验并由板块/个股两个专用 evaluator 确定性计算
→ StageResult + Candidate 2.0.0
→ 内部可信接缝创建待准入 Observation
→ 既有 Admission / Evidence / Research
```

首版不建设通用策略语言、通用 DAG、完整自动化平台或周期调度。WorkBuddy Automation 只允许固定短启动 Prompt；任何创建、修改、启停或调度仍须用户单独显性授权。

既有 WorkBuddy Candidate 2.0.0 Shared Directory Intake 继续作为外部候选兼容路径，不删除、不改写历史事实。新路径从 WorkBuddy DataBundle 入站，系统生成的 Candidate 不得回绕该 Bridge 或伪装成 `producer=workbuddy`；DataBundle 与 Candidate 的生产者身份和 provenance 分开保存。

## 1. 目标

将 Stage 4D 从横跨合同、存储、Pipeline、API、Web 和 Research 的大任务，拆成四个可独立验收、逐阶段放行的纵向阶段：

```text
阶段 0：合同与现场前置验证
  ↓ Gate 0
阶段 1：外部候选准入闭环
  ↓ Gate 1
阶段 2：只读工作台 MVP
  ↓ Gate 2
阶段 3：正式验证与研究闭环
  ↓ Gate 3 / Stage 4D MVP 完成

独立阶段 4：受控任务发起（D6，不阻塞 MVP）
```

## 2. 范围边界

### 2.1 MVP 包含

```text
WorkBuddy DataBundle
→ invest-infra 专用 evaluator
→ Candidate 2.0.0 candidates JSON
→ 内部可信 Candidate handoff
→ ExternalObservation
→ Opportunity Radar / Automation Center
→ Observation Admission
→ Research Case / Evidence
→ Research Run / Result
→ Research Case 统一时间线
```

### 2.2 MVP 不包含

- 从投研系统直接创建或取消 WorkBuddy 任务；
- Investment Case、Proposal、Risk Check 和 Approval；
- Portfolio、Order、Fill、Position 和实盘；
- T+5/T+20 与完整 Review；
- 新消息队列、新微服务或共享目录之外的额外基础设施。

### 2.3 执行规则

- 只有当前阶段 Gate 通过，下一阶段才可开始；
- 每个实现任务必须有 focused tests，并保持现有测试无回归；
- 生产者状态、Candidate Intake 状态和正式验证状态必须分离；
- 外部观察不得直接成为 Evidence；
- 原始归档是生产输入权威源，PostgreSQL 是标准化业务状态和查询权威源；
- D6 单独评审、单独授权、单独验收。

## 3. 依赖图

```text
已完成兼容路径：WorkBuddy Candidate → SharedDirectory Adapter → ExternalObservation

当前 Gate 3 路径：DataRequest → WorkBuddy DataBundle → 专用 evaluator
  └─ StageResult / CandidateProposal → 内部可信 handoff → ExternalObservation
       └─ Observation Admission
            └─ Research Case + Evidence + Research Run / Result
                 └─ Research Workspace 统一时间线
```

## 4. 阶段 0：合同与现场前置验证

对应原蓝图：D0，以及 D3/D6 所需的 WorkBuddy 现场确认项。

### 4.1 交付任务

#### 任务 0.1：冻结治理边界和 ADR

交付 ExternalWorkflow、ExternalObservation Admission、读 MCP/写 Command API、共享目录所有权边界。

验收标准：

- WorkBuddy 与 invest-infra 的数据所有权无冲突；
- ExternalObservation 与 Evidence 生命周期明确分离；
- 共享目录不可变、逻辑 URI、hash 和审计规则明确；
- D6 被标记为独立可选阶段。

验证：文档链接、ADR 状态和架构治理检查全部通过。

#### 任务 0.2：冻结 Candidate Intake 交接合同

冻结 Candidate Schema 2.0.0、Intake Manifest、run-level/item-level 准入矩阵及 Stage 4D 数据库投影输入。legacy 1.1.x 三件套不再属于当前入口。

验收标准：

- 合法候选、坏项、坏批次、无法映射 symbol 的处理结果唯一且可测试；
- producer/intake/admission 三类状态不混用；
- 重复输入的幂等键和版本字段明确。

验证：Schema fixtures 与 contract tests 通过。

#### 任务 0.3：完成真实样本和共享目录验证

使用真实 WorkBuddy 2.0.0 Candidate JSON 验证字段、编码、路径和原子写入能力。

验收标准：

- 真实 2.0.0 样本有可复现验收记录；
- Windows 容器与 Linux 宿主路径映射明确；
- 写权限、最大文件、原子 rename、失败结果结构和凭据脱敏已确认。

验证：手工验收记录包含输入 hash、执行命令、结果和问题清单。

### Gate 0：允许开发存储与导入链路

- [ ] 合同和 ADR 已冻结；
- [ ] 真实样本验收通过，或未通过项已明确为阻塞；
- [ ] 路径、权限和原子写入策略已确认；
- [ ] 阶段 1 的输入/输出合同无开放歧义。

### 4.2 P0 增量：Candidate 2.0.0 两阶段 lineage 合同

> 状态：兼容路径代码已实现（2026-08-31）；原定由 WorkBuddy 生成正式 Candidate 的真实验收已被 2026-09-03 DataBundle 路径取代

中心投研可视化 3C-L0 真实字段盘点确认：现有 `ExternalWorkflowRun`、
`ExternalArtifact`、`ExternalObservation`、Admission 和 Research Workspace 已能表达
交付、归档、摄取、准入与研究生命周期。当前唯一阻塞是 Candidate 2.0.0 没有保存
两阶段策略和 `StageResult` 身份/hash。可视化层不得从文件名、Markdown 或前端常量
补关系，因此先在 Stage 4D P0 增量补齐这条证据链。

#### 4.2.1 架构决定

1. **保持现有两文件 archive。** `.ready` 包继续只要求 `candidates.json` 和
   `manifest.json`；`manifest.json` 继续校验 `candidates.json` 的 SHA-256 与字节数，
   不新增 `lineage.json` 或第二套 artifact 合同。
2. **lineage 放入现有 Candidate payload。** `candidates.json` 顶层增加 `lineage`，
   保存两个有序 stage：`sector_selection → stock_screening`。每个 stage 包含 `stage_key`、
   `stage_result_id`、`stage_result_sha256`、`strategy_key`、`strategy_version`、
   `strategy_artifact_hash` 和 `as_of`；板块阶段还包含
   `constituent_snapshot_sha256`，终端阶段必须显式绑定上游 stage ID/hash。
3. **候选只引用终端 stage。** 每个 Candidate 继续要求非空 `symbol/reason`，并增加
   `terminal_stage_result_id` 与 `terminal_stage_result_sha256`。二者必须与
   顶层终端 stage 完全一致，不复制整条 lineage。
4. **深化现有 parser seam。** 直接扩展 `parse_candidates_payload()`，集中验证 hash
   格式、阶段顺序、上下游绑定、策略身份、as-of 一致性和候选 terminal 引用；
   Bridge、API 与 Web 不重复实现这些规则，也不新建平行 Module。
5. **复用现有持久化 seam。** 完整 `candidates.json` 继续由 `ExternalArtifact` 的
   manifest/hash 证明；规范化 lineage 写入 `ExternalWorkflowRun.metadata`，候选对应的
   terminal/upstream 引用写入 `ExternalObservation.metadata`。原始 Candidate payload
   仍保存在 `ExternalObservation.payload`，但新的只读 projection 不直接暴露 raw payload。
   本增量不新增表、不新增 FK、不改变 Observation→ResearchExternalEvidence→ResearchCase
   的既有绑定路径。
6. **Admission 时间不纳入本增量。** 现有记录没有权威决定时间时，只读 projection
   返回 `unavailable`；不得用 `observed_at` 或数据库时间代替。Admission 时间如需补齐，
   作为独立任务单独评估，不阻塞 Candidate lineage。
7. **兼容入口只作内部一致性校验。** 现有 WorkBuddy Candidate archive 摄取只验证
   payload/manifest 内部一致性与合同，不静默调用网络，也不从文件名或 Markdown 补身份。
8. **新旧入口分离。** 已完成的 `parse_candidates_payload()` 与
   `import_archived_candidate_run()` 保持 WorkBuddy 外部候选兼容语义；新 evaluator 生成的
   CandidateProposal 通过内部 Application 接缝创建 Observation，不写回共享目录，也不标记为
   WorkBuddy 产物。两条路径最终复用同一 Admission 服务，不复用错误的生产者身份。

#### 4.2.2 现有 parser Interface

保留现有单一入口，不增加新的公开 Interface：

```text
parse_candidates_payload(payload)
  → CandidateIntakeResult（增加规范化 lineage）
  → ValueError（稳定、脱敏的原因）
```

解析结果只增加：

- 两个经过验证且严格有序的 stage identities/hashes；
- 每个 Candidate 经过验证的 terminal stage reference；
- Bridge 写入 JSONB 所需的规范化安全 projection。

错误保持稳定原因，例如 `invalid_stage_order`、
`upstream_binding_mismatch`、`strategy_identity_mismatch`、`as_of_mismatch`、
`candidate_terminal_mismatch`；不得包含宿主机路径、raw exception、凭据或原始正文。

#### 4.2.3 实施切片

##### P0-A：合同、parser 与 Bridge

- 更新 Candidate Intake M0 合同和 schema fixtures；
- 扩展现有 parser，验证两阶段 lineage 和 Candidate terminal 引用；
- Bridge 在 manifest 校验后使用同一 parser，并将规范化 lineage 写入现有 JSONB；
- 复用现有 JSONB 保存规范化 lineage，不新增 migration；
- 旧 Candidate 2.0.0 记录保持可读，但 lineage 明确为 `unavailable`，不做推断。

验收：合法、缺字段、阶段倒序、上游错绑、策略身份错、as-of 错位、候选 terminal
错绑、重复导入、同 run 不同内容冲突、旧记录读回和 PostgreSQL round-trip 通过。

##### P0-B：只读投影与真实验收

- 在现有 External Workflow/Research Workspace Reader 后增加一个有界只读 projection；
- Archive、Intake、Admission、Research 状态分别返回；
- 只投影 stage/strategy ID、version、hash 和 as-of，不返回 artifact URI、raw payload、
  内部 metadata 或异常；
- 兼容入口的 lineage 只读投影继续保留；
- 原定“WorkBuddy 直接生成正式 Candidate ready archive”的真实验收取消，不再作为 Gate 3 输入方案；
- 新 DataBundle → evaluator → 内部 Candidate handoff 验收以候选策略 MVP 计划的 Slice 1B/2 为唯一依据；
- 不启动周期自动摄取，不修改历史 Observation/Candidate/Research 数据。

验收：现有 Application/API success、unavailable、partial、conflict、404 和脱敏测试继续通过；
新路径最终需使两条策略、DataBundle、StageResult、成分快照、Candidate 与 Research Timeline
可逐项追溯，fixture 不替代真实证据。完成 Gate 3 后再独立决定是否恢复中心可视化 3C-L1。

#### 4.2.4 固定实施顺序与停止条件

```text
已完成：P0-A 合同、parser、Bridge → P0-B 只读 projection
当前：候选策略 Slice 1B/2 → Gate 3 真实验收
后续：中心可视化 3C-L1～L3（独立授权）
```

以下任一情况立即停止并重新评审，不顺带扩展：

- 需要新增业务表、外键或改变 Research/Admission 状态机；
- 需要浏览器、API Reader 或 Bridge 跨目录解析 Markdown/猜测关系；
- 两个专用 evaluator 无法在现有 Candidate payload 中生成可验证 lineage；
- 新路径必须复用外部 Candidate Bridge 或伪造 `producer=workbuddy` 才能进入 Admission；
- 需要在摄取事务中调用 WorkBuddy、active Strategy API 或其他网络来源；
- 需要回填/重写历史 Observation、Candidate、Admission 或 Research 数据；
- 需要启动 Dagster、周期自动摄取、部署或业务数据写入才能完成代码级验收。

## 5. 阶段 1：外部候选准入闭环

对应原蓝图：D1–D3。目标是交付可重复、可诊断、可恢复的
`共享目录 → ExternalObservation → 准入状态` 纵向闭环，不包含 Web，
也不把 WorkBuddy 结果接入投研系统内部 CandidatePool 计算。

### 5.1 交付任务

#### 任务 1.1：建立 Integration Domain 与持久化

实现 ExternalWorkflowRun/Event/Artifact/Observation/Admission、Repository、UoW 和 Migration。

验收标准：

- 生产者状态、intake 状态、外部准入规则版本及 schema 版本可持久化；
- 唯一键、event sequence、artifact hash 和 Observation 状态转换受约束；
- migration upgrade/downgrade 与事务 rollback 可验证。

验证：domain、storage、migration focused tests 通过。

依赖：任务 0.1、0.2。

#### 任务 1.2：实现 Artifact Bridge 与安全导入

实现逻辑 URI、路径映射、manifest/intake result parser、hash 校验、原子 claim、archive/rejected、CLI 和 health check。

验收标准：

- `.tmp` 不消费，ready package 可导入；
- hash 错误、目录穿越、文件缺失和非法 MIME 被安全拒绝；
- DB 失败后可重试，重复 message 不产生重复业务对象。

验证：Pipeline fixtures 覆盖 Linux/Windows 路径和主要异常矩阵。

依赖：任务 1.1。

#### 任务 1.3：接入 WorkBuddy Shared Directory Adapter

实现 2.0.0 输入适配，并将 Candidate Intake 归档与标准化结果投影为 Stage 4D ExternalWorkflow/Artifact/Observation 对象。

验收标准：

- 合法候选进入 pending_validation；
- 坏项隔离且同批合法项继续；
- 无法映射的 symbol 进入 needs_symbol_resolution；
- legacy 报告审计不属于当前候选入口范围。

验证：fake WorkBuddy E2E 与一次真实 WorkBuddy 导入演示通过。

依赖：任务 1.2。

### Gate 1：外部候选准入闭环

- [x] 正常、partial、failed、坏批次和坏项均可诊断；
- [x] 重复导入幂等；
- [x] 原始文件、Artifact 和数据库对象可用 run ID/hash 串联；
- [x] 共享目录短暂不可用后可恢复；
- [x] 阶段 1 focused tests 和现有相关测试通过。

2026-08-24 技术验收结果：

1. 真实共享目录已完成坏批次、坏条目、待解析标的、重复导入、冲突包和 processing 恢复演练；
2. 自动化矩阵 `31 passed`，Pipeline 全量 `2426 passed, 1 skipped`，Ruff 通过；
3. 证据记录见 `docs/validation/stage4d-gate1-20260824.md`，Gate 1 技术条件通过，可进入阶段 2 的只读 API/Web 工作台。

legacy 1.1.x 不在当前入口、测试队列或后续 Web 工作台范围内。

## 6. 阶段 2：只读工作台 MVP

对应原蓝图：D4–D5。目标是让用户只读查看外部运行、候选、来源、状态、产物和集成健康度。

### 6.1 交付任务

#### 任务 2.1：交付 External Workflow 与 Opportunity Query API

实现 run list/detail/events/artifacts、observations、opportunity 聚合、integration health 和 artifact preview。

验收标准：

- pagination/filter、404、invalid UUID、partial/failed 行为稳定；
- producer/intake/admission 状态分别返回；
- API 返回完整 source、as_of、hash 和 provenance；
- artifact 不可用时返回安全错误，不泄露宿主机路径。

验证：API tests 与 OpenAPI client drift check 通过。

依赖：Gate 1。

#### 任务 2.2：交付 Dashboard、Opportunity Radar 与 Automation Center

以只读方式展示运行、候选、来源、冲突、产物和健康状态。

验收标准：

- loading/empty/success/partial/failed/stale/conflict 状态齐全；
- pending_validation、needs_symbol_resolution、item_rejected、batch_failed 分区展示；
- 外部评分与正式候选排名视觉分层；
- 页面刷新后可从服务端恢复状态。

验证：Web component/integration tests 与人工导航演示通过。

依赖：任务 2.1。

### Gate 2：只读工作台可用

- [ ] 用户可从 run 定位候选、来源、artifact 和诊断信息；
- [ ] 浏览器不直接访问共享目录或宿主机绝对路径；
- [ ] UI 无写操作；
- [ ] Fake WorkBuddy 导入后可在页面完整查看；
- [ ] API/Web focused tests 和构建通过。

## 7. 阶段 3：正式验证与研究闭环

对应原蓝图：D7–D8。目标是完成 `Observation → Admission → Evidence → Research Case → Research Run/Result → 统一时间线`。JiuwenSwarm 已停止采用，不再作为本阶段依赖或验收对象。

真实 WorkBuddy 验收前置依赖：先完成 `invest-infra-candidate-strategies-mvp-plan-v1.0.md`。既有 Draft → RAA 审计 → CIA 批准 → StrategyVersion 发布激活已经完成；当前只推进 DataRequest/DataBundle、两个专用 evaluator 和固定两阶段候选发现。该切片属于 Stage 4D P0，不新增并行主线。

### 7.1 交付任务

#### 任务 3.1：实现 Observation Admission

实现 identity、date/freshness、unit/definition、internal cross-check、conflict detection 和 admission decision。

设计依据：`docs/adr/0015-external-observation-admission.md`。

Gate 3 准入契约冻结如下：

- 客户端/WorkBuddy 只提交 `observation_id`、`Idempotency-Key` 和必要的操作上下文，不提交 `identity_ok`、`freshness_ok`、`unit_ok` 或 `conflict_detected` 等验证结论；
- 服务端从 `ExternalObservation`、关联 `ExternalArtifact`、标的主数据及同源/内部历史 Observation 读取判定输入，由版本化规则计算验证事实和最终 `AdmissionDecision`；
- `identity`、`freshness`、`unit/definition` 属于确定性检查；缺少必要数据时不得默认为通过；
- `internal cross-check` 和 `conflict detection` 必须基于服务端可查询的既有事实，无法自动消解时进入 `corroborated` 或 `conflict`，不得由客户端强行标记 `admitted`；
- `rules_version`、决定主体、原因、检查明细、来源 Observation/run 和决定时间写入不可变审计元数据；
- 当前已存在的布尔验证字段仅视为过渡实现，Slice B 必须移除其对公开 Command API 的依赖；生产写入 feature flag 在 Slice B、契约测试和迁移验证完成前保持关闭。

验收标准：

- 浏览器只提交命令，不计算验证结果；
- 公共 Command API 不接受客户端验证布尔值，OpenAPI 与生成客户端同步反映该约束；
- corroborated、admitted、rejected 和 conflict 的转换受领域规则约束；
- 只有 admitted Observation 可生成新的 Evidence Item；
- 所有决定保留规则版本、主体、原因和来源。

验证：domain/API tests 覆盖过期、口径不符、冲突和重复操作。

依赖：Gate 2。

#### 任务 3.2：连接 Research Case、Evidence 与 Research Run

从已准入 Observation 创建/关联 Research Case，构建有效 Evidence，并复用现有 ResearchRunner 领域端口和 Research Run/Result 生命周期；不依赖 JiuwenSwarm。

验收标准：

- 无效或未准入 Evidence 引用被拒绝；
- Research Run 成功/失败均可追溯到 Research Case 和源 run；
- WorkBuddy 内容只作为受治理的 Evidence/Context 输入，不修改正式事实。

验证：Fake ResearchRunner E2E 与现有 Research focused tests 通过。

依赖：任务 3.1。

#### 任务 3.3：交付 Research Workspace 统一时间线

扩展 Research Case 页面，展示 External Discovery、Admission、Artifact、Evidence、Research Result 和 provenance 跳转。

验收标准：

- 一页可追溯发现、验证、Evidence 和深研全过程；
- WorkBuddy 观察、正式事实和研究解释有明确视觉标签；
- artifact unavailable、Research Run failed 和无效引用有可理解错误态。

验证：Web tests 与完整验收演示通过。

依赖：任务 3.2。

### Gate 3：Stage 4D MVP 完成

- [ ] 正常主链路端到端通过；
- [ ] 蓝图第 25.10 节异常场景全部有测试或手工验收证据；
- [ ] Fake WorkBuddy、Fake ResearchRunner E2E 通过；
- [ ] 真实 WorkBuddy 两次 MCP DataBundle 手工验收通过；
- [ ] 两个专用 evaluator 对相同版本和输入产生可重复的 StageResult/Candidate；
- [ ] WorkBuddy 不解释策略、不生成正式 hash/lineage、不决定 CandidateAdmission；
- [ ] 现有全量测试无回归；
- [ ] 运行手册、架构文档和 OpenAPI client 已同步。

## 8. 独立阶段 4：受控任务发起

对应原蓝图：D6。此阶段不属于 Stage 4D MVP 必经链路。

### 8.1 启动条件

- WorkBuddy 已确认稳定的创建、查询、取消或共享目录任务监听能力；
- 本地操作身份、feature flag、Idempotency-Key、CSRF/会话策略已冻结；
- 用户单独批准写命令入口范围。

### 8.2 交付和验收

实现任务创建/取消 Command API、参数预览、状态追踪和深链接。

验收标准：

- feature flag 默认关闭；
- 重复提交幂等；
- 未授权、过期、取消失败和外部不可用均可安全恢复；
- 外部内容不能触发 Command API；
- 不提供任意 SQL、任意文件写入或交易能力。

## 9. 阶段级风险与控制

| 风险 | 暴露阶段 | 控制 |
|---|---|---|
| 真实 WorkBuddy 输出不稳定 | 阶段 0 | 真实样本先验收，Schema/Adapter 隔离差异 |
| WorkBuddy 长 Prompt 超出 MiniMax-M3 稳定执行边界 | 阶段 0/3 | 固定短 Prompt + 结构化 DataRequest；策略计算、hash 和 lineage 下沉到专用 evaluator |
| 状态语义混用 | 阶段 1 | producer/intake/admission 分字段和领域约束 |
| 重复或损坏消息 | 阶段 1 | hash、幂等键、原子 claim、archive/rejected |
| UI 先于闭环膨胀 | 阶段 2 | 只做只读三页面，Gate 1 后启动 |
| 外部观察污染正式 Evidence | 阶段 3 | Admission 后生成新 Evidence，不原地转换 |
| D6 扩大写入面 | 独立阶段 4 | 单独授权、默认关闭、审计和幂等 |

## 10. 交付物索引

| 文档 | 职责 |
|---|---|
| `docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md` | Stage 4D–4G 总蓝图、领域和架构设计基线 |
| `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` | Stage 4D 当前阶段、依赖、Gate 和验收权威 |
| `docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md` | Candidate Intake 已冻结合同 |

## 11. 开始实施前检查

- 用户授权、代码实现、自动验证和真实验收分别记录，不通过独立任务清单维护；
- 每个实现切片必须关联本计划的阶段和 Gate；
- 未经单独批准不启动 D6、4E、4F 或 4G。
