# Stage 4D–4G 策略库驱动投研工作流实施计划

## Overview

建设一条可持续演进的投研主工作流：投研系统以版本化策略发布候选发现任务，WorkBuddy 生成候选交付物；投研系统完成正式准入后发布深度研究任务，WorkBuddy 专家团队生成研究交付物；正式研究进入长期观察、投资建议和后验评价，并通过受控变更提案形成新的策略版本。首批只贯通一个真实 ETF 垂直切片，再扩展多策略和可视化。

## Architecture decisions

- 投研系统是策略、版本、准入、ResearchResult、观察状态和审批的唯一权威源。
- WorkBuddy 是候选发现、深度研究、风险反证、观察复评和改进建议的执行者。
- Candidate 阶段由 WorkBuddy 使用 Skills、多个金融 MCP、Connector、通达信和公开信息做广覆盖发现；投研系统 API 不是唯一数据源，只负责内部权威参照、身份和正式准入。
- Research 阶段收窄标的与问题，但继续多源交叉验证；外部事实和内部权威数据冲突时保留来源并进入 Evidence/Admission。
- 共享目录按 `strategy/candidate/research/observation` 分区，按生命周期流转；具体策略由元数据标识。
- `StrategyVersion` 和 `CandidateSelectionWorkflowVersion` 发布后不可变，所有任务和结果保留工作流及组成策略版本归因。
- WorkBuddy 交付物校验和正式入库是完成信号，运行状态和 HTTP 200 只是诊断信号。
- 策略反馈先形成 `StrategyChangeProposal`，经过验证和人工审批后才能发布新版本。
- 候选策略、研究策略、观察策略和持仓建议策略分离，避免一条大策略承担全部职责。

## Dependency graph

```text
S0 领域合同
  → S0A 阶段摄取与自动归档基础
    → S1 Strategy Governance 人工审核闭环
      → S1A CIA/RAA OpenClaw 适配
        → S2 候选发现闭环
          → S3 深度研究闭环
            → S4 长期观察闭环
              → S5 投资建议与组合联动
                → S6 策略评价与版本演进
                  → S7 多策略和可视化
```

## Phase S0：领域合同冻结

### Task S0.1：冻结对象与职责

定义 `StrategySourceDocument`、`StrategyCapabilityAssessment`、`Strategy`、`StrategyVersion`、`StrategyAutomationDefinition`、`CandidateSelectionWorkflowVersion`、`CandidateSelectionRun`、`StrategyTask`、`StrategyRun/StageResult`、`CandidateProposal`、`CandidateAdmission`、`CandidateEntry`、`ResearchCase/Run/Result`、`WatchlistEntry`、`StrategyEvaluation`、`StrategyChangeProposal` 的职责和关系。

Acceptance criteria:

- 每个事实只有一个权威对象；
- 候选、研究、观察和组合建议不互相替代；
- 单个策略规则与多策略选择工作流分离，Candidate Pool 只保存正式准入结果；
- 历史对象可追溯到不可变工作流版本及其全部组成策略版本。

Verification: ADR/领域模型评审通过，现有 ExternalObservation 与 Research 对象可复用，不新增重复聚合。

权威入口和完整生命周期见 `docs/plan/invest-infra-strategy-source-to-automation-workflow.md`。

### Task S0.2：冻结跨阶段任务合同

所有任务强制携带 `task_id/stage/strategy_id/strategy_version/schema_version`；候选任务额外携带工作流版本、阶段角色和上游 StageResult 引用。冻结 strategy/candidate/research/observation 的输入和交付物合同。

Acceptance criteria:

- 路径只表达阶段和生命周期；
- 元数据完整表达策略身份；
- 不兼容合同确定性失败，不猜测解析。

Verification: strategy/candidate/research/observation 合同测试覆盖成功、partial、failed、损坏和重复交付。

### Task S0.3：冻结数据获取矩阵

发布 WorkBuddy 数据能力盘点任务，真实探测已安装 Skills、金融 MCP、Connector、通达信和投研 API，形成 candidate/research/observation 三阶段数据路由矩阵。

Acceptance criteria:

- 每类数据具有 discovery、cross-check、authoritative admission 和 fallback 路由；
- 每个来源记录 source/as_of/unit/definition、覆盖范围、新鲜度、稳定性和可重放性；
- 未实际验证的能力标记 not_tested，不按产品宣传推断可用。

Verification: `data-matrix.json`、`data-matrix.md`、`capability-probes.json` 完整且可由宿主机复核。

