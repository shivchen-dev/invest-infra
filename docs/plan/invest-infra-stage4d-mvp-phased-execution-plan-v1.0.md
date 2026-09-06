# Stage 4D MVP 分阶段执行计划

> 文档版本：v1.0
> 文档状态：BLOCKED（等待 v2.1.0 策略治理及 Gate B2A）
> 计划治理：`docs/plan/README.md`
> 制定日期：2026-08-14
> 上位蓝图：`docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md`
> 当前范围：Stage 4D MVP（D0–D5 + D7–D8）
> 后续参考：中心投研可视化平台的业务定位与信息架构保留在 `docs/plan/archive/deferred/invest-infra-central-research-visualization-mvp-plan-v1.0.md`；恢复实施前必须重新授权。本计划已完成的只读工作台事实继续有效，不再扩展为回测、自动交易或通用流程平台。

> 2026-09-06 修订：当前唯一活动前置主线为 `invest-infra-target-dataset-source-admission-plan-v1.0.md`。本计划已完成事实继续有效；目标 Dataset 已冻结 WorkBuddy 固定多源配方，可实施 DS-C0/DS-1 和双次 shadow。Gate 3 正式执行仍须等待 Gate B2A 与 v2.1.0 策略治理通过。

## 0. 当前执行边界

Gate 1/2 和已完成的策略治理事实继续有效。Gate 3 不再要求 MiniMax-M3 通过长 Prompt 解释正式策略并自行生成 StageResult/Candidate，改为：

```text
目标 Dataset Gate 冻结 WorkBuddy Dataset 固定多源配方
→ WorkBuddy DataRequest/DataBundle 1.0 执行冻结的多 Connector 配方
→ invest-infra 通过 evaluator 私有板块输入不变量校验并组装 Industry/Concept
→ 板块/个股两个专用 evaluator 只消费已验证的单值输入；旁证按需记录
→ StageResult + Candidate 2.0.0
→ 内部可信接缝创建待准入 Observation
→ 既有 Admission / Evidence / Research
```

首版不建设双路径并行接入、跨 Provider fallback、公开通用组装接口、通用策略语言、通用 DAG、完整自动化平台或周期调度。WorkBuddy Automation 只允许固定短启动 Prompt；任何创建、修改、启停或调度仍须用户单独显性授权。

既有 WorkBuddy Candidate 2.0.0 Shared Directory Intake 继续作为外部候选兼容路径，不删除、不改写历史事实。新路径从 Gate 入选的 DataBundle 或 ProviderBatch 入站，系统生成的 Candidate 不得回绕该 Bridge 或伪装上游生产者；上游输入与 Candidate 的生产者身份和 provenance 分开保存。

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
Gate 入选的 DataBundle 1.0 或 ProviderBatch
→ evaluator 私有板块输入不变量
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

当前 Gate 3 路径：Gate 入选的单一采集路径 → evaluator 私有板块输入不变量 → 专用 evaluator
  └─ StageResult / CandidateProposal → 内部可信 handoff → ExternalObservation
       └─ Observation Admission
            └─ Research Case + Evidence + Research Run / Result
                 └─ Research Workspace 统一时间线
