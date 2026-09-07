# 投研系统首批两条候选策略最小审核、登记与执行计划 v1.0

> 治理状态：`BLOCKED`
> 制定日期：2026-08-26
> 当前执行修订：2026-09-07 跨计划校准（共同基线 `8610418`）；历史 v2.0.0 Gate A/B 保留，目标 v2.1.0 与 Gate B2A 仍待验收
> 计划定位：Stage 4D Gate 3 的前置垂直切片；用户已于 2026-08-26 明确授权实施
> 合同依据：`../governance/invest-infra-strategy-source-to-automation-workflow.md`
> 数据源前置：`invest-infra-target-dataset-source-admission-plan-v1.0.md`

## 1. 目标

当前 Gate 3 的真实阻塞不是缺少完整策略平台。DataRequest/DataBundle 合同与 evaluator 接缝已经存在或部分实现；生产阻塞是 `sector-ranking` 和 `sector-constituents` 均无生产准入来源，Gate B2A 为 `BLOCKED`，且收窄后的板块策略尚未形成不可变 active 版本。

当前准入事实为：`sector-ranking=research_only`、`sector-constituents=research_only`、预采集未获准，禁止生成正式 Candidate。目标 Dataset 的探针、准入决定和最小运行时守卫只由 `invest-infra-target-dataset-source-admission-plan-v1.0.md` 承担，本计划不再维护第二套来源矩阵或准入流程。v2.1.0 提案及 CIA/RAA 审核可与数据源计划并行；Gate B2A 阻塞期间 v2.1.0 保持 inactive。Slice 1C-A 先向数据主线交付已冻结数据要求及已审核、获准影子的 v2.1.0 artifact/evaluator，保持 inactive；不等 B2A 后才实现影子所需计算。只有策略治理、Gate B2A 与独立发布/激活授权均具备后，才由 Slice 1C-B 发布/启用获批路径并激活匹配策略，再开始 Slice 2 正式执行。

```text
Slice 1C-A：目标数据要求 → CIA/RAA 审核 → 可信 v2.1.0 artifact + matching evaluator
             │ DS-FM/接线前交接要求                 │ DS-2 前交接实现（inactive）
数据主线：DS-0M → DS-FM → 既有 DS-C0 差异验收 → DS-1 → DS-2 → B2A
策略治理获批 + B2A + 独立授权 → Slice 1C-B：发布/启用入选路径并激活策略
→ Slice 2：SectorStageResult → 个股输入核验 → StockStageResult → Candidate 2.0.0
→ 内部可信接缝 → CandidateAdmission → Evidence → ResearchCase/Run/Result → Timeline
```

历史 WorkBuddy 固定组合与 DS-C0 实现保留为复核对象；本计划不自行宣布 DS-FM 已通过或改选 Provider。当前来源适用性、采集到业务 Dataset 的映射及通过范围，只消费 [来源准入计划](invest-infra-target-dataset-source-admission-plan-v1.0.md) 所引用的决定。

## 2. 权威边界

- 投研系统保存待审策略、正式审计记录和正式策略版本，是审核状态、策略身份、版本和当前激活状态的唯一权威源。
- 用户/CIA 决定策略业务语义、适用范围、风险和是否批准；ARC 不代替投研决策。
- CIA 负责策略业务语义和提案；WorkBuddy 只评估数据能力并按 DataRequest 调用获准 MCP，不能解释或改写正式策略、决定正式候选或激活版本。
- ARC 负责 DataRequest/DataBundle 合同和技术验证；投研系统负责确定性 evaluator、StageResult、Candidate、hash 和 lineage。
- 首版由 RAA 审计作为策略发布硬门禁；RAA 只读待审策略，不直接修改策略状态。
- 本 MVP 不建设或依赖回测模块。RAA 只审核规则可执行性、数据口径、无未来数据、可复算性、失败条件和证据边界，不审核或证明策略收益有效性。
- AgentOA 负责审计任务投递和 `audit.json` 回传，不代表审计入库、策略批准或业务摄取完成。
- JSON 是机器权威；Markdown 仅供人工审核。
- 历史 YAML、策略代码、旧任务包和裸 `strategy_id` 不自动升级为正式策略。

## 3. 范围

### 3.1 纳入范围