现场基线（2026-08-15）：任务 `data-acquisition-matrix-20260815-0003` 已交付 21 类路由和 35 项探测；核心可用源为 tdx-connector、westock-mcp、mx-ds-mcp，invest-api 当前身份/工作流可用但行情准入数据 stale。矩阵按版本保存，后续能力变化通过新任务生成新版本，不覆盖基线。

## Phase S0A：阶段摄取与自动归档基础（最高优先级）

### Task S0A.1：统一 Stage Artifact Worker

实现 `strategy/candidate/research/observation` 的共同生命周期内核：发现 `.ready`、原子认领至 processing、调用阶段专属校验器、数据库事务入库、写 manifest/validation record、成功 archive、异常 failed、重启恢复和重复幂等。

Acceptance criteria:

- Worker 不把目录出现或 WorkBuddy succeeded 当作业务成功；
- 数据库失败不会产生成功归档，重启后可安全重试；
- 每个阶段使用独立合同，公共生命周期实现不复制四份。

Verification: 四阶段成功/损坏/重复/冲突/数据库失败/重启恢复集成测试通过，并用真实 data-matrix 交付包重放验收。

### Task S0A.2：生产调度修复与运行验收

修复 Dagster/systemd 当前停止、WorkBuddy schedule 环境变量不匹配和只扫描旧 `选股报告/candidates_*.json` 的问题，改为调度 Stage Artifact Worker。

Acceptance criteria:

- 服务重启和用户退出后仍持续运行；
- 新阶段 `.ready` 包可触发或被周期扫描；
- backlog、失败和最后成功摄取时间可观测。

Verification: Ops执行服务重启和连续两轮真实任务验收；ARC验证代码、配置和测试，不以服务进程存在替代业务结果。

### Task S0A.3：正式准入数据恢复

恢复 daily-bars、freshness snapshot 和 pipeline run，使内部权威行情可参与 CandidateAdmission。

Acceptance criteria:

- `daily_bar_count > 0` 且目标标的可查询；
- freshness 不再为 stale/missing；
- 数据源、trade_date、snapshot 和 pipeline run 可追溯。

Verification: API、数据库和真实候选准入前置检查通过。

## Phase S1：Strategy Governance 人工审核闭环

### Task S1.0A：策略源文档登记

接收用户交给 CIA 或 ARC 的原始策略文档，保存不可变 StrategySourceDocument、来源、提交时间、原始 artifact 和内容 hash。ARC 只负责技术登记和任务发布，不替 CIA 判断策略业务逻辑。

Acceptance criteria:

- 原文可追溯、不可原地覆盖，重复内容幂等；
- 新修订产生新 revision，并使依赖旧内容的待审决定失效；
- 聊天文本或共享目录文件出现不直接创建正式策略。

Verification: 原文、重复、修订、hash 冲突和 artifact 缺失 fixtures 通过。

### Task S1.0B：策略范围数据能力评估

ARC 基于 StrategySourceDocument 发布 WorkBuddy 能力评估任务。WorkBuddy 实测策略需要的数据来源、覆盖、新鲜度、稳定性、可重放性和 fallback，投研系统摄取为 StrategyCapabilityAssessment。

Acceptance criteria:

- assessment 绑定 source document、任务、数据截止时间和 DataAcquisitionMatrixVersion；
- 结果明确为 ready、ready_with_degradation、needs_review 或 blocked；
- unavailable/not_tested 不得伪装为可执行能力；
- assessment 不创建 StrategyVersion。

Verification: ready、degraded、review、blocked、重复和矩阵版本变化 fixtures 通过。

### Task S1.0：策略制定任务与提案摄取

基于 StrategySourceDocument 和 StrategyCapabilityAssessment 发布策略工程化任务。WorkBuddy 交付 `strategy.json + strategy.md + validation.json`，策略优化时额外交付 `change-proposal.json`。摄取后只创建 StrategyProposal，不直接创建 active 版本。

Acceptance criteria:

- 提案可追溯到任务、输入材料、数据截止时间和交付物 hash；
- 提案必须绑定源文档和能力评估，blocked assessment 不能伪装为可执行策略；
- schema、数据能力、可计算性和未来数据泄露检查失败时不能正式化；
- WorkBuddy 不能绕过人工审批创建或修改 active 版本。

Verification: 提案成功、验证失败、拒绝、重复和篡改 fixture 全部得到确定状态。

### Task S1.1：Strategy 与 StrategyVersion