```

## 4. 已完成基线：阶段 0–2

阶段 0–2 已退出当前派工面，其详细实现过程不再保留在活动计划中：

| 阶段 | 结论 | 权威证据 |
|---|---|---|
| 阶段 0：合同与现场前置 | 完成；ExternalObservation、Evidence、共享目录与权限边界已冻结 | [Candidate Intake 合同](../implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md)、[协作职责 ADR](../adr/0014-investment-collaboration-responsibility-boundaries.md) |
| 阶段 1：外部候选准入 | Gate 1 通过；真实共享目录异常矩阵、幂等、恢复和 lineage 已验收 | [Gate 1 验收](../validation/stage4d-gate1-20260824.md) |
| 阶段 2：只读工作台 | Gate 2 通过；Fake WorkBuddy → PostgreSQL → API → Web 已形成端到端证据 | [Gate 2 验收](../validation/stage4d-gate2-20260825.md) |

已完成的 WorkBuddy Candidate 2.0.0 Shared Directory Intake 保留为外部候选兼容入口，不删除、不改写历史事实。Gate 3 新路径必须遵守以下边界：

- Gate 入选的 DataBundle 由投研系统专用 evaluator 生成 StageResult 和 Candidate；
- 系统生成的 Candidate 通过内部可信接缝进入 Admission，不回绕外部 Candidate Bridge，不伪装上游生产者；
- 上游输入、StageResult、Candidate 和 Research 对象分别保存 producer、version、hash 与 lineage；
- 摄取事务不调用 WorkBuddy、active Strategy API 或其他网络来源；
- 不回填或重写历史 Observation、Candidate、Admission 或 Research 数据；
- 新增业务表、改变 Research/Admission 状态机或启动周期调度时立即停止并重新评审。

## 5. 当前阶段：正式验证与研究闭环

对应原蓝图：D7–D8。目标是完成 `Observation → Admission → Evidence → Research Case → Research Run/Result → 统一时间线`。JiuwenSwarm 已停止采用，不再作为本阶段依赖或验收对象。

真实数据验收前置依赖：先完成 `invest-infra-candidate-strategies-mvp-plan-v1.0.md`。既有 Draft → RAA 审计 → CIA 批准 → StrategyVersion 发布激活已经完成；当前须按目标 Dataset 计划已冻结的 WorkBuddy 固定配方完成必要的 evaluator 私有收敛、Dataset 绑定和双次 shadow，再执行两个专用 evaluator 的固定两阶段候选发现。WorkBuddy 路径复用 DataRequest/DataBundle 1.0；仅在证据证明无法表达时另行评审 2.0。该切片属于 Stage 4D P0，不新增并行主线。

### 5.1 已完成代码基线

Gate 3 的自动化能力已经落地：服务端 Admission 计算验证事实，Research Case/Evidence/Research Run 生命周期和 Research Workspace 时间线均有聚焦测试。权威证据见 [Gate 3 进度记录](../validation/stage4d-gate3-progress-20260826.md)。

### 5.2 剩余交付

1. 完成目标 Dataset 计划的 DS-C0、DS-1、双次 shadow 与 Gate B2A；
2. 完成并激活获批的 v2.1.0 策略与匹配的 WorkBuddy Definition；
3. 使用新生成的 Candidate 完成 `Admission → Evidence → Research Case → Research Run/Result → Timeline` 真实手工联调；
4. 执行 Gate 3 全量回归、构建、异常矩阵和最终演示。

既有 rejected Observation 不回写、不重置；历史 WorkBuddy 报告不作为当前 Gate 3 输入。

### Gate 3：Stage 4D MVP 完成

- [ ] 正常主链路端到端通过；
- [ ] 蓝图第 25.10 节异常场景全部有测试或手工验收证据；
- [ ] Fake WorkBuddy、Fake ResearchRunner E2E 通过；
- [ ] 两个阶段的真实多源输入手工验收通过，各 Dataset 的 Connector、真实上游、来源和 hash 可追溯；内部 Provider 只有在另行批准接入后才纳入验收；
- [ ] 两个专用 evaluator 对相同版本和输入产生可重复的 StageResult/Candidate；
- [ ] WorkBuddy 不解释策略、不生成正式 hash/lineage、不决定 CandidateAdmission；
- [ ] 现有全量测试无回归；
- [ ] 运行手册、架构文档和 OpenAPI client 已同步。

## 6. 独立阶段：受控任务发起

对应原蓝图：D6。此阶段不属于 Stage 4D MVP 必经链路。

### 6.1 启动条件

- WorkBuddy 已确认稳定的创建、查询、取消或共享目录任务监听能力；
- 本地操作身份、feature flag、Idempotency-Key、CSRF/会话策略已冻结；
- 用户单独批准写命令入口范围。

### 6.2 交付和验收

实现任务创建/取消 Command API、参数预览、状态追踪和深链接。

验收标准：

- feature flag 默认关闭；
- 重复提交幂等；
- 未授权、过期、取消失败和外部不可用均可安全恢复；
- 外部内容不能触发 Command API；
- 不提供任意 SQL、任意文件写入或交易能力。

## 7. 阶段级风险与控制

| 风险 | 暴露阶段 | 控制 |
|---|---|---|
| WorkBuddy 输入不稳定或长 Prompt 越权解释策略 | Gate 3 | 固定短 Prompt + 结构化 DataRequest；策略计算、hash 和 lineage 由专用 evaluator 完成 |
| 外部观察污染正式 Evidence | Gate 3 | Admission 后生成新 Evidence，不原地转换 |
| D6 扩大写入面 | 独立阶段 | 单独授权、默认关闭、审计和幂等 |

## 8. 交付物索引

| 文档 | 职责 |
|---|---|
| `docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md` | Stage 4D–4G 总蓝图、领域和架构设计基线 |
| `docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md` | Stage 4D 当前阶段、依赖、Gate 和验收权威 |
| `docs/implementation/WORKBUDDY-CANDIDATE-INTAKE-M0-CONTRACT.md` | Candidate Intake 已冻结合同 |

## 9. 恢复实施前检查

- 用户授权、代码实现、自动验证和真实验收分别记录，不通过独立任务清单维护；
- 每个实现切片必须关联本计划的阶段和 Gate；
- 未经单独批准不启动 D6、4E、4F 或 4G。