- 两篇已明确URL和内容hash的头条策略源材料；
- 两套已归档、预检通过且状态为 `needs_review` 的 WorkBuddy 工程化交付；
- 两个保存不可变 `strategy.json`、来源和 validation 的 `StrategyDraft`；
- 两份通过 AgentOA 交付并由投研系统摄取的不可变 `StrategyAudit`；
- 两个最小、不可变、可查询和可激活的 `StrategyVersion`；
- 板块阶段和个股阶段各一次可信数据输入；板块阶段只使用 DS-FM/B2A 决定的单一执行路径及其确定性采集映射；
- 入选来源的可复算 artifact/batch，以及投研系统生成的一份同时追溯两个正式策略版本和上游 StageResult 的 Candidate 2.0.0；
- 两个固定范围的专用 evaluator；仅 WorkBuddy 路径需要相应 active DataAcquisitionDefinition；
- 与现有 Admission、Evidence 和 Research 链路的真实联调；既有 WorkBuddy Candidate Intake 仅保留为外部兼容入口。

### 3.2 明确不做

- 独立 `StrategySourceDocument` 数据库聚合；
- 独立 `StrategyCapabilityAssessment` 数据库聚合；
- `StrategyProposalRevision` 状态机和提案管理平台；
- 通用 `StrategyAutomationDefinition` 状态机、周期调度和自动任务发布；
- RAA 写 API、审批 UI 和通用权限平台；
- 多策略编排、通用 DAG、图形化流程设计器；
- 通用策略表达式语言、规则解释器或模型驱动的正式候选判断；
- 任何回测模块、收益验证、参数寻优或以回测指标作为发布门禁；
- `suspended/retired` 等当前无真实用例的生命周期状态；
- 修改或重置现有两条已 `rejected` Observation；
- 恢复 legacy 1.1.x 三件套或 JiuwenSwarm 路径。

上述能力保留在合同蓝图中，只有出现当前固定两阶段范围之外的新真实用例并获得独立授权后才实施。

首批两条策略按固定业务顺序人工执行，不为这一条固定链路建设 `CandidateSelectionWorkflowVersion` 或通用编排器。

### 3.3 已确认输入（历史登记基线）

| 阶段 | 来源 | Source ID | 既有策略 artifact | 当前状态 |
|---|---|---|---|---|
| 板块强度 | `https://m.toutiao.com/is/fslPVWFTKSY/` | `source-sector-strength-toutiao-20260815` | `strategy-engineering-sector-strength-20260815-0001` | validation passed / needs_review |
| 通达信个股筛选 | `https://m.toutiao.com/is/QwmHBSMbhGQ/` | `source-tdx-native-tools-toutiao-20260815` | `strategy-engineering-tdx-native-tools-20260815-0001` | validation passed / needs_review |

上表及原始正文恢复要求属于 Slice 0 的历史输入记录；其完成事实由第 4 节 Gate A 证据定义，不因本次补丁重复派工。未来确需重新提取原文且与原 hash 不同时，仍须并列保留新旧快照并交 CIA 确认，不把变化后的网页静默解释为原始内容。

## 4. 已完成治理基线

领域对象、角色、状态与交付合同由 [策略源到自动化治理合同](../governance/invest-infra-strategy-source-to-automation-workflow.md) 统一定义，本计划不再复制。

| 基线 | 当前事实 | 证据 |
|---|---|---|
| StrategyDraft / Gate A | 两条源文与不可变 Draft 已登记并验收 | [Slice 0 / Gate A](../validation/candidate-strategies-slice0-gate-a-20260826.md) |
| StrategyAudit / StrategyVersion | 早期审计曾要求修订；后续治理发布、激活与 active 只读接口已进入代码基线 | [早期审计记录](../validation/candidate-strategies-slice1-audit-ingestion-20260826.md)；提交 `25b5e24`、`a934513`、`e603403` |
| 数据获取合同 | DataRequest/DataBundle 1.0、静态 Definition 与只读接口已实现 | 提交 `9035c97`、`a9b288f` |

历史 v2.0.0 的完成事实不自动批准 v2.1.0。收窄策略仍须创建新的不可变版本并完成 CIA/RAA 治理。

## 5. 实施切片

### 已完成切片：Slice 0–1B

| 切片 | 结论 |
|---|---|
| Slice 0 | 两条 StrategyDraft 与 Gate A 已完成 |
| Slice 1 | 历史 v2.0.0 的审计、发布与人工激活能力已形成实现基线 |
| Slice 1A | active StrategyVersion 局域网只读接口已实现 |
| Slice 1B | DataRequest/DataBundle 1.0、两个静态 Definition 和只读接口已实现 |

以上切片不再派工。剩余工作仍限 Slice 1C 和 Slice 2：1C-A 可在既有范围内取得明确授权后并行推进；1C-B 和 Slice 2 仍等待各自 Gate，不因本次补丁获准执行。

