# 投研系统首批两条候选策略最小审核、登记与执行计划 v1.0

> 治理状态：`ACTIVE`
> 制定日期：2026-08-26
> 计划定位：Stage 4D Gate 3 的前置垂直切片；用户已于 2026-08-26 明确授权实施
> 合同依据：`invest-infra-strategy-source-to-automation-workflow.md`

## 1. 目标

当前 Gate 3 的真实阻塞不是缺少完整策略平台，而是投研系统尚未把既有两条候选策略工程化交付纳入正式审核、版本发布和执行链路。此前 WorkBuddy 收到的 `real-chain-etf-candidate-v1` 只有标识，与现有两条策略交付没有正式绑定。

本计划只解决这一个问题：将已经提取并完成工程化预检的“板块强度”和“通达信个股筛选”两条候选策略登记为待审 Draft，分别完成 RAA/CIA 审核和版本发布，再人工执行一次两阶段候选发现并接回 Stage 4D。

```text
恢复并核验两篇头条原文
→ 两条 StrategyDraft 入库并固化既有工程化 artifact
→ RAA 通过只读 API 分别审核
→ AgentOA 分别回传 audit.json
→ ARC 通过受控 CLI 摄取两份 StrategyAudit
→ CIA 分别批准并发布、激活两个 StrategyVersion
→ ARC 通过 AgentOA 人工执行板块阶段
→ 校验板块 StageResult
→ ARC 人工执行个股阶段并绑定上游结果 hash
→ WorkBuddy 生成 Candidate 2.0.0
→ CandidateAdmission
→ Evidence → ResearchCase → ResearchRun/Result → Timeline
```

## 2. 权威边界

- 投研系统保存待审策略、正式审计记录和正式策略版本，是审核状态、策略身份、版本和当前激活状态的唯一权威源。
- 用户/CIA 决定策略业务语义、适用范围、风险和是否批准；ARC 不代替投研决策。
- WorkBuddy 可以评估数据能力、形成策略工程化材料并执行策略，但不能批准、创建或激活正式版本。
- 首版由 RAA 审计作为策略发布硬门禁；RAA 只读待审策略，不直接修改策略状态。
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
- 板块阶段和个股阶段各一次人工 AgentOA WorkBuddy 业务任务；
- 一份同时追溯两个正式策略版本和上游 StageResult 的 Candidate 2.0.0 交付；
- 与现有 Candidate Intake、Admission、Evidence 和 Research 链路的真实联调。

### 3.2 明确不做

- 独立 `StrategySourceDocument` 数据库聚合；
- 独立 `StrategyCapabilityAssessment` 数据库聚合；
- `StrategyProposalRevision` 状态机和提案管理平台；
- `StrategyAutomationDefinition`、周期调度和自动任务发布；
- RAA 写 API、审批 UI 和通用权限平台；
- 多策略编排、通用 DAG、图形化流程设计器；
- 自动审批、自动激活、自动淘汰、自动调参或复杂回测；
- `suspended/retired` 等当前无真实用例的生命周期状态；
- 修改或重置现有两条已 `rejected` Observation；
- 恢复 legacy 1.1.x 三件套或 JiuwenSwarm 路径。

上述能力保留在合同蓝图中，只有出现当前固定两阶段范围之外的新真实用例并获得独立授权后才实施。

首批两条策略按固定业务顺序人工执行，不为这一条固定链路建设 `CandidateSelectionWorkflowVersion` 或通用编排器。

### 3.3 已确认输入

| 阶段 | 来源 | Source ID | 既有策略 artifact | 当前状态 |
|---|---|---|---|---|
| 板块强度 | `https://m.toutiao.com/is/fslPVWFTKSY/` | `source-sector-strength-toutiao-20260815` | `strategy-engineering-sector-strength-20260815-0001` | validation passed / needs_review |
| 通达信个股筛选 | `https://m.toutiao.com/is/QwmHBSMbhGQ/` | `source-tdx-native-tools-toutiao-20260815` | `strategy-engineering-tdx-native-tools-20260815-0001` | validation passed / needs_review |

已归档 `source-document.json` 保存标题、URL和 `content_sha256`，但没有完整原文正文。Slice 0 必须先从既有归档找回或重新提取正文：若重新提取内容与原 hash 不同，必须并列保留旧hash与新快照并交由CIA确认，禁止把变化后的网页静默解释为原始内容。

