# Stage 4D–4G 策略库驱动投研工作流执行清单

## S0 领域合同

- [ ] 冻结 Strategy/StrategyVersion/StrategyTask 职责
- [ ] 冻结 StrategySourceDocument/StrategyCapabilityAssessment 职责
- [ ] 冻结 StrategyAutomationDefinition 与策略业务规则的分工
- [ ] 冻结 StrategyRun/StageResult 的运行、交付、摄取和业务状态
- [ ] 冻结 CandidateSelectionWorkflowVersion/CandidateSelectionRun 职责
- [ ] 冻结 CandidateProposal 与正式 CandidateEntry 的分工
- [ ] 冻结 CandidateAdmission/CandidateEntry 职责
- [ ] 冻结 ResearchCase/Run/Result 与 WatchlistEntry 分工
- [ ] 冻结 StrategyEvaluation/StrategyChangeProposal 职责
- [ ] 冻结 strategy/candidate/research/observation 合同与版本规则
- [x] 发布 WorkBuddy 数据获取矩阵任务
- [x] 盘点并实测 Skills、金融 MCP、Connector、通达信和投研 API
- [x] 冻结 candidate/research/observation v1 数据路由矩阵
- [x] 明确 discovery/cross-check/admission/fallback 数据源

## S0A 阶段摄取与自动归档（最高优先级）

- [ ] 实现统一 Stage Artifact Worker
- [ ] strategy/candidate/research/observation 独立合同路由
- [ ] 实现原子 claim、archive/failed 和重启恢复
- [ ] 实现数据库事务失败可重试
- [ ] 使用真实 data-matrix 归档包重放测试
- [ ] 修复 Dagster服务与WorkBuddy schedule环境变量
- [ ] 改为扫描四阶段 `.ready` 包
- [ ] 增加 backlog/失败/最后成功摄取指标
- [ ] 恢复 daily-bars 和 freshness snapshot
- [ ] 完成 Ops 连续两轮运行验收

## S1 Strategy Governance 人工审核闭环

- [ ] 实现 StrategySourceDocument 原文登记、artifact 和 hash
- [ ] 支持源文档不可变 revision 与重复幂等
- [ ] 发布策略范围 WorkBuddy 数据能力评估任务
- [ ] 摄取 StrategyCapabilityAssessment
- [ ] 支持 ready/degraded/review/blocked 评估状态
- [ ] 绑定 StrategySourceDocument/DataAcquisitionMatrixVersion/数据截止时间
- [ ] 实现 strategy 阶段任务发布
- [ ] 冻结 strategy.json/strategy.md/validation.json 合同
- [ ] 冻结 change-proposal.json 合同
- [ ] 摄取 WorkBuddy 交付并创建 StrategyProposal
- [ ] 强制 StrategyProposal 绑定源文档和能力评估
- [ ] 实现 StrategyProposalRevision
- [ ] 实现 StrategyValidationRun
- [ ] 实现 DataAcquisitionMatrixVersion
- [ ] 实现 schema、数据能力、可计算性和未来数据泄露检查
- [ ] 生成 ReviewPackage 与父版本 diff
- [ ] 实现 StrategyAudit 人工录入和 revision/hash 校验
- [ ] 实现 CIA 批准/拒绝/退回修改 API
- [ ] 实现 CIA 策略审核页面
- [ ] 验证旧 revision 和旧 hash 决定 fail closed
- [ ] 实现 StrategyProposal validating/validation_failed/review_pending/approved/rejected
- [ ] 验证只有人工批准后才能创建正式 StrategyVersion
- [ ] 实现 Strategy 与不可变 StrategyVersion
- [ ] 实现策略类型、适用场景、数据依赖和任务模板
- [ ] 实现 draft/validating/approved/active/suspended/retired
- [ ] 实现版本化 StrategyAutomationDefinition
- [ ] 绑定任务模板、执行 adapter、调度、输入装配和交付合同
- [ ] 验证 active StrategyVersion + active AutomationDefinition 才能发布任务
- [ ] 验证自动化可独立 paused/retired
- [ ] 先完成人工触发验收，再启用周期调度
- [ ] 分离运行、交付、摄取和业务结果状态
- [ ] 实现 repository、migration 和 API
- [ ] 创建板块七步候选策略 v1 fixture
- [ ] 创建个股六维筛选策略 v1 fixture
- [ ] 实现不可变 CandidateSelectionWorkflowVersion
- [ ] 首批固定板块策略 → 个股策略两阶段依赖
- [ ] 不把策略内部 filter/score/veto/rank/top_n 提升为公共节点
- [ ] 保存工作流及全部组成策略版本归因
- [ ] 保存两阶段结构化结果、Markdown、质量结果和运行归因
- [ ] 验证下游绑定上游 StageResult/run id/artifact hash
- [ ] 验证相同 InputSnapshot 的工作流运行可重复
- [ ] 验证 v2 不改变 v1 历史语义
- [ ] 完成一次真实 WorkBuddy 策略制定任务验收

