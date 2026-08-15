# 投研策略源文档到自动化执行工作流设计

## 1. 目的

定义投研策略从用户原始文档进入投研系统，到 WorkBuddy 完成数据能力评估、策略工程化、自动化执行和报告交付，再由投研系统摄取入库的唯一主流程。

本流程首先服务候选池两阶段选股工作流，后续可复用于深度研究、风险复核和长期观察策略。首批只实现真实垂直切片所需对象和状态，不建设通用文档管理、流程引擎或自动策略优化平台。

## 2. 权威流程

```text
用户提供原始策略文档
  → StrategySourceDocument 登记原文、来源和 hash
  → ARC 发布 WorkBuddy 数据能力评估任务
  → StrategyCapabilityAssessment
  → ARC 发布策略工程化任务
  → WorkBuddy 交付 strategy.json + strategy.md + validation.json
  → StrategyProposal / StrategyProposalRevision
  → 投研系统确定性 validation
  → RAA 审计（按风险要求）
  → CIA 人工批准、拒绝或退回修改
  → immutable StrategyVersion
  → StrategyAutomationDefinition
  → 人工显式激活
  → 自动发布 StrategyTask
  → WorkBuddy 执行并生成结构化结果 + Markdown 报告 + 质量结果
  → 投研系统校验、不可变归档和入库
  → StageResult / StrategyRun
  → 下游工作流或 CandidateAdmission
```

交付物到达、WorkBuddy 状态成功、HTTP 200 或文件出现都不代表正式入库成功。只有投研系统完成合同校验、artifact 归档和数据库事务后，才形成正式 StageResult。

## 3. 角色职责

| 角色 | 职责 | 不得执行 |
|---|---|---|
| 用户 | 提供原始策略意图、材料和最终授权 | 不以聊天文本直接修改 active 版本 |
| CIA | 审核策略业务逻辑、适用范围、风险和失效条件 | 不绕过投研系统保存正式策略状态 |
| ARC | 登记源文档、发布技术任务、设计合同、验证自动化实现 | 不替 CIA 作投研判断，不直接批准策略 |
| WorkBuddy | 实测数据能力、工程化策略、执行策略、生成交付物 | 不创建、修改或激活正式 StrategyVersion |
| RAA | 按风险要求独立审计策略、证据和验证记录 | 不替代 CIA 决定或系统 validation |
| 投研系统 | 保存策略源、提案、版本、自动化定义、运行、报告和审批的唯一正式状态 | 不把外部工具状态当作业务完成信号 |

## 4. 最小领域对象

### 4.1 StrategySourceDocument

保存用户提供的原始策略材料，是后续所有提案和版本的追溯根。

最小职责：

- 保存稳定身份、原始文件引用、内容 hash、提交时间和提交来源；
- 保存可选的目标、适用市场和用户补充说明；
- 原文不可变；修改必须创建新 revision 或新 source document；
- 不解释策略、不承担正式策略状态。

### 4.2 StrategyCapabilityAssessment

保存 WorkBuddy 对指定源文档和数据矩阵版本的真实能力评估。

最小职责：

- 绑定 source document、评估任务、数据截止时间和 DataAcquisitionMatrixVersion；
- 按策略所需数据记录 available/degraded/unavailable/not_tested；
- 记录覆盖范围、新鲜度、稳定性、可重放性、fallback 和缺口；
- 输出 `ready`、`ready_with_degradation`、`needs_review` 或 `blocked`；
- 不创建策略版本，不把产品宣传当作已验证能力。

### 4.3 StrategyProposal

保存 WorkBuddy 基于源文档和能力评估形成的可执行策略提案。

最小职责：

- 绑定 StrategySourceDocument 和 StrategyCapabilityAssessment；
- 保存 `strategy.json`、`strategy.md`、`validation.json` 及 artifact hash；
- 修改产生不可变 StrategyProposalRevision；
- 只有通过系统 validation、所需审计和 CIA 决定后才能创建 StrategyVersion。

### 4.4 StrategyVersion

保存经过批准的不可变策略语义。

最小职责：

- 保存稳定策略身份、版本、适用范围、数据依赖、规则、失效条件和来源 revision；
- 发布后不可原地修改；
- approved 不等于 active；
- 历史任务、运行和结果永久引用执行时版本。

### 4.5 StrategyAutomationDefinition

保存某一 StrategyVersion 如何被自动执行和交付，不保存策略业务规则本身。

最小职责：

- 绑定 StrategyVersion、stage、任务模板、执行 adapter、调度、输入装配和交付合同版本；
- 记录启停状态、有效期、幂等键规则、超时和失败处理；
- 不复制策略规则，不保存凭证，不直接代表 active StrategyVersion；
- 自动化定义变更必须版本化并显式激活；
- 禁用自动化只停止新任务，不修改历史策略和运行。

### 4.6 StrategyRun / StageResult

保存自动化实际运行和投研系统正式摄取结果。

最小职责：

- 绑定 StrategyVersion、AutomationDefinition、任务、InputSnapshot 和数据矩阵版本；
- 保存原始结构化结果、Markdown 报告、质量结果、manifest、validation record 和 hash；
- 区分执行状态、交付状态、摄取状态和业务结果状态；
- 只有完成正式摄取才形成 StageResult。

## 5. 模块接口和接缝

首批保持四个深模块，各自使用小接口：

1. 源文档登记模块：接收原始文档与元数据，返回不可变 StrategySourceDocument。
2. 能力评估模块：接收 source document 和矩阵版本，发布评估任务并返回 StrategyCapabilityAssessment。
3. 策略治理模块：接收提案交付物，完成 validation、审计、决定和不可变版本创建。
4. 自动化运行模块：接收 active StrategyVersion 和 AutomationDefinition，发布任务并返回经摄取的 StageResult。