## 4. 最小设计

### 4.1 不可变策略 artifact

策略业务内容保存在不可变 artifact 中，不复制成大量数据库字段。

首版 `strategy.json` 只要求：

| 字段 | 用途 |
|---|---|
| `schema_version` | 解释合同版本 |
| `strategy_key` | 稳定策略身份 |
| `version` | 不可变业务版本 |
| `name` | 人工识别 |
| `market_scope` | 限定板块或沪深股票市场及标的范围 |
| `as_of_policy` | 数据截止时间规则，防止未来数据泄漏 |
| `rules` | CIA 确认的筛选与解释规则 |
| `required_data` | WorkBuddy 执行所需数据及口径 |
| `candidate_contract` | Candidate 2.0.0 输出要求 |
| `failure_conditions` | 数据不足或规则不可执行时的停止条件 |
| `source_refs` | 原始业务材料引用与 hash |

业务扩展字段默认允许；只有身份、版本、完整性和安全解释失败才阻断登记。

### 4.2 最小 StrategyDraft

策略在审核前先入库为 `StrategyDraft`，不得直接创建 `StrategyVersion`：

| 字段 | 约束 |
|---|---|
| `draft_id` | 系统稳定身份 |
| `strategy_key` | 待发布策略身份 |
| `proposed_version` | 目标版本，不代表已发布 |
| `artifact_ref` | 不可变 `strategy.json` 引用 |
| `artifact_hash` | SHA-256，入库后不可修改 |
| `source_refs` | 原始业务材料引用与 hash |
| `validation_result` | 系统确定性校验结果 |
| `created_at` | 系统登记时间 |

RAA 通过只读接口读取完整待审内容：

```http
GET /api/v1/strategy-drafts/{draft_id}
```

接口返回 `strategy.json` 内容、source refs、artifact hash、validation 结果和已有审计摘要；不暴露宿主机绝对路径或凭证。

### 4.3 最小 StrategyAudit 记录

RAA 通过 AgentOA 交付 `audit.json`。AgentOA 是传输通道，ARC 使用受控 CLI 完成校验和正式摄取。

审计记录最少保存：

| 字段 | 约束 |
|---|---|
| `audit_id` | 系统稳定身份 |
| `draft_id` | 绑定待审策略 |
| `artifact_hash` | 必须与当前 Draft 完全一致 |
| `agentoa_task_id` | 审计任务追溯 |
| `auditor` | 必须为授权 RAA 身份 |
| `verdict` | `pass / changes_required / reject` |
| `findings` | 结构化审计发现 |
| `limitations` | 审计限制 |
| `report_ref/report_hash` | 原始审计报告及 SHA-256 |
| `audited_at` | 审计时间 |

重复报告按 `(draft_id, artifact_hash, agentoa_task_id)` 幂等。Draft 内容或 hash 变化后，旧审计不能用于发布新版本。

### 4.4 最小 StrategyVersion 聚合

数据库只新增一个正式聚合，保存：

| 字段 | 约束 |
|---|---|
| `strategy_id` | 系统稳定身份 |
| `strategy_key` | 每条策略稳定且唯一 |
| `version` | 与 `strategy_key` 联合唯一 |
| `artifact_ref` | 不可变策略 JSON 引用 |
| `artifact_hash` | SHA-256，登记后不可修改 |
| `source_hashes` | 原始业务材料 hash 引用 |
| `decision_ref` | CIA 决定证据引用 |
| `audit_id` | 必须引用当前 Draft 的有效 `pass` 审计 |
| `approved_at` | CIA 批准时间 |
| `activated_at` | 人工激活时间；未激活为空 |
| `created_at` | 系统登记时间 |

不在首版建立通用状态机。可执行条件只有：

```text
artifact hash 有效
AND audit_id 指向当前 hash 的 pass 审计
AND decision_ref 有效
AND approved_at 非空
AND activated_at 非空
```

版本发布后不可修改。业务语义变化时创建新版本，不覆盖旧版本。

### 4.5 最小接口与命令

策略模块只暴露四个业务能力：

```text
register_draft(...)
publish_approved_version(draft_id, audit_id, decision_ref)
activate_version(strategy_id, version)
get_active_version(strategy_key)
```

RAA 只读 API 位于 Draft 查询接缝；首版不提供 RAA 写 API。ARC 使用受控管理 CLI 摄取 `audit.json`，CLI 调用同一领域校验能力，不复制规则。artifact 校验、hash、审计有效性、唯一性、不可变性和激活约束隐藏在模块内部。