### Slice 1C：目标策略影子交接与 Gate B2A 结果消费

**目标：** 明确同一 Slice 的两个交接时点，不新设主线、来源矩阵或审批系统；数据主线仍唯一负责来源核证和准入。

**业务范围：** `sector-strength-ranking` 的 v2.1.0 收窄提案仅保留 `industry`、`concept`，暂停 `area` 和 `zgb/R-A3`；最终以 CIA/RAA 治理后的不可变 artifact 为准。本补丁不确定新公式、权重或审批结果，不原地改写 active v2.0.0。

#### 1C-A：影子前的策略与 evaluator 交接

此部分不依赖 B2A 已通过，否则 DS-2 无法验收目标版本。提案、审核和必要实现各按既有授权/派工流程执行；本补丁仅明确归属，不自动授权业务代码。

| 交付 | 责任 | 最迟时点 |
|---|---|---|
| 带身份/hash 的目标数据要求：范围、字段、单位、时间和停止条件 | CIA 确认语义，ARC 登记技术合同 | DS-FM 判断覆盖及相关接线前；变化后复核受影响来源证据 |
| 已审核且获准用于影子的 v2.1.0 不可变 artifact、审核/决定引用 | CIA/RAA 按既有治理流程，系统保存权威记录 | DS-2 前，保持 inactive；不得用临时 scoped profile 挂旧版本替代 |
| 匹配的专用 evaluator、可信加载接线、实现版本及测试位置 | ARC 经既有 task-routing 派工并独立技术验收 | DS-2 前；复用当前 evaluator，代码按授权任务串行修改 |

**交接验收：**

- [ ] 实际 artifact 内容按既有规则核验 hash，与审核对象和目标规则一致；不能信任自报 hash 或缺省固定值。
- [ ] 目标规则/版本及兼容性由策略任务验证；来源映射、单位和完整度由数据任务验证；同一文件仅一个写入型执行器，复用对应测试证据。
- [ ] 影子入口绑定固定 artifact、evaluator、请求与归档；不得要求先 active，也不得绕过正式入口的 active 检查。
- [ ] 交接未完成则 DS-2 等待，不以旧版输出代替、不提前发布 Definition、不生成正式 Candidate。

#### 1C-B：消费 B2A 与受控发布/激活

**依赖：** 1C-A 交接、目标策略治理获批、来源计划 B2A 通过，以及独立发布/启用和激活授权。

**工作与验收：**

- [ ] 读取唯一的 B2A 决定及验收引用，核对目标策略所需业务输入、采集 Dataset 映射、单位、时间、分类、完整度及停止条件；两个业务输入不要求恰好两个采集 Dataset。
- [ ] 仅在 WorkBuddy 入选时发布与目标策略和获批映射一致的候选 Definition；仅在内部 Provider 入选时启用获批配置。未入选路径不实现，不伪造生产者。
- [ ] 按独立授权激活目标策略；Definition active 与 StrategyVersion active 分别核对，不能互相替代。
- [ ] 缺少策略批准、B2A 或激活/发布授权时，正式执行继续 `BLOCKED`。

**验证与规模：** 1C-A 使用策略 artifact/审核记录、可信加载及 evaluator 聚焦测试；1C-B 使用 B2A 证据和实际发布配置的 identity/version/hash 读回。按真实差异划分 S/M 任务，不重复实现数据源或新增注册表。

### Slice 2：可信数据输入驱动的两阶段真实执行并回接 Stage 4D

**目标：** 用两个正式策略版本和两个阶段的可信数据输入，按固定顺序由投研系统确定性完成候选发现，解除 Gate 3 输入阻塞。

**工作内容：**

- ARC 查询两条策略及 Gate B2A 入选采集路径的当前 active 配置和 artifact；
- 板块阶段仅执行 B2A 批准并显式发布/启用的路径：WorkBuddy 使用 DataRequest/DataBundle 1.0；内部 Provider 仅在其确已入选并验收时使用自身证据链。此条件描述不授权新增 Provider，也不允许运行中改源；
- 投研系统复用现有 evaluator 兼容接口或其私有板块输入核心，校验并组装 Industry/Concept；旁证仅在真实需要时生成诊断；
- 仅在 SectorStageResult 合法时，针对其限定成分股生成第二个 DataRequest；
- 个股阶段继续按该阶段的正式策略与获批 Definition 请求行情、资金、北向、财务等实际必需字段；逐项核对真实供给、时点和使用范围。板块 B2A 不替代个股数据核验，未知项先停止受影响阶段，不由 AI 补数或临时改规则；可选旁证仍非必需。WorkBuddy 不解释策略或决定候选；
- 投研系统个股专用 evaluator 按正式 StrategyVersion 生成 StockStageResult 和 Candidate 2.0.0，并绑定上游 StageResult；
- 投研系统以 `producer=invest-infra` 保存 CandidateProposal，通过内部可信 Application 接缝创建待准入 ExternalObservation 并执行 CandidateAdmission；
- 既有共享目录 `import_archived_candidate_run()` 继续只接收外部 WorkBuddy Candidate 2.0.0，不承接新路径中的系统 Candidate，也不改写其 producer；
- 准入后继续 Evidence → ResearchCase → ResearchRun/Result → Timeline；
- 固化实际 request/bundle 或 Provider request/attempt/batch、策略/配置版本、hash、时间戳、状态和读回证据。

