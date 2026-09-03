# 投研策略源文档到自动化执行工作流设计

## 1. 目的

定义投研策略从用户原始文档进入投研系统，到 CIA 形成策略提案、RAA 独立审计、WorkBuddy 按结构化数据请求调用 MCP，再由投研系统确定性执行和摄取入库的唯一主流程。

本流程首先服务候选池两阶段选股工作流，后续可复用于深度研究、风险复核和长期观察策略。首批只实现真实垂直切片所需对象和状态，不建设通用文档管理、流程引擎或自动策略优化平台。

## 2. 权威流程

```text
用户提供原始策略文档
  → StrategySourceDocument 登记原文、来源和 hash
  → ARC 发布 WorkBuddy 数据能力评估任务
  → StrategyCapabilityAssessment
  → CIA 形成 strategy.json + strategy.md
  → StrategyProposal / StrategyProposalRevision
  → 投研系统确定性 validation
  → RAA 审计（按风险要求）
  → CIA 人工批准、拒绝或退回修改
  → immutable StrategyVersion
  → DataAcquisitionDefinition
  → 人工显式激活
  → 投研系统生成版本化 DataRequest
  → WorkBuddy 调用获准 MCP 并生成 DataBundle
  → 投研系统校验 DataBundle，由专用 evaluator 计算并原子归档
  → StageResult / StrategyRun
  → 下游工作流或 CandidateAdmission
```

交付物到达、WorkBuddy 状态成功、HTTP 200 或文件出现都不代表正式入库成功。只有投研系统完成合同校验、artifact 归档和数据库事务后，才形成正式 StageResult。

旧候选池中的策略和报告未通过 CIA 审查，只能登记为 `legacy_unapproved`、`test_only`、`non_authoritative`。它们可用于验证摄取、阶段衔接、错误处理和报告差异展示，但不得作为正式策略语义、预期选股结果或新策略必须复现的验收基线。

## 3. 角色职责

| 角色 | 职责 | 不得执行 |
|---|---|---|
| 用户 | 提供原始策略意图、材料和最终授权 | 不以聊天文本直接修改 active 版本 |
| CIA | 形成并审核策略业务逻辑、适用范围、规则、阈值、风险和失效条件 | 不绕过投研系统保存正式策略状态 |
| ARC | 登记源文档、设计 DataRequest/DataBundle 合同、实现专用 evaluator、验证自动化实现 | 不替 CIA 作投研判断，不直接批准策略 |
| WorkBuddy | 实测数据能力，按 DataRequest 调用获准 MCP 并生成 DataBundle | 不创建、修改或解释 StrategyVersion，不决定正式候选 |
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

保存 CIA 基于源文档和能力评估形成的可执行策略提案。

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

### 4.5 DataAcquisitionDefinition

保存某一 StrategyVersion 需要 WorkBuddy 如何获取和交付外部数据，不保存策略业务规则、阈值或自然语言执行 Prompt。

最小职责：

- 绑定 StrategyVersion、stage、`allowed_connectors`、`data_request_template` 和 `output_contract`；
- 一个 DataRequest 可包含多个语义独立的 dataset；每个 dataset 的 `allowed_connectors`
  按主源到 fallback 的优先顺序排列，不表示可任意择源；
- 通过局域网 active 只读接口向固定启动 Prompt 提供结构化执行规格；
- 首版只保存两个随代码发布的不可变、版本化 JSON artifact；active 表示当前部署版本
  对该 definition key 暴露的唯一 artifact，不建立数据库聚合、迁移或管理 CLI；
- 记录幂等键规则、超时和失败处理；
- 不复制策略规则，不保存凭证，不直接代表 active StrategyVersion；
- 定义变更创建新 artifact 版本并随受控发布切换，不原地覆盖历史版本。

首版只实现板块和个股两个固定定义，不建设通用调度平台、表达式语言或任意 DAG。

### 4.6 StrategyRun / StageResult

保存自动化实际运行和投研系统正式摄取结果。

最小职责：