## 5. 实施切片

### Slice 0：恢复原文并登记两条 StrategyDraft

**目标：** 恢复两篇源文正文，核对既有工程化交付，将两条待审策略正式入库，并为 RAA 提供唯一只读审核入口。

**工作内容：**

- 找回既有提取正文；确实缺失时重新提取两篇头条文章并生成新快照和hash；
- 对照原文、现有能力评估、`strategy.json`、`strategy.md` 和 `validation.json`；
- 复算现有manifest和全部artifact hash，不重新发明策略内容；
- 将两套既有工程化交付分别登记为不可变 `StrategyDraft`；
- 提供 `GET /api/v1/strategy-drafts/{draft_id}` 只读接口。

能力评估和工程化提案仍以不可变 artifact 保存，不分别建设数据库模型。

**验收标准：**

- [x] 两篇原文正文可读取，旧hash与当前快照关系明确；
- [x] 两条策略的 key、版本、市场范围、规则和数据口径分别明确；
- [x] manifest与现有策略交付hash复算一致；
- [x] 两条Draft入库后内容和hash不可原地修改；
- [x] RAA能通过API分别读取完整策略、来源、能力评估和validation结果。

**验证：** JSON schema/fixture、hash、repository 和只读 API tests；RAA 身份实际读回。

**依赖：** 无。

**预计规模：** 拆成两个 M 任务，每个不超过 5 个文件：Draft 领域/存储；只读 API。

### Slice 1：分别审计并发布两个 StrategyVersion

**目标：** 通过AgentOA分别完成两条策略的RAA审计，经正式摄取和CIA逐条批准后发布、激活两个版本。

**工作内容：**

- ARC通过AgentOA分别发布绑定`draft_id + artifact_hash`的审计任务；
- RAA通过只读API逐条审核并分别交付`audit.json`；
- ARC使用受控CLI分别校验、摄取两份不可变`StrategyAudit`；
- CIA对两条通过审计的当前Draft分别作出决定；
- 新增最小 `StrategyVersion`，实现发布、人工激活和按 `strategy_key` 查询；
- 校验 Draft hash、有效审计、CIA 决定、版本唯一性和不可变性；
- 提供最小只读查询能力，供 ARC 验收和任务发布读取。

**验收标准：**

- [ ] AgentOA 完成不等于审计入库成功；
- [ ] hash 不符、任务身份不符、非 RAA 提交或非 pass 审计均不能发布版本；
- [ ] 未经 CIA 批准或未激活版本不能作为执行依据；
- [ ] 每条key/version重复登记幂等，冲突内容失败；
- [ ] 已登记版本不能原地修改；
- [ ] 查询返回正式 artifact 引用和 hash，而不是裸字符串。

**验证：** audit ingestion、domain、repository、migration 和 focused CLI/query tests；AgentOA、审计记录、CIA决定和版本四方读回。

**依赖：** Slice 0。

**预计规模：** 拆成三个 M 任务，每个不超过 5 个文件：Audit 摄取；Version 领域/存储；发布/查询入口。

### Slice 2：两阶段真实执行并回接 Stage 4D

**目标：** 用两个正式策略版本按固定顺序完成一次真实候选发现，解除Gate 3输入阻塞。

**工作内容：**

- ARC查询两条策略的当前激活版本及artifact；
- 通过AgentOA人工发布板块强度任务，绑定其`strategy_id + strategy_version + artifact_hash`；
- 校验并保存板块StageResult、run id和artifact hash；
- 仅在上游结果合法时发布个股筛选任务，并显式绑定板块StageResult引用；
- WorkBuddy使用真实业务数据生成Candidate 2.0.0，并同时保留两个策略版本归因；
- 投研系统校验、不可变归档、导入并执行 CandidateAdmission；
- 准入后继续 Evidence → ResearchCase → ResearchRun/Result → Timeline；
- 固化任务 ID、版本、hash、时间戳、状态和读回证据。

**验收标准：**

- [ ] 两个WorkBuddy任务的执行内容分别与登记artifact hash一致；
- [ ] 个股任务输入可追溯板块run id和StageResult hash；
- [ ] Candidate携带末阶段正式策略版本，并能追溯上游板块策略版本；
- [ ] Candidate 内容满足当前 Admission 合同，或形成可解释的合法空结果；
- [ ] 运行、交付、摄取和业务结果状态分别记录；
- [ ] 旧 `rejected` Observation 未修改或重置；
- [ ] Gate 3 正常主链路形成可复验证据。