**验收标准：**

- [ ] 实际 Connector 或 Provider、参数、分页、样本量、调用顺序和错误可追溯；
- [ ] 同一策略、映射/evaluator 版本、原请求身份与归档输入重放得到相同结果及 hash；跨请求比较按来源计划第 4.7 节的业务投影，不要求不同 request_id 的完整运行 hash 相同；
- [ ] 跨源差异不平均、不静默覆盖；可选旁证不作为 evaluator 输入或运行必需依赖；
- [ ] 个股 DataRequest 可追溯板块 run id 和 SectorStageResult hash；
- [ ] Candidate 携带末阶段正式策略版本，并能从持久化数据及既有只读入口追溯上游板块策略、StageResult ID/hash、实际输入及 as_of；不以临时 JSON 有字段代替读回验收；
- [ ] 上游 `producer/provider` 与 CandidateProposal 的 `producer=invest-infra` 分开保存并显式关联，外部输入不能冒充系统 evaluator；
- [ ] Candidate 内容满足当前 Admission 合同，或形成可解释的合法空结果；
- [ ] 缺字段、过期数据、未知或未准入的 Connector/Provider、hash 冲突和 evaluator 规则不可执行均 fail closed；
- [ ] 运行、交付、摄取和业务结果状态分别记录；
- [ ] 旧 `rejected` Observation 未修改或重置；
- [ ] Gate 3 正常主链路形成可复验证据。

**验证：** 入选路径 fixtures、两个 evaluator 的规则边界和重复执行测试；archive、数据库、适用的 active API 与 API/Web Timeline 多方读回；Stage 4D focused 和全量回归。

**依赖：** v2.1.0 策略治理和 Gate B2A 均通过；随后显式激活 v2.1.0，并发布/启用与该版本匹配的入选采集路径。此前不得开始本 Slice 的正式执行。

**预计规模：** 拆成板块和个股两个 M 垂直切片，每个先完成入选输入 → evaluator → StageResult，再进入下一阶段；不建设通用规则引擎。

## 6. 当前依赖与验收 Gate

两条主线并行，但有明确交接：Slice 1C-A 在 DS-FM/接线前交付数据要求，在 DS-2 前交付已审核且获准影子的目标 artifact/evaluator；B2A 后由 1C-B 消费验收并按独立授权发布/激活。其后才开始 Slice 2，不把目标 evaluator 延后到 B2A 之后。

### 已完成 Gate：历史 v2.0.0 Gate A/B

- Gate A 的 Draft、来源与 hash 验收见 [Slice 0 / Gate A](../validation/candidate-strategies-slice0-gate-a-20260826.md)。
- [早期审计记录](../validation/candidate-strategies-slice1-audit-ingestion-20260826.md)只描述当时的 `changes_required` 状态；后续 StrategyVersion 发布、激活和只读查询能力已由提交 `25b5e24`、`a934513`、`e603403` 落地。
- 这些历史完成事实不替代 v2.1.0 的新提案、审计和批准。

### Gate B2A：只消费来源主线的决定

本计划不再次定义或批准 B2A。唯一判定范围与验收条件见 [来源准入计划](invest-infra-target-dataset-source-admission-plan-v1.0.md)；1C-B 只核对其与目标策略的匹配。结论缺失、失效或范围不匹配时停止正式执行并交回原责任方，不增设同名 Gate 或第二份来源矩阵。

### Gate C：真实链路通过