- 绑定 StrategyVersion、DataAcquisitionDefinition、DataRequest、DataBundle、InputSnapshot 和数据矩阵版本；
- 保存原始 DataBundle、确定性 evaluator 输出、manifest、validation record 和 hash；
- 复用现有 ExternalWorkflowRun、ExternalArtifact 和 WorkBuddy 原子归档能力，不新增
  DataBundle 专属数据库表或第二套 manifest/归档框架；
- 区分执行状态、交付状态、摄取状态和业务结果状态；
- 只有完成正式摄取才形成 StageResult。

## 5. 模块接口和接缝

首批保持四个深模块，各自使用小接口：

1. 源文档登记模块：接收原始文档与元数据，返回不可变 StrategySourceDocument。
2. 能力评估模块：接收 source document 和矩阵版本，发布评估任务并返回 StrategyCapabilityAssessment。
3. 策略治理模块：接收提案交付物，完成 validation、审计、决定和不可变版本创建。
4. 数据获取与执行模块：接收 active StrategyVersion 和 DataAcquisitionDefinition，生成 DataRequest、摄取 DataBundle，并用专用 evaluator 返回 StageResult。

模块之间只传正式对象身份和 artifact 引用，不传数据库行结构，不通过 Markdown 文本或共享目录文件名猜测业务状态。

## 6. 交付合同

### 6.1 能力评估交付

首批复用并按策略范围裁剪：

- `capability-assessment.json`：机器权威；
- `capability-assessment.md`：人工说明；
- `capability-probes.json`：真实探测证据。

机器合同只强制身份、schema version、source document、矩阵版本、数据截止时间、能力状态和 artifact hash。数据源解释、替代方案和限制允许 warning/review。

### 6.2 策略提案交付

- `strategy.json`：机器可执行策略提案；
- `strategy.md`：人工审核说明；
- `validation.json`：生产者验证材料；
- 可选 `change-proposal.json`：已有策略的演进建议。

CIA 负责策略语义；投研系统 validation 和 RAA 审计仍是版本发布门禁。WorkBuddy 的能力探测只证明字段可获取，不证明策略正确或可批准。

### 6.3 数据获取与确定性执行交付

WorkBuddy 只交付版本化 `DataBundle`：包含 request identity、as_of、分页、样本量、字段、单位、原始或最小规范化数据、warning 和 error。每个 dataset 按调用顺序保存结构化 attempts，attempt 是 connector、tool 和脱敏参数的唯一权威来源；最后一个 `succeeded` attempt 即该 dataset 的最终来源，不在 dataset 顶层重复同一组字段。failed attempt 只使用固定允许列表内的稳定错误码；attempt connector 不得重复，数量不得超过当前获准 connector 总数。使用 fallback 时，必须能证明优先级更高的来源已经失败。投研系统负责 Schema、canonical JSON、hash、lineage、原子发布以及 StageResult/CandidateProposal；首版不建立覆盖所有阶段的万能业务 schema。

首版每个 `dataset_key` 只接受一个最终成功来源，不允许 WorkBuddy 静默拼接、覆盖或裁决多个来源。同一业务事实确需并行来源对照时，必须在 DataRequest 中拆成不同 `dataset_key`，再由对应专用 evaluator 显式处理；跨源融合、动态评分和通用路由继续延期。

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

首版不建立 DataAcquisitionDefinition 生命周期状态机。只有 active StrategyVersion 与当前部署版本暴露的固定 DataAcquisitionDefinition artifact 组合才能生成 DataRequest；定义切换通过新的不可变 artifact 版本和受控发布完成。周期调度仍须独立显性授权。

### 7.4 运行和摄取

```text
task_published
  → running
  → delivered
  → validating
  → ingested / review / failed
```

业务结果状态由具体阶段合同定义，例如 `succeeded/partial/needs_rule_confirmation/blocked_no_data/failed`，不得与运行或摄取状态混用。

## 8. 首个候选池测试垂直切片

首个测试场景从用户提供的两篇原始策略文章开始，在新工作流中重新完成数据能力评估、策略工程化和 CIA 审查：

