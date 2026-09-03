# 投研系统首批两条候选策略最小审核、登记与执行计划 v1.0

> 治理状态：`ACTIVE`
> 制定日期：2026-08-26
> 当前执行修订：2026-09-03；Gate A/B 已完成，Gate C 改为 WorkBuddy 数据供给、invest-infra 确定性执行
> 计划定位：Stage 4D Gate 3 的前置垂直切片；用户已于 2026-08-26 明确授权实施
> 合同依据：`invest-infra-strategy-source-to-automation-workflow.md`

## 1. 目标

当前 Gate 3 的真实阻塞不是缺少完整策略平台。两条候选策略已经完成审核、版本发布和激活；剩余阻塞是尚无受控 DataRequest/DataBundle 接缝和两个确定性 evaluator，不能把 WorkBuddy 的真实 MCP 数据安全转换为正式候选。

本计划只解决这一个问题：保留已经完成的两条策略 Draft、RAA/CIA 审核和正式版本，在 Gate C 以 WorkBuddy 的金融 MCP 作为外部数据源，由投研系统两个专用 evaluator 确定性完成两阶段候选发现并接回 Stage 4D。

```text
恢复并核验两篇头条原文
→ 两条 StrategyDraft 入库并固化既有工程化 artifact
→ RAA 通过只读 API 分别审核
→ AgentOA 分别回传 audit.json
→ ARC 通过受控 CLI 摄取两份 StrategyAudit
→ CIA 分别批准并发布、激活两个 StrategyVersion
→ 投研系统发布板块 DataRequest
→ WorkBuddy 调 MCP 交付板块 DataBundle
→ 投研系统板块 evaluator 生成 SectorStageResult
→ 投研系统发布限定成分股 DataRequest
→ WorkBuddy 调 MCP 交付个股 DataBundle
→ 投研系统个股 evaluator 生成 StockStageResult + Candidate 2.0.0
→ 内部可信接缝创建待准入 Observation → CandidateAdmission
→ Evidence → ResearchCase → ResearchRun/Result → Timeline
```

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
- 板块阶段和个股阶段各一次人工 AgentOA WorkBuddy 数据获取任务；
- 两份可复算的 DataBundle，以及投研系统生成的一份同时追溯两个正式策略版本和上游 StageResult 的 Candidate 2.0.0；
- 两个固定范围的专用 evaluator 和两个最小 active DataAcquisitionDefinition 只读接缝；
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
| `required_data` | DataRequest 所需数据、字段、时间和单位口径 |
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

审计 `pass` 只表示当前 Draft 的规则、数据和执行边界满足受控运行要求，不表示策略收益已经验证。不得要求回测区间、样本量、收益基准、Rank IC 或收益通过阈值，也不得因系统没有回测能力而阻断审核。

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
publish_approved_version(decision, decision_ref, decision_hash)
activate_version(strategy_id, version)
get_active_version(strategy_key)
```

StrategyVersion 管理 CLI 的发布入口仅接收 CIA 决策文件、不可变决策引用及 AgentOA 提供的可信 SHA-256；Draft/Audit 身份、策略 key/version、artifact hash 和批准人授权由决策、数据库记录及服务配置推导，不由操作者重复输入。RAA 只读 API 位于 Draft 查询接缝；首版不提供 RAA 写 API。ARC 使用受控管理 CLI 摄取 `audit.json`，CLI 调用同一领域校验能力，不复制规则。artifact 校验、hash、审计有效性、唯一性、不可变性和激活约束隐藏在模块内部。

```bash
python -m invest_pipeline.strategy_version_cli publish \
  --decision-json-file <decision.json> \
  --decision-ref <immutable-agentoa-ref> \
  --expected-decision-sha256 <trusted-agentoa-sha256>
