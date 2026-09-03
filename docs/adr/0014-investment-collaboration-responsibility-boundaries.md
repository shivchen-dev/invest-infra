# ADR-0014：投研协作职责与权威边界

- 状态：Accepted
- 日期：2026-08-15
- 最近修订：2026-09-03（候选生产改为 WorkBuddy 数据供给、invest-infra 确定性执行）
- 适用范围：Stage 4D–4G、策略库、WorkBuddy 外部工作流、研究、观察、组合与复盘
- 决策参与者：CIA、ARC、RAA、Ops、WorkBuddy、invest-infra

## 1. 背景

投研系统将逐步形成以下闭环：

```text
策略制定
→ 候选发现
→ 正式准入
→ 深度研究
→ 长期观察
→ 投资建议
→ 组合与执行
→ 后验评价
→ 策略版本演进
```

该闭环同时包含方向决策、技术建设、外部智能体执行、确定性治理、独立审计和运行保障。若不明确权威边界，容易出现以下问题：

- WorkBuddy 同时提出、执行、评价并批准自己的策略；
- ARC 因实现系统而越权形成投资判断；
- CIA 的方向决策无法落成可追溯策略版本；
- 投研系统和外部智能体形成两套策略、数据或研究事实源；
- 审计与运行职责混入业务结论；
- 外部智能体直接写数据库、激活策略或产生交易动作。

本 ADR 冻结各参与方的职责、决定权、接口和禁止事项。

## 2. 决策

采用以下核心分工：

```text
CIA          = 投研方向、策略提案、正式审批与投资判断
ARC          = 投研系统架构、开发、集成与技术验证
WorkBuddy    = 外部 MCP 数据获取、研究、反证与观察执行
invest-infra = 数据、流程、策略版本、正式结果和审计记录权威
RAA          = 独立审计与验证
Ops          = 运行、调度、监控、备份与故障恢复
```

任何参与方不得同时取得“提出、执行、评价、批准”四项完整权力。

## 3. 各方职责

### 3.1 CIA：投研方向与正式决策

CIA 负责：

- 确定投研方向、市场范围、研究主题和优先级；
- 形成和修订 `StrategyProposal`，明确策略目标、规则、阈值、适用场景、评价窗口、风险偏好和 STOP 条件；
- 审核 `StrategyProposal`、`StrategyChangeProposal`；
- 批准、暂停、恢复和退役正式 `StrategyVersion`；
- 审阅正式候选、ResearchResult、Watchlist 和 Investment Proposal；
- 作出投资判断或明确不行动。

CIA 不负责：

- 编写或维护业务代码；
- 直接修改数据库、文件归档或任务状态；
- 以口头结论覆盖正式策略版本、Evidence 或审计记录；
- 绕过风控、审批或数据准入门禁。

### 3.2 ARC：技术建设与技术解释

ARC 负责：

- 设计并实现领域模型、数据层、工作流、接口和可视化；
- 建设策略库、版本、任务、交付物摄取、准入和后验模块；
- 接入 WorkBuddy、金融 MCP、共享目录及受控 HTTP/MCP 接口；
- 将已批准 StrategyVersion 映射为版本化 `DataRequest`，实现确定性 evaluator、Schema、hash、lineage 和原子发布；
- 编写测试、迁移、技术文档和可复现验收工具；
- 解释系统如何工作、数据如何流转和故障发生在哪里；
- 独立检查编码代理输出、测试结果和工作树。

ARC 不负责：

- 判断某只证券是否值得投资；
- 替 CIA 批准策略、候选、研究结论或持仓建议；
- 替 RAA 出具独立审计结论；
- 替 Ops 承担长期运维、巡检和生产故障处置；
- 因技术实现便利而改变投研业务权威。

### 3.3 WorkBuddy：外部数据与研究执行团队

WorkBuddy 负责：

- 利用已安装 Skills、金融 MCP、Connector、通达信和公开信息获取多源数据；
- 执行数据能力盘点，并按投研系统发布的版本化 `DataRequest` 生成 `DataBundle`；
- 记录真实工具、参数、数据时间、分页、样本量、字段、单位、warning 和 error；
- 对已准入候选开展深度研究、风险反证和证据交叉验证；
- 执行长期观察、事件复评和投资假设检查；
- 生成结构化交付物与人类可读报告；
- 基于多次正式运行结果提供数据缺口和研究观察，供 CIA 判断是否形成 `StrategyChangeProposal`。