- 《从零开始：每日“板块强度排行榜”制作完整流程图解》：`https://m.toutiao.com/is/fslPVWFTKSY/`；
- 《炒股十几年，我悟了：主力最怕散户学会的东西，都藏在通达信里》：`https://m.toutiao.com/is/QwmHBSMbhGQ/`。

1. 将两篇头条文章登记为 StrategySourceDocument；
2. 评估通达信、金融 MCP、投研 API 和 fallback 的实际数据覆盖；
3. CIA 分别形成板块强度与通达信个股筛选 StrategyProposal，并显式列出对原文的所有工程化补充、阈值和偏离；
4. 完成 validation、所需审计和 CIA 批准，创建两个不可变 StrategyVersion；
5. 创建两个最小 DataAcquisitionDefinition，并通过 active 只读 API 提供结构化规格；
6. WorkBuddy 获取板块数据并提交 DataBundle，投研系统板块专用 evaluator 生成 SectorStageResult；
7. 以已校验 SectorStageResult 生成个股 DataRequest；
8. WorkBuddy 获取限定成分股数据并提交 DataBundle，投研系统个股专用 evaluator 生成 StockStageResult 和 CandidateProposal；
9. 投研系统通过内部可信接缝为 CandidateProposal 创建待准入 Observation，经 CandidateAdmission 形成 CandidateEntry 或可解释空结果。

只有完成 CIA 批准和显式激活后，测试工作流才可切换为正式候选生产。2026-08-13 的旧策略、旧报告、23 → 20 → 5 → 2 → 0 和 `needs_rule_confirmation` 仅作为非权威测试 fixtures；新提案和新报告允许且预期与其不同。

## 9. 分阶段实施顺序

### Phase A：入口与证据

- StrategySourceDocument 登记与不可变原文归档；
- 策略范围能力评估任务和 StrategyCapabilityAssessment；
- 使用真实源文档完成一次 ready/degraded/blocked fixture 验收。

### Phase B：策略治理

- StrategyProposal/Revision 摄取；
- 系统 validation、RAA 审计和 CIA 决定；
- 创建并显式激活不可变 StrategyVersion。

### Phase C：数据获取定义

- 两个静态 DataAcquisitionDefinition artifact、DataRequest/DataBundle 合同与部署版本绑定；
- active 只读 API、固定短 Prompt、connector 白名单和交付合同绑定；
- 只允许人工触发影子运行；周期调度必须另行显性授权。

### Phase D：运行与摄取

- 发布 DataRequest、WorkBuddy 获取数据、DataBundle 校验；
- 原子认领、不可变归档、幂等入库和恢复；
- 两个专用 evaluator 形成 StrategyRun/StageResult。

### Phase E：候选池真实闭环

- 串联板块与个股两个策略阶段；
- 使用旧报告验证测试fixture隔离和差异展示，再以 CIA 批准的新策略运行一个新交易日；
- CandidateProposal → CandidateAdmission → CandidateEntry 验收。

## 10. 验收门禁

- 任一 StrategyVersion 可追溯到原始 StrategySourceDocument、能力评估、提案 revision、validation、审计和批准决定；
- WorkBuddy 不能创建或激活正式 StrategyVersion；
- `legacy_unapproved/test_only/non_authoritative` 策略和报告不能激活、不能创建正式候选；
- 数据获取定义不复制策略业务规则，并可独立暂停；
- 只有 active 策略与 active 数据获取定义组合能生成 DataRequest；
- WorkBuddy 只交付 DataBundle，不决定正式 StageResult、CandidateProposal 或 CandidateAdmission；
- DataBundle 保留 `producer=workbuddy`，系统生成的 CandidateProposal 保留 `producer=invest-infra`；不得借用外部 Candidate Bridge 混淆生产者；
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
- 通用策略解释器、表达式语言、任意 DAG 或首版周期自动调度；
- 将凭证、共享宿主机绝对路径或内部数据库结构写入策略交付物。