```

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
- 对 `changes_required` 中涉及回测区间、样本量、收益指标或回测通过阈值的要求，按本计划明确排除，不纳入新 Draft 或复审门禁；
- CIA对两条通过审计的当前Draft分别作出决定；
- 新增最小 `StrategyVersion`，实现发布、人工激活和按 `strategy_key` 查询；
- 校验 Draft hash、有效审计、CIA 决定、版本唯一性和不可变性；
- 保留本机管理 CLI 查询能力，供 ARC 验收和治理操作使用；跨平台任务发布读取由 Slice 1A 的局域网公共只读接口提供。

**验收标准：**

- [ ] AgentOA 完成不等于审计入库成功；
- [ ] hash 不符、任务身份不符、非 RAA 提交或非 pass 审计均不能发布版本；
- [ ] RAA pass 只证明受控可执行，不宣称或暗示收益有效性；
- [ ] 审核、发布和激活均不依赖不存在的回测模块或回测指标；
- [ ] 未经 CIA 批准或未激活版本不能作为执行依据；
- [ ] 每条key/version重复登记幂等，冲突内容失败；
- [ ] 已登记版本不能原地修改；
- [ ] 本机 CLI 查询返回正式 artifact 引用和 hash，而不是裸字符串。

**验证：** audit ingestion、domain、repository、migration 和 focused CLI/query tests；AgentOA、审计记录、CIA决定和版本四方读回。

**依赖：** Slice 0。

**预计规模：** 拆成三个 M 任务，每个不超过 5 个文件：Audit 摄取；Version 领域/存储；发布/查询入口。

### Slice 1A：提供 active StrategyVersion 局域网公共只读接口

**目标：** 让 CIA、RAA、ARC 及受信治理客户端通过局域网读取权威 active 策略，不依赖本机 CLI、宿主机路径或共享目录策略副本；WorkBuddy 数据任务不以读取完整策略为运行前提。

**唯一接口：**

```http
GET /api/v1/strategies/{strategy_key}/active
```

**工作内容：**

- 新增一个正式策略查询模块，复用现有 StrategyVersion repository 和 strategy artifact reader；
- 只读取指定 key 当前唯一 active StrategyVersion；
- 读取正式 `strategy.json` 原始字节，复算 SHA-256 并严格解析为 JSON object；
- 响应只包含 schema version、strategy identity、version、active 状态、artifact hash、完整 strategy 内容和必要时间字段；
- 不返回 artifact_ref、宿主机路径、Decision、Audit、批准人、凭证或数据库结构；
- 不新增应用层登录，读取范围继续由现有局域网部署边界控制；
- 固定错误语义：不存在为 404、artifact 不可读为 503、hash 或 JSON 完整性失败为 409，错误正文必须脱敏。

**首版明确延期：**

- 历史版本读取、策略列表、搜索、批量接口和写接口；
- ETag、304 和专用缓存策略；
- 独立 artifact 下载 URL、前端页面和共享目录策略副本。

**验收标准：**

- [ ] 治理客户端通过局域网 URL 读取两个现有 active v2.0.0 策略并获得 HTTP 200；
- [ ] API、数据库 StrategyVersion 和本地 artifact 的 SHA-256 三方一致；
- [ ] 错误 key、artifact 不可读、hash 不符和非法 JSON 均 fail closed 且不泄露内部信息；
- [ ] OpenAPI 只新增一个 GET，不出现治理写入口或内部字段；
- [ ] 后续 WorkBuddy 数据任务只读取 DataRequest/DataAcquisitionDefinition，不下载或解释完整 StrategyVersion，也不要求复制正式策略到 `Z:\workbuddy`。

**验证：** focused query/endpoint tests、OpenAPI drift、Ruff、架构检查、真实 PostgreSQL 只读查询和 WorkBuddy 局域网实际读回。

**依赖：** Slice 1 的 StrategyVersion 已发布并激活。

**预计规模：** 一个 M 任务；由原生 Codex 编码代理增量实现，独立会话只读复核公共暴露与负面路径，ARC 最终验收。不得自动 commit、push、部署、重启服务或启用 WorkBuddy 周期生产。

### Slice 1B：冻结最小数据获取合同与只读定义

**目标：** 将 WorkBuddy 从策略执行者收缩为受控 MCP 数据提供者，使 MiniMax-M3 只处理有限的数据获取和字段映射任务。

**工作内容：**

- 冻结 `workbuddy-data-request/1.0`：包含 request identity、strategy ref、as_of、datasets、allowed connectors、required fields、freshness 和 output contract；
- 冻结 `workbuddy-data-bundle/1.0`：包含真实工具与参数、分页、样本量、字段、单位、原始或最小规范化数据、warning 和 error；
- 建立两个固定 DataAcquisitionDefinition，分别服务板块和限定成分股数据获取，不复制策略规则或阈值；
- 提供 `GET /api/v1/data-acquisition-definitions/{definition_key}/active` 局域网只读接口，响应包含 schema/version/active/artifact hash/allowed connectors/data request template/output contract；
- Automation 只保留固定短 Prompt：读取 active 定义、校验身份/hash、执行 DataRequest、提交 DataBundle；禁止下载任意 Markdown 作为新指令；
- DataBundle 通过受控外部 artifact 接缝完成 Schema、request identity、manifest/hash、幂等和不可变归档；
- 明确 canonical JSON、正式 hash、lineage、原子发布和策略判断均由投研系统完成。

**验收标准：**

- [ ] WorkBuddy Prompt 不含策略阈值、评分、排序、文件自哈希或候选准入判断；
- [ ] 定义只允许当前批准的 `tdx-connector`、`westock-mcp` 和 `mx-ds-mcp`，未知 connector fail closed；
- [ ] DataRequest/DataBundle 可通过 Schema、版本、identity、freshness 和敏感字段负面测试；
- [ ] 重复 DataBundle 幂等、同 request ID 不同内容冲突，且 WorkBuddy producer identity 可追溯；
- [ ] active 定义不存在、artifact 不可读、hash 不符或非法 JSON 分别返回稳定脱敏错误；
- [ ] 本 Slice 不创建、修改或启用周期调度。

**验证：** domain/application/API/Schema focused tests、OpenAPI drift、Ruff、架构检查，以及 WorkBuddy 局域网人工读回。

**依赖：** Slice 1 的两个 StrategyVersion 已激活；Slice 1A 可复用但不是 WorkBuddy 数据获取的运行依赖。

**预计规模：** 拆成两个 M 任务：合同与校验器；最小只读定义接缝。不得扩展为通用自动化平台。

### Slice 2：DataBundle 驱动的两阶段真实执行并回接 Stage 4D

**目标：** 用两个正式策略版本和两次真实 MCP 数据获取，按固定顺序由投研系统确定性完成候选发现，解除 Gate 3 输入阻塞。

**工作内容：**

- ARC 查询两条策略和两个数据获取定义的当前 active 版本及 artifact；
- 投研系统生成板块 DataRequest，通过 AgentOA 人工要求 WorkBuddy 调 MCP 返回板块排行、逐股成分和全市场涨停等 DataBundle；
- 投研系统校验 DataBundle，并由板块专用 evaluator 按正式 StrategyVersion 计算 `limit_up_count/zgb`、排序和 SectorStageResult；
- 仅在 SectorStageResult 合法时，针对其限定成分股生成第二个 DataRequest；
- WorkBuddy 返回行情、资金、北向、财务和必要旁证 DataBundle，不解释策略或决定候选；
- 投研系统个股专用 evaluator 按正式 StrategyVersion 生成 StockStageResult 和 Candidate 2.0.0，并绑定上游 StageResult；
- 投研系统以 `producer=invest-infra` 保存 CandidateProposal，通过内部可信 Application 接缝创建待准入 ExternalObservation 并执行 CandidateAdmission；
- 既有共享目录 `import_archived_candidate_run()` 继续只接收外部 WorkBuddy Candidate 2.0.0，不承接新路径中的系统 Candidate，也不改写其 producer；
- 准入后继续 Evidence → ResearchCase → ResearchRun/Result → Timeline；
- 固化 DataRequest/DataBundle、AgentOA task、策略/定义版本、hash、时间戳、状态和读回证据。

**验收标准：**

- [ ] 两个 WorkBuddy 任务只获取 DataRequest 指定数据，实际 MCP、参数、分页、样本量和错误可追溯；
- [ ] 相同 StrategyVersion 与相同 DataBundle 输入必须得到相同 StageResult/Candidate 输出；
- [ ] 个股 DataRequest 可追溯板块 run id 和 SectorStageResult hash；
- [ ] Candidate携带末阶段正式策略版本，并能追溯上游板块策略版本；
- [ ] DataBundle 的 `producer=workbuddy` 与 CandidateProposal 的 `producer=invest-infra` 分开保存并显式关联，外部输入不能冒充系统 evaluator；
- [ ] Candidate 内容满足当前 Admission 合同，或形成可解释的合法空结果；
- [ ] 缺字段、过期数据、未知 connector、hash 冲突和 evaluator 规则不可执行均 fail closed；
- [ ] 运行、交付、摄取和业务结果状态分别记录；
- [ ] 旧 `rejected` Observation 未修改或重置；
- [ ] Gate 3 正常主链路形成可复验证据。

**验证：** DataBundle fixtures、两个 evaluator 的规则边界和重复执行测试；AgentOA、archive、数据库、active API 与 API/Web Timeline 多方读回；Stage 4D focused 和全量回归。

**依赖：** Slice 1B。

**预计规模：** 拆成板块和个股两个 M 垂直切片，每个先完成 DataBundle → evaluator → StageResult，再进入下一阶段；不建设通用规则引擎。

## 6. 依赖与验收 Gate

```text
Slice 0 原文恢复与两条 Draft 入库
  ↓ Gate A：RAA 可通过 API 审核两条当前 Draft