- 两个阶段均具备可验证的可信输入；需要 WorkBuddy 补数时，DataBundle 字段、时间、来源和调用证据可验证；
- 内部 Provider 数据仅在该 Dataset、消费者和接入路径明确获批并通过相应验收后使用；保留 provider、request/attempt/batch、hash 和质量证据，不冒充 WorkBuddy，也不将板块准入外推到个股阶段；
- 投研系统两个专用 evaluator 按正式 StrategyVersion 确定性生成 SectorStageResult、StockStageResult 和 Candidate；
- 下游任务显式引用已校验上游StageResult，不依赖文件名或Markdown猜测；
- Candidate 2.0.0可追溯两个策略版本、各阶段实际输入 artifact/batch，以及存在时的 AgentOA 任务和原始 DataBundle；生产者身份不混用；
- Stage 4D Admission 及 Research 链路形成证据，或如实记录符合合同的合法空结果；空结果只证明该分支，不冒充尚未发生的 Research Run/Result 或替代 Stage 4D 的正常主链路验收；
- focused/full tests、迁移检查、OpenAPI drift、Web typecheck/build 和 `git diff --check` 通过。

## 7. 兼容与延期

- 现有 YAML/custom strategy loader、策略 archive 和 validator 保持原用途并优先复用；不自动升级为正式版本。
- 历史 `strategy_id`、旧提案和旧报告继续视为 `legacy_unapproved/test_only/non_authoritative`。
- 既有 WorkBuddy Candidate 2.0.0 Shared Directory Bridge 保持兼容，只用于真正由 WorkBuddy 生产的外部候选；新 DataBundle 路径不得回绕该 Bridge。
- 数据库迁移只新增，不改写历史 Observation、Artifact、Run 或 Candidate。
- 出现第二种非候选业务、第三个 evaluator 或周期调度需求后，再评估：
  - 独立 SourceDocument/CapabilityAssessment/ProposalRevision 聚合；
  - 通用 StrategyAutomationDefinition 和完整生命周期；
  - changes_requested/rejected/suspended/retired 状态机；
  - 审批接口和 UI；
  - 多策略编排与自动调度。

## 8. 风险控制

| 风险 | 控制措施 |
|---|---|
| ARC 或系统编造策略规则 | Slice 0 必须由用户/CIA确认业务内容 |
| 裸 `strategy_id` 再次进入任务 | AgentOA 任务必须携带版本和 artifact hash |
| AgentOA 完成被误认为审计完成 | 只有 StrategyAudit 成功摄取才形成正式审计记录 |
| RAA 审核了过期内容 | audit 必须绑定当前 draft_id 和 artifact_hash |
| 归档成功被误认为正式版本 | 正式执行须审核批准且 active；影子仅按 1C-A 的受控、未激活交接执行，不产生正式候选 |
| MiniMax-M3 被长 Prompt 压垮 | WorkBuddy 只接收短启动 Prompt 和结构化 DataRequest，策略计算下沉到专用 evaluator |
| 两阶段关系固化成脆弱脚本 | 下游 DataRequest 显式引用上游 StageResult 身份和 hash，但不建设通用编排器 |
| 合同继续膨胀 | 新字段必须对应当前安全、身份或业务操作需求 |
| 过早删除旧入口 | 首版只新增最小路径，不删除现有 loader/archive |

## 9. 实施规则

- 本文当前仍为 `BLOCKED`；作为 Stage 4D 的前置切片，1C-A 可在明确授权下准备影子交接，1C-B/正式执行仍等待策略治理、B2A 与独立发布/激活授权，不新增第三条主线；
- 各 Slice 分别授权、实现和验收；
- 后续代码通过仓库 `task-routing` 治理入口交由合格编码后端增量实现，独立只读复核，ARC 最终验收；
- CIA/RAA 决定由对应角色产生，ARC 只负责技术登记和验证；
- 提交、推送、部署均需单独明确授权。

## 10. 激活前待确认

1. 以已归档的板块强度和通达信个股筛选两套工程化交付作为首批Draft输入；
2. 缺失原文重新提取时，内容变化必须保留新旧快照并由CIA确认；
3. RAA通过投研系统只读API逐条审核，报告经AgentOA回传并由ARC CLI摄取；
4. StrategyVersion 首版使用管理 CLI 发布/激活；正式执行读取 Slice 1A 的 active 接口。影子按 1C-A 显式引用已审核、获准且 hash 验证通过的未激活 artifact，不将其放入 active 接口或绕过正式守卫；
5. 两阶段按固定顺序人工执行；板块阶段只执行 Gate 入选路径，不新增通用工作流编排对象；
6. v2.2-rev1 长 Prompt 不进入 Automation；WorkBuddy 路径的固定短 Prompt 和候选 Definition 必须先人工影子验收；
7. 本计划作为Stage 4D前置切片，不新增第三条活动主线。
