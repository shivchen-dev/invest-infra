# Stage 4D MVP 分阶段执行计划

> 文档版本：v1.0
> 文档状态：ACTIVE（当前范围为 Stage 4D 收口）
> 计划治理：`docs/plan/README.md`
> 制定日期：2026-08-14
> 上位蓝图：`docs/plan/archive/reference-blueprints/invest-infra-stage4d-unified-investment-workbench-integration-plan-v1.0.md`
> 当前范围：Stage 4D MVP（D0–D5 + D7–D8）
> 后续承接：中心投研可视化平台的业务定位、信息架构与新增实施任务，以 `docs/plan/invest-infra-central-research-visualization-mvp-plan-v1.0.md` 为准；本计划已完成的只读工作台事实继续有效，不再扩展为回测、自动交易或通用流程平台。

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
WorkBuddy candidates JSON / legacy 三件套
→ Candidate Intake
→ 不可变归档
→ ExternalWorkflowRun / Artifact / Observation
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
合同 / ADR / 真实样本 / 路径权限
  └─ Candidate Intake → ExternalObservation 准入合同
       └─ Domain + Migration + Repository
            └─ Artifact Bridge + Ingestor + SharedDirectory Adapter
                 └─ Query API + Artifact Preview + Integration Health
                      └─ Dashboard + Opportunity Radar + Automation Center
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

冻结 Candidate Schema 2.0.0、legacy 1.1.x 适配、Intake Manifest、run-level/item-level 准入矩阵及 Stage 4D 数据库投影输入。

验收标准：

- 合法候选、坏项、坏批次、无法映射 symbol 的处理结果唯一且可测试；
- producer/intake/admission 三类状态不混用；
- 重复输入的幂等键和版本字段明确。

验证：Schema fixtures 与 contract tests 通过。

#### 任务 0.3：完成真实样本和共享目录验证

使用真实 WorkBuddy 2.0.0 样本和至少一份 legacy 1.1.x 三件套验证字段、编码、路径和原子写入能力。

验收标准：

- 真实 2.0.0 与 legacy 样本均有可复现验收记录；
- Windows 容器与 Linux 宿主路径映射明确；
- 写权限、最大文件、原子 rename、失败结果结构和凭据脱敏已确认。

验证：手工验收记录包含输入 hash、执行命令、结果和问题清单。

### Gate 0：允许开发存储与导入链路

- [ ] 合同和 ADR 已冻结；
- [ ] 真实样本验收通过，或未通过项已明确为阻塞；
- [ ] 路径、权限和原子写入策略已确认；
- [ ] 阶段 1 的输入/输出合同无开放歧义。

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

实现 2.0.0/legacy 输入适配，并将 Candidate Intake 归档与标准化结果投影为 Stage 4D ExternalWorkflow/Artifact/Observation 对象。

验收标准：

- 合法候选进入 pending_validation；
- 坏项隔离且同批合法项继续；
- 无法映射的 symbol 进入 needs_symbol_resolution；
- legacy 报告审计失败不阻断已提取合法候选。

验证：fake WorkBuddy E2E 与一次真实 WorkBuddy 导入演示通过。

依赖：任务 1.2。

### Gate 1：外部候选准入闭环

- [ ] 正常、partial、failed、坏批次和坏项均可诊断；
- [ ] 重复导入幂等；
- [ ] 原始文件、Artifact 和数据库对象可用 run ID/hash 串联；
- [ ] 共享目录短暂不可用后可恢复；
- [ ] 阶段 1 focused tests 和现有相关测试通过。

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

### 7.1 交付任务

#### 任务 3.1：实现 Observation Admission

实现 identity、date/freshness、unit/definition、internal cross-check、conflict detection 和 admission decision。

验收标准：

- 浏览器只提交命令，不计算验证结果；
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
- [ ] 真实 WorkBuddy 手工验收通过；
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