实现稳定策略身份、不可变版本、类型、适用市场/标的、数据依赖、任务模板和变更原因。

Acceptance criteria:

- 可创建 ETF 候选发现策略 v1；
- v2 不修改 v1 历史语义；
- 任务只能引用存在的版本。

Verification: domain、repository、migration 和 API 测试通过。

### Task S1.1D：CandidateSelectionWorkflowVersion

实现不可变候选选择工作流版本，首批按真实业务顺序组合板块七步策略和个股六维策略两个完整 `StrategyVersion`。工作流模块只暴露“以冻结输入运行两阶段选股并返回 CandidateProposal 集合”的小接口；每个策略内部的筛选、评分、否决、排序和解释步骤保持在策略实现内部。

Acceptance criteria:

- 工作流版本显式引用全部组成策略版本，发布后不可变；
- `CandidateSelectionRun` 绑定工作流版本、InputSnapshot、数据矩阵版本、输入/输出 hash；
- 个股阶段输入显式绑定已校验的板块 StageResult、上游 run id 和 artifact hash；
- 每阶段保存结构化结果、Markdown 报告、质量结果、计数、警告和复核状态；
- 每个 CandidateProposal 可追溯两个策略版本和阶段运行；
- 首批不把策略内部规则提升为公共节点，也不建设通用 DAG、图形编排器、自定义表达式语言或动态插件系统。

Verification: 将 2026-08-13 旧报告作为 `legacy_unapproved/test_only/non_authoritative` fixtures，验证阶段依赖、摄取和正式状态隔离；新工作流只验证 CIA 批准版本的重复运行与历史版本重放，不要求复现旧结果。

### Task S1.1A：Proposal Revision 与验证记录

实现 `StrategyProposalRevision`、`StrategyValidationRun` 和 `DataAcquisitionMatrixVersion`，每次修改产生新 revision，旧 revision 永久不可变。

Acceptance criteria:

- revision 绑定原始交付物 hash、数据截止时间和矩阵版本；
- validation 记录 Schema、数据能力、可计算性、未来数据泄露和样本检查；
- validation_failed 不能进入正式审核。

Verification: revision 并发、旧版本重放、hash 冲突和验证失败测试通过。

### Task S1.1B：ReviewPackage 与 CIA人工决定

生成包含策略摘要、规则、数据矩阵、验证结果、父版本 diff、风险、失效条件和原始 hash 的 ReviewPackage；提供受控 API/UI 接收 CIA 的批准、拒绝和退回修改决定。

Acceptance criteria:

- Decision 绑定 proposal/revision/content hash/data matrix version；
- 内容变化或旧 revision 提交决定时 fail closed；
- approved 只允许创建不可变 StrategyVersion，不自动 active。

Verification: API、权限、并发、旧 hash 和端到端人工审核测试通过。

### Task S1.1C：RAA审计记录

实现独立 `StrategyAudit`，保存审计结论、问题、证据引用、审计人和被审 revision。首批允许人工录入，不阻塞后续 OpenClaw 适配。

Acceptance criteria:

- Audit 不覆盖 validation 或 CIA decision；
- 审计 revision/hash 不匹配时拒绝；
- 高风险策略无所需 audit 时不能进入 CIA 批准。

Verification: 审计缺失、通过、有条件通过和拒绝测试通过。

### Task S1.2：策略生命周期

实现 `draft → validating → approved → active → suspended → retired`，校验合法迁移和发布权限。

Acceptance criteria:

- 只有 active 版本可由定时流程发布任务；
- suspended/retired 禁止新任务但保留历史；
- 同一策略的生产版本切换可审计。

Verification: 状态迁移和并发版本测试通过。

### Task S1.3：StrategyAutomationDefinition

为已批准的 StrategyVersion 建立版本化自动化定义，绑定 stage、任务模板、执行 adapter、调度、输入装配、交付合同、幂等和失败处理。自动化定义不复制策略业务规则，必须经过验证和显式激活。

Acceptance criteria:

- 只有 active StrategyVersion 与 active AutomationDefinition 的组合可自动发布任务；
- 自动化可独立 paused/retired，不修改策略版本和历史运行；
- 先完成人工触发验收，再允许周期调度；
- 运行、交付、摄取和业务结果状态彼此分离。

Verification: draft/active/paused/retired、版本切换、重复调度、失败恢复和旧合同测试通过。

## Phase S1A：CIA/RAA OpenClaw 适配（人工闭环通过后）

### Task S1A.1：审核包派送与决定回写