WorkBuddy 不负责：

- 将自己的输出直接标记为正式准入、approved 或 active；
- 自行解释或改写 StrategyVersion、决定候选资格、评分、排序或正式 StageResult；
- 承担 canonical JSON、业务 hash、原子发布和正式 lineage 的最终校验；
- 修改正式 StrategyVersion、ResearchResult、Watchlist 或组合账本；
- 直接写 PostgreSQL、执行任意 SQL 或绕过 Artifact Bridge；
- 决定正式持仓、下单或改变风控约束；
- 将自检、运行状态或报告生成视为投研系统验收成功；
- 成为自己策略与研究结果的唯一评价者。

### 3.4 invest-infra：正式业务权威

投研系统负责：

- 保存 Strategy、StrategyVersion、DataAcquisitionMatrixVersion 和生命周期；
- 保存 active DataAcquisitionDefinition，生成窄 `DataRequest`，校验和摄取 `DataBundle`；
- 使用两个首版专用 evaluator 确定性计算 SectorStageResult、StockStageResult 和 CandidateProposal；
- 发布受控的 strategy/candidate/research/observation 任务；
- 管理 ExternalObservation、Admission、Evidence、ResearchResult 和 Watchlist；
- 校验交付物 Schema、身份、来源、时间、单位、定义、hash 和版本；
- 执行确定性数据质量、回测、样本外、风险和后验评价；
- 管理 Champion/Challenger、审批记录和正式激活状态；
- 保存订单、成交、持仓和对账的唯一账本；
- 为 CIA、RAA、ARC 和外部智能体提供受控查询与提交接口。

投研系统不负责：

- 自行生成无法追溯来源的观点；
- 把外部 MCP 结果直接当作正式 Evidence；
- 把 WorkBuddy 的 succeeded、processing 或文件出现当成业务成功；
- 允许模型输出绕过确定性验证和人工审批。

### 3.5 RAA：独立审计

RAA 负责：

- 审计策略提案、数据来源、评价方法、未来数据泄露和样本偏差；
- 检查策略版本、任务、交付物、Evidence、审批和归档是否一致；
- 独立复核高风险策略变更、研究结果和投资建议；
- 对缺失证据、口径冲突、不可复现或越权行为提出审计结论。

RAA 不负责：

- 替 CIA 作投资决策；
- 替 ARC 修改代码；
- 替 WorkBuddy 生产研究报告；
- 因系统运行正常而推定业务结论正确。

### 3.6 Ops：运行保障

Ops 负责：

- 服务、数据库、调度、共享目录和网络的稳定运行；
- 监控、日志、备份、恢复、容量和故障响应；
- 确保摄取 Worker、API、Dagster/systemd 作业持续可用；
- 维护凭据、权限和生产配置的安全边界。

Ops 不负责：

- 修改策略规则、研究结论或投资建议；
- 因恢复服务而重放未经授权的业务任务；
- 用运行状态替代业务完成信号。

## 4. 权威对象与唯一所有者

| 对象/决定 | 唯一业务所有者 | 生产者/执行者 | 审计者 |
|---|---|---|---|
| 投研方向和研究优先级 | CIA | CIA | RAA |
| StrategyProposal | invest-infra | CIA | RAA |
| StrategyVersion 激活/暂停/退役 | CIA，经 invest-infra 留痕 | invest-infra | RAA |
| DataAcquisitionMatrixVersion | invest-infra | WorkBuddy盘点，ARC实现摄取 | RAA |
| DataBundle | invest-infra | WorkBuddy 按 DataRequest 获取 | ARC 技术校验，RAA抽查 |
| 候选发现结果 | invest-infra 的 StageResult/CandidateProposal | invest-infra 专用 evaluator | RAA抽查 |
| CandidateAdmission | invest-infra | 确定性准入模块 | RAA |
| ResearchResult | invest-infra | WorkBuddy研究，系统验收 | RAA |
| WatchlistEntry | invest-infra | WorkBuddy复评，CIA判断 | RAA |
| Investment Proposal | CIA，经 invest-infra 留痕 | WorkBuddy/确定性组合模块 | RAA |
| 订单、成交和持仓 | invest-infra | 受控执行适配器 | RAA/Ops对账 |
| 代码与技术架构 | ARC | ARC/编码代理 | ARC技术验收，RAA按需审计 |
| 生产运行状态 | Ops | Ops | RAA按需审计 |