**验证：** AgentOA 回报、artifact hash、数据库、API/Web Timeline 四方读回；Stage 4D focused 和全量回归。

**依赖：** Slice 1。

**预计规模：** M；以联调和验收记录为主，不扩展自动化平台。

## 6. 依赖与验收 Gate

```text
Slice 0 原文恢复与两条 Draft 入库
  ↓ Gate A：RAA 可通过 API 审核两条当前 Draft
Slice 1 分别审计、CIA批准、两个 Version 发布激活
  ↓ Gate B：两份审计有效且系统可查询两个激活版本
Slice 2 两阶段 WorkBuddy 真实执行与 Stage 4D 回接
  ↓ Gate C：首批候选策略 MVP 完成
```

### Gate A：策略可审核

- 两篇原文快照、既有内容hash及当前提取差异可解释；
- 两条策略的业务规则、数据口径、失败条件和输出要求明确；
- 两个StrategyDraft、strategy artifact和source refs的引用与hash可复算；
- RAA可通过投研系统API读取两条完整待审内容；
- 数据不可得时明确 `blocked`，不猜测或补造。

### Gate B：策略可引用

- 两个StrategyVersion均不可变且已人工激活；
- 两份StrategyAudit分别绑定当前Draft hash、AgentOA任务和RAA身份，verdict均为`pass`；
- CIA分别作出有效决定；
- 投研系统能按两个`strategy_key`分别返回唯一激活版本及artifact hash；
- 未批准、未激活或冲突版本均不能被任务引用。

### Gate C：真实链路通过

- WorkBuddy按两个正式策略版本完成一次固定两阶段真实执行；
- 下游任务显式引用已校验上游StageResult，不依赖文件名或Markdown猜测；
- Candidate 2.0.0可追溯两个策略版本、两个AgentOA任务和原始artifact；
- Stage 4D Admission 及 Research 链路形成证据，或产生符合合同的合法空结果；
- focused/full tests、迁移检查、OpenAPI drift、Web typecheck/build 和 `git diff --check` 通过。

## 7. 兼容与延期

- 现有 YAML/custom strategy loader、策略 archive 和 validator 保持原用途并优先复用；不自动升级为正式版本。
- 历史 `strategy_id`、旧提案和旧报告继续视为 `legacy_unapproved/test_only/non_authoritative`。
- 数据库迁移只新增，不改写历史 Observation、Artifact、Run 或 Candidate。
- 出现第二个策略版本、第二种执行配置或周期调度需求后，再评估：
  - 独立 SourceDocument/CapabilityAssessment/ProposalRevision 聚合；
  - StrategyAutomationDefinition；
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
| 归档成功被误认为正式版本 | 只有审计通过、CIA批准并激活的 StrategyVersion 可执行 |
| 两阶段关系固化成脆弱脚本 | 下游任务显式引用上游StageResult身份和hash，但不建设通用编排器 |
| 合同继续膨胀 | 新字段必须对应当前安全、身份或业务操作需求 |
| 过早删除旧入口 | 首版只新增最小路径，不删除现有 loader/archive |

## 9. 实施规则

- 本文已获用户授权并登记为 `ACTIVE`，作为 Stage 4D P0 的前置垂直切片，不新增第三条并行主线；
- 三个 Slice 分别授权、实现和验收；
- Slice 0–1 代码由 OpenCode 增量实现，Codex 独立复核，ARC 最终验收；
- CIA/RAA 决定由对应角色产生，ARC 只负责技术登记和验证；
- 提交、推送、部署均需单独明确授权。

## 10. 激活前待确认

1. 以已归档的板块强度和通达信个股筛选两套工程化交付作为首批Draft输入；
2. 缺失原文重新提取时，内容变化必须保留新旧快照并由CIA确认；
3. RAA通过投研系统只读API逐条审核，报告经AgentOA回传并由ARC CLI摄取；
4. StrategyVersion首版使用管理CLI发布/激活，并提供只读查询；
5. 两阶段按固定顺序人工执行，不新增通用工作流编排对象；
6. 本计划作为Stage 4D前置切片，不新增第三条活动主线。