建立窄 Adapter，将 invest-infra ReviewPackage 派送给 CIA/RAA，并把结构化审计/决定回写既有 S1 接口。GTD/OpenClaw 只负责协作和通知，不保存正式策略状态。

Acceptance criteria:

- Adapter 无数据库直写能力；
- 回写必须通过身份、revision 和 hash 校验；
- 外部系统不可用时，投研系统人工审核仍可完成。

Verification: fake CIA/RAA、重复回调、旧 revision、超时和不可用降级测试通过。

### Checkpoint S1

- 投研系统可发布一份真实策略制定任务并摄取 WorkBuddy 提案；
- StrategyProposal 可完成 validation、RAA audit 和 CIA 人工决定；
- StrategyVersion 可追溯到 StrategySourceDocument 和 StrategyCapabilityAssessment；
- 板块策略、个股策略及其 CandidateSelectionWorkflowVersion 可分别审核，并由工作流显式激活、暂停和版本升级；
- 自动化定义可人工触发、独立暂停，尚不启用周期调度；
- 尚不触发真实 WorkBuddy 任务；
- 全量回归和迁移检查通过。

## Phase S2：候选发现闭环

### Task S2.1：策略任务发布

根据 active `CandidateSelectionWorkflowVersion` 创建首阶段板块策略任务并发布到 `Z:\workbuddy\candidate\inbox` 对应宿主机映射。任务绑定工作流版本、板块策略版本、数据矩阵版本和冻结输入。

Acceptance criteria:

- 数据依赖不满足时 fail closed；
- 任务路径、输出路径、工作流版本和板块策略版本正确；
- 重复发布使用确定性幂等键。

Verification: serializer、发布器和路径命名空间测试通过。

### Task S2.2：两阶段报告衔接

摄取板块策略的结构化结果、Markdown 报告和质量结果，校验后形成 SectorStageResult；再以该 StageResult、上游 run id 和 artifact hash 创建个股六维策略任务。个股阶段交付结构化结果、Markdown 报告和质量结果，校验后形成 StockStageResult 和 CandidateProposal。

Acceptance criteria:

- Markdown 用于人工审核，机器状态只读取结构化结果；
- 上游未通过阶段合同规定的门禁时不发布下游任务；
- warning/review 可按合同降级流转，单项坏候选隔离；
- 两阶段原始 artifact、阶段计数和运行身份完整保留。

Verification: 真实 2026-08-13 报告、partial、review、failed、格式变体和重复交付 fixtures 通过。

### Task S2.3：候选准入

将合法 CandidateProposal 保留为 ExternalObservation provenance，经身份、去重、来源、日期和数据质量验证后形成 CandidateAdmission/CandidateEntry。

Acceptance criteria:

- 坏项隔离，合法项继续处理；
- 未准入项不能触发研究；
- 多策略命中保留独立归因。

Verification: fixture、幂等、冲突和真实 WorkBuddy 手工验收通过。

### Checkpoint S2

- 一个真实两阶段候选工作流从板块策略进入个股策略并形成正式候选或可解释的空结果；
- 交付物、数据库记录和 hash 可复核；
- 候选页面能展示来源策略和准入状态。

## Phase S3：深度研究闭环

### Task S3.1：研究任务编排

正式候选绑定 `deep_research` 版本，创建/关联 ResearchCase、EvidencePack 和 ResearchRun，并发布 research 任务。

Acceptance criteria:

- 多策略命中的同一标的不重复创建等价研究；
- 研究任务冻结候选理由、证据和时间范围；
- blocked_no_data 不发布伪研究。

Verification: orchestration 和幂等测试通过。

### Task S3.2：研究结果验收

摄取 `result.json + report.md + evidence.json`，校验合同、身份、日期、来源和 Evidence 后生成 ResearchResult。

Acceptance criteria:

- succeeded/partial/failed/blocked_no_data 确定映射；
- Evidence 无效不能成功；
- Gateway/运行状态不改变交付物判定。

Verification: 单元、集成和真实 ETF 垂直测试通过。

### Checkpoint S3

- 同一 ETF 可从 CandidateSelectionWorkflowVersion、组成 StrategyVersion 追溯到 CandidateEntry 和 ResearchResult；
- WorkBuddy 专家团队交付完成正式入库；
- 未通过此门禁不得进入自动策略优化。

## Phase S4：长期观察闭环

### Task S4.1：WatchlistEntry

研究结果按准入规则形成观察条目，保存投资假设、指标、风险、复评周期、触发器和退出条件。