## 5. 标准工作流

### 5.1 策略制定与演进

```text
CIA确定方向和策略目标
→ CIA形成StrategyProposal
→ WorkBuddy提交数据能力评估材料
→ invest-infra执行Schema、数据能力、可计算性和样本验证
→ RAA独立审计
→ CIA批准或拒绝
→ invest-infra创建不可变StrategyVersion
→ 显式激活后允许执行
```

### 5.2 候选发现与研究

```text
invest-infra按active StrategyVersion和active DataAcquisitionDefinition生成DataRequest
→ WorkBuddy调用获准MCP并提交DataBundle
→ invest-infra校验DataBundle并由专用evaluator生成StageResult/CandidateProposal
→ invest-infra通过内部可信接缝创建Candidate ExternalObservation并正式准入
→ invest-infra发布research任务
→ WorkBuddy专家团队研究与风险反证
→ invest-infra校验Evidence并生成ResearchResult
→ CIA审阅并决定是否进入长期观察或建议流程
```

### 5.3 观察、后验与再演进

```text
invest-infra触发observation任务
→ WorkBuddy复评投资假设和风险
→ invest-infra追加观察版本
→ 确定性后验形成StrategyEvaluation
→ WorkBuddy提交StrategyChangeProposal
→ RAA审计
→ CIA决定是否发布下一StrategyVersion
```

## 6. 外部智能体接入接口

外部智能体必须通过窄接口接入，不得直接操作内部数据库。

只读查询接口：

```text
get_strategy_version
get_data_matrix_version
get_active_data_acquisition_definition
get_data_request
get_strategy_run_history
get_candidate_outcomes
get_research_results
get_observation_history
get_strategy_evaluation
```

受控提交接口：

```text
submit_strategy_proposal
submit_change_proposal
submit_data_bundle
submit_research_artifact
submit_observation_review
```

Stage 4D 首批可使用共享目录实现同一接口语义；后续 HTTP/MCP Adapter 必须复用相同领域合同，不能形成第二套业务逻辑。

现有 WorkBuddy Candidate 2.0.0 共享目录 Bridge 仅作为外部候选兼容入口保留。新 DataBundle 路径不得把 invest-infra 生成的 Candidate 重新标记为 `producer=workbuddy` 后送回该入口；DataBundle 的外部生产者为 WorkBuddy，StageResult/CandidateProposal 的生产者为 invest-infra，两类 provenance 必须分别保存并显式关联。

## 7. 强制治理规则

1. 外部智能体不能同时拥有提出、执行、评价和批准全部权力。
2. WorkBuddy 交付状态不等于投研系统正式状态。
3. 所有生产任务绑定不可变策略版本和数据矩阵版本。
4. 所有外部事实携带来源、`as_of`、单位、定义和可复现等级。
5. 数据冲突并列保存，禁止平均或静默覆盖。
6. 策略演进只能形成新版本，禁止修改历史版本。
7. 新策略先验证和 Challenger 影子运行，再由 CIA 批准成为 Champion。
8. AI 不得绕过 Evidence、风险、审批和交易账本。
9. RAA 审计结论与 CIA 投资决定分别保存，不互相替代。
10. Ops/ARC 的技术动作不得改变正式投研结论。

## 8. 结果

该分工使 OpenClaw 团队承担治理层：CIA 管策略和审批，ARC 管建设，RAA 管独立审计，Ops 管运行；WorkBuddy 作为外部数据与研究执行团队，充分使用金融 MCP 和技能交付可追溯数据包并开展研究；invest-infra 负责确定性候选计算，并保持数据、策略、结果、组合和审计记录的唯一权威。

代价是流程中增加正式准入、审计和审批步骤，但这是策略可复现、可追溯和受控演进的必要成本。