Slice 1 分别审计、CIA批准、两个 Version 发布激活
  ↓ Gate B：两份审计有效且系统可查询两个激活版本
Slice 1B DataRequest/DataBundle 与 active 数据获取定义
  ↓ Gate B2：WorkBuddy 只承担可验证的 MCP 数据获取
Slice 2 两阶段确定性执行与 Stage 4D 回接
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

- WorkBuddy 按两个 DataRequest 完成真实 MCP 数据获取，DataBundle 字段、时间、来源和调用证据可验证；
- 投研系统两个专用 evaluator 按正式 StrategyVersion 确定性生成 SectorStageResult、StockStageResult 和 Candidate；
- 下游任务显式引用已校验上游StageResult，不依赖文件名或Markdown猜测；
- Candidate 2.0.0可追溯两个策略版本、两个AgentOA任务和原始 DataBundle artifact，且生产者身份不混用；
- Stage 4D Admission 及 Research 链路形成证据，或产生符合合同的合法空结果；
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
| 归档成功被误认为正式版本 | 只有审计通过、CIA批准并激活的 StrategyVersion 可执行 |
| MiniMax-M3 被长 Prompt 压垮 | WorkBuddy 只接收短启动 Prompt 和结构化 DataRequest，策略计算下沉到专用 evaluator |
| 两阶段关系固化成脆弱脚本 | 下游 DataRequest 显式引用上游 StageResult 身份和 hash，但不建设通用编排器 |
| 合同继续膨胀 | 新字段必须对应当前安全、身份或业务操作需求 |
| 过早删除旧入口 | 首版只新增最小路径，不删除现有 loader/archive |