模块之间只传正式对象身份和 artifact 引用，不传数据库行结构，不通过 Markdown 文本或共享目录文件名猜测业务状态。

## 6. 交付合同

### 6.1 能力评估交付

首批复用并按策略范围裁剪：

- `capability-assessment.json`：机器权威；
- `capability-assessment.md`：人工说明；
- `capability-probes.json`：真实探测证据。

机器合同只强制身份、schema version、source document、矩阵版本、数据截止时间、能力状态和 artifact hash。数据源解释、替代方案和限制允许 warning/review。

### 6.2 策略工程化交付

- `strategy.json`：机器可执行策略提案；
- `strategy.md`：人工审核说明；
- `validation.json`：生产者验证材料；
- 可选 `change-proposal.json`：已有策略的演进建议。

WorkBuddy 的 validation 是提案材料，不替代投研系统 validation、RAA 审计或 CIA 决定。

### 6.3 自动执行交付

每个具体策略阶段定义自己的结构化结果和质量结果；Markdown 使用推荐模板，不要求固定标题或逐字一致。所有交付包共享最小严格信封，但不建立覆盖所有阶段的万能业务 schema。

## 7. 状态与门禁

### 7.1 源文档与评估

```text
registered
  → assessment_pending
  → assessed_ready / assessed_degraded / needs_review / blocked
```

`blocked` 不销毁源文档；数据能力变化后可基于新矩阵版本重新评估。

### 7.2 策略治理

```text
proposal
  → validating
  → validation_failed / review_pending
  → changes_requested / rejected / approved
  → versioned
  → active / suspended / retired
```

内容、source document、assessment 或数据矩阵版本变化时，旧 revision 的决定失效。

### 7.3 自动化

```text
draft
  → validated
  → active
  → paused / retired
```

只有 active StrategyVersion 与 active StrategyAutomationDefinition 的组合才能自动发布新任务。自动化暂停不改变策略版本状态。

### 7.4 运行和摄取

```text
task_published
  → running
  → delivered
  → validating
  → ingested / review / failed
```

业务结果状态由具体阶段合同定义，例如 `succeeded/partial/needs_rule_confirmation/blocked_no_data/failed`，不得与运行或摄取状态混用。

## 8. 首个候选池垂直切片

首个正式样本使用原候选池两阶段工作流：

1. 登记板块七步与个股六维策略来源文档；
2. 评估通达信、金融 MCP、投研 API 和 fallback 的实际数据覆盖；
3. 分别形成 `sector-seven-step` 与 `tdx-six-dimension` StrategyProposal；
4. 完成 validation、所需审计和 CIA 批准，创建两个不可变 StrategyVersion；
5. 创建一个 CandidateSelectionWorkflowVersion 和两个 StrategyAutomationDefinition；
6. 自动执行板块阶段，摄取结构化结果、Markdown 和质量结果；
7. 以已校验 SectorStageResult 创建个股阶段任务；
8. 摄取 StockStageResult，生成 CandidateProposal；
9. 经 CandidateAdmission 形成 CandidateEntry 或可解释空结果。

2026-08-13 原始工作流的 23 → 20 → 5 → 2 → 0 与 `needs_rule_confirmation` 作为首个行为回放基线。

## 9. 分阶段实施顺序

### Phase A：入口与证据

- StrategySourceDocument 登记与不可变原文归档；
- 策略范围能力评估任务和 StrategyCapabilityAssessment；
- 使用真实源文档完成一次 ready/degraded/blocked fixture 验收。

### Phase B：策略治理

- StrategyProposal/Revision 摄取；
- 系统 validation、RAA 审计和 CIA 决定；
- 创建并显式激活不可变 StrategyVersion。

### Phase C：自动化定义

- StrategyAutomationDefinition 合同、版本和状态；
- 任务模板、输入装配、执行 adapter、调度和交付合同绑定；
- 人工触发通过后再启用周期调度。

### Phase D：运行与摄取

- 发布任务、WorkBuddy 执行、交付物校验；
- 原子认领、不可变归档、幂等入库和恢复；
- 形成 StrategyRun/StageResult。

### Phase E：候选池真实闭环

- 串联板块与个股两个策略阶段；
- 回放 2026-08-13 基线和一个新交易日；
- CandidateProposal → CandidateAdmission → CandidateEntry 验收。

## 10. 验收门禁

- 任一 StrategyVersion 可追溯到原始 StrategySourceDocument、能力评估、提案 revision、validation、审计和批准决定；
- WorkBuddy 不能创建或激活正式 StrategyVersion；
- 自动化定义不复制策略业务规则，并可独立暂停；
- 只有 active 策略与 active 自动化定义组合能发布任务；
- 运行成功不替代交付、摄取和业务结果状态；
- JSON 为机器权威，Markdown 格式差异不阻断安全交付；
- 原始 artifact、manifest、validation record、数据库记录和 hash 一致；
- 候选策略结果不能绕过 CandidateAdmission；
- 首个垂直切片可回放、可暂停、可重试和可解释失败。

## 11. 明确不做

- 通用 OA、任意流程设计器和企业文档管理平台；
- 自动批准、自动激活或 WorkBuddy 直接修改生产策略；
- 一份覆盖所有策略和阶段的万能 schema；
- 在首个候选池闭环前建设自动调参、复杂回测和多资产平台；
- 解析 Markdown 标题或自然语言推进正式状态；
- 将凭证、共享宿主机绝对路径或内部数据库结构写入策略交付物。