## S1A CIA/RAA OpenClaw适配

- [ ] 人工审核闭环通过后冻结外部适配合同
- [ ] 实现 ReviewPackage派送Adapter
- [ ] 实现RAA结构化审计回写
- [ ] 实现CIA结构化决定回写
- [ ] 验证身份/revision/hash/重复回调
- [ ] 验证OpenClaw不可用时人工审核不受阻

## S2 候选发现闭环

- [ ] 从 active CandidateSelectionWorkflowVersion 发布任务
- [ ] 发布板块策略任务并绑定工作流、策略和数据版本
- [ ] 摄取板块结构化结果、Markdown 和质量结果
- [ ] 形成 SectorStageResult
- [ ] 绑定上游 run id/artifact hash 发布个股策略任务
- [ ] 摄取个股结构化结果、Markdown 和质量结果
- [ ] 形成 StockStageResult 和 CandidateProposal
- [ ] 投影并保留 ExternalObservation provenance
- [ ] 完成身份、去重、来源、日期和数据准入
- [ ] 形成 CandidateAdmission/CandidateEntry
- [ ] 验证坏项隔离、重复幂等和多策略归因
- [ ] 完成一次真实 WorkBuddy ETF 候选验收

## S3 深度研究闭环

- [ ] 从 CandidateEntry 创建/关联 ResearchCase
- [ ] 生成 EvidencePack 和 ResearchRun
- [ ] 绑定 deep_research StrategyVersion
- [ ] 发布 research 阶段任务
- [ ] 摄取 result.json/report.md/evidence.json
- [ ] 验证 Evidence、日期、来源和身份
- [ ] 生成正式 ResearchResult
- [ ] 验证 succeeded/partial/failed/blocked_no_data
- [ ] 完成一个真实 ETF 全链路验收

## S4 长期观察

- [ ] 实现 WatchlistEntry 和状态机
- [ ] 保存投资假设、指标、风险、复评周期和退出条件
- [ ] 支持固定周期触发复评
- [ ] 支持事件触发复评
- [ ] 发布 observation 阶段任务
- [ ] 摄取 review.json/report.md
- [ ] 验证复评追加版本、不覆盖历史

## S5 投资建议与组合联动

- [ ] 生成 Investment Proposal
- [ ] 引用 ResearchResult、WatchlistEntry、策略版本和 Evidence
- [ ] 执行确定性 Risk Check
- [ ] 完成人工批准/拒绝和冻结
- [ ] 对接 Stage 4F Portfolio/OMS 接口
- [ ] 验证未审批建议不产生交易动作

## S6 策略评价与演进

- [ ] 实现 StrategyEvaluation
- [ ] 分开候选、研究、观察、市场阶段和建议评价
- [ ] 实现 StrategyChangeProposal
- [ ] 实现验证、审批和拒绝流程
- [ ] 发布保留 parent_version/change_reason 的新版本
- [ ] 对比 v1/v2 样本外表现
- [ ] 验证 WorkBuddy 不能直接修改 active 策略

## S7 多策略与可视化

- [ ] 支持 independent/complementary/exclusive 关系
- [ ] 合并重复候选研究并保留多策略来源
- [ ] 实现策略库页面
- [ ] 实现候选工作台
- [ ] 实现研究与观察工作台
- [ ] 实现策略评价页面
- [ ] 完成双策略 ETF E2E

## Release checkpoints

- [ ] S0A：四阶段自动摄取、归档和恢复验收通过
- [ ] S1：策略身份、版本和生命周期验收通过
- [ ] S1A：CIA/RAA适配不形成正式状态旁路
- [ ] S2：真实候选发现与准入闭环通过
- [ ] S3：真实 ResearchResult 闭环通过
- [ ] S4：长期观察和一次复评通过
- [ ] S5：建议、风控和审批通过
- [ ] S6：策略评价、提案和新版本发布通过
- [ ] S7：多策略归因与四个工作台通过
- [ ] 每阶段保留测试、交付物、数据库记录、hash 和失败样本