## 9. 实施规则

- 本文已获用户授权并登记为 `ACTIVE`，作为 Stage 4D P0 的前置垂直切片，不新增第三条并行主线；
- 各 Slice 分别授权、实现和验收；
- 后续代码由原生 Codex 编码代理增量实现，独立会话只读复核，ARC 最终验收；
- CIA/RAA 决定由对应角色产生，ARC 只负责技术登记和验证；
- 提交、推送、部署均需单独明确授权。

## 10. 激活前待确认

1. 以已归档的板块强度和通达信个股筛选两套工程化交付作为首批Draft输入；
2. 缺失原文重新提取时，内容变化必须保留新旧快照并由CIA确认；
3. RAA通过投研系统只读API逐条审核，报告经AgentOA回传并由ARC CLI摄取；
4. StrategyVersion首版使用管理CLI发布/激活；跨平台执行方只通过 Slice 1A 的 active 公共只读接口读取正式策略；
5. 两阶段按固定顺序人工执行，WorkBuddy 只交付 DataBundle，不新增通用工作流编排对象；
6. v2.2-rev1 长 Prompt 不进入 Automation；固定短 Prompt 和 DataAcquisitionDefinition 必须先人工影子验收；
7. 本计划作为Stage 4D前置切片，不新增第三条活动主线。