Acceptance criteria:

- ResearchCase 永久档案与当前观察状态分离；
- 研究失败或否定结论不强制入观察；
- 状态迁移和历史版本可追溯。

Verification: domain、storage 和 API 测试通过。

### Task S4.2：观察复评任务

固定周期或事件触发 observation 任务，摄取 `review.json + report.md` 并追加观察版本。

Acceptance criteria:

- 复评不覆盖历史；
- strengthened/weakened/review_required/closed 有明确条件；
- 重复事件不会产生重复复评。

Verification: 定时、事件、幂等和真实复评测试通过。

## Phase S5：投资建议与组合联动

### Task S5.1：Investment Proposal

汇总研究、观察、市场状态和风险约束生成可解释建议。

Acceptance criteria:

- 研究结论和持仓建议分开保存；
- 建议引用策略版本与证据；
- 未审批建议不能产生交易动作。

Verification: proposal、risk check 和 approval 测试通过。

### Task S5.2：Stage 4F 接口

批准后的建议进入组合/OMS，WorkBuddy 仍只作为监督式执行适配器。

Acceptance criteria:

- 投研系统保持订单和持仓唯一账本；
- 审批后冻结；
- 对账异常 fail closed。

Verification: Stage 4F 合同和手工监督式执行验收通过。

## Phase S6：策略评价与演进

### Task S6.1：StrategyEvaluation

按候选、研究、观察、市场阶段和持仓建议分别计算评价，避免混合成单一分数。

Acceptance criteria:

- 单个标的不能直接改变整体策略；
- 评价窗口和数据截止时间固定；
- 可比较同一策略不同版本。

Verification: 确定性后验和版本比较测试通过。

### Task S6.2：StrategyChangeProposal

WorkBuddy 基于多次运行提交结构化改进建议，投研系统执行验证、审批并发布新版本。

Acceptance criteria:

- 提案不能直接修改 active 版本；
- 新版本保留 parent_version 和 change_reason；
- 提出者不能成为唯一评价者。

Verification: 提案、审批、拒绝和版本发布全链测试通过。

## Phase S7：多策略与可视化

### Task S7.1：多策略运行与归因

支持 independent/complementary/exclusive 关系、候选合并研究和分策略评价。

Acceptance criteria:

- 多策略命中不重复研究；
- 每条策略归因不丢失；
- 互斥策略不会在同一场景错误并发。

Verification: 双策略 ETF 场景 E2E 通过。

### Task S7.2：四个工作台

交付策略库、候选工作台、研究与观察工作台、策略评价页面。

Acceptance criteria:

- 所有页面读取统一领域对象；
- 可从策略版本导航到任务、候选、研究、观察和评价；
- UI 不根据文件路径重建业务状态。

Verification: API、Web、权限和真实数据演示通过。

## Release gates

- S0A 未通过，不宣称共享目录自动归档闭环成立。
- S1 未通过，不发布策略驱动任务。
- S1 人工审核闭环未通过，不开发 CIA/RAA 自动适配旁路。
- S2 未通过，不自动生成研究任务。
- S3 未通过，不宣称研究闭环完成。
- S4 未通过，不将观察结果用于持仓建议。
- S5 未通过，不进入任何真实交易动作。
- S6 未通过，不发布自动生成的新策略版本。
- 每个 Checkpoint 必须保留测试命令、真实交付物、数据库记录、hash 和失败样本。

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 策略库先行过度建设 | 延迟真实闭环 | 首批只做身份、版本、生命周期、依赖和模板 |
| WorkBuddy 结果直接成为正式候选/研究 | 污染权威数据 | ExternalObservation + Admission + 交付物校验 |
| 策略自动漂移 | 不可复现、过拟合 | ChangeProposal + 样本外验证 + 人工审批 |
| 多策略重复研究 | 成本和状态冲突 | 合并 ResearchCase，保留多来源归因 |
| 目录承担业务语义 | 策略变更导致路径失控 | 目录只表达阶段/生命周期，策略写元数据 |
| 观察与研究档案混合 | 历史被当前状态覆盖 | ResearchCase 永久档案，WatchlistEntry 当前状态 |

## Explicit non-goals for the first vertical slice

- 自动市场状态识别与策略切换；
- 全量历史回测平台；
- 自动调参、自动晋级或自动淘汰；
- 多账户和自动交易；
- 为每条策略建立独立共享目录；
- 在首个 ETF 闭环前扩展到多资产类别。
