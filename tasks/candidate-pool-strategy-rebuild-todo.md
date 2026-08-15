# 原候选池两阶段选股报告工作流重建执行清单

## Phase 0：原始报告与行为基线

- [ ] 登记板块和个股阶段的 Markdown、结构化结果、质量报告及 hash
- [ ] 固化 23 → 20 → 5 → 2 → 0 阶段计数和 `needs_rule_confirmation`
- [ ] 固化两阶段上下游输入输出关系
- [ ] 分类确定性规则、策略判断、模型解释和正式准入门禁
- [ ] 盘点旧 Candidate Pool、WorkBuddy 调度、目录、摄取和准入入口
- [ ] 明确允许差异、必须一致项和回滚方式

## Phase 1：策略与交付合同

- [ ] 登记板块和个股 StrategySourceDocument 原文、artifact 和 hash
- [ ] 完成两个策略范围的 StrategyCapabilityAssessment
- [ ] 冻结 Sector StrategyVersion 职责和最小输入输出
- [ ] 冻结 Stock StrategyVersion 职责和最小输入输出
- [ ] 冻结 CandidateSelectionWorkflowVersion/CandidateSelectionRun 合同
- [ ] 冻结 SectorStageResult → Stock StrategyTask 阶段依赖
- [ ] 设计两阶段最小结构化结果合同
- [ ] 设计两阶段 Markdown 推荐模板
- [ ] 设计两阶段质量结果合同
- [ ] 冻结严格信封和 required/optional/extension 业务载荷
- [ ] 冻结 error/warning/review 和坏项隔离规则
- [ ] 建立成功、partial、review、failed、坏项和重复交付 fixtures
- [ ] 通过人工审核创建不可变策略和工作流版本，暂不激活生产
- [ ] 为两个策略建立独立 StrategyAutomationDefinition
- [ ] 人工触发验收通过前不启用周期调度

## Phase 2：数据与代码辅助

- [ ] 绑定 DataAcquisitionMatrixVersion 和首轮实际 Provider
- [ ] 生成不可变 InputSnapshot 和 input hash
- [ ] 建立规则职责分类表，避免全部规则强制代码化
- [ ] 抽取确需复算的确定性指标和规则
- [ ] 实现受控数据读取和阶段输入组装
- [ ] 实现 artifact 合同、身份和 hash 校验
- [ ] 覆盖 Provider 失败、fallback、过期、缺数据、partial 和 review 测试

## Phase 3：两阶段工作流执行

- [ ] 从 active CandidateSelectionWorkflowVersion 创建板块 StrategyTask
- [ ] 摄取板块结构化结果、Markdown 和质量报告
- [ ] 形成正式 SectorStageResult
- [ ] 使用上游 run id 和 artifact hash 创建个股 StrategyTask
- [ ] 摄取个股结构化结果、Markdown 和质量报告
- [ ] 形成正式 StockStageResult
- [ ] 保存各阶段计数、淘汰原因、警告、复核状态和原始 artifact
- [ ] 从合法末阶段结果生成 CandidateProposal
- [ ] 验证 Markdown 格式差异不阻断合法结构化交付

## Phase 4：正式候选准入

- [ ] 对 CandidateProposal 校验 symbol、日期、来源、重复和数据新鲜度
- [ ] 实现合法项继续、可恢复项 review、非法项隔离
- [ ] 保留工作流、两个策略、两个阶段运行及报告归因
- [ ] 通过 CandidateAdmission 创建 CandidateEntry
- [ ] 验证未准入候选不能创建 ResearchCase/ResearchRun
- [ ] 验证 WorkBuddy ExternalObservation 不形成正式状态旁路

## Phase 5：双轨报告回放

- [ ] 使用等价输入运行旧工作流和新工作流
- [ ] 对比两阶段结构化结果、阶段计数、TOP板块和个股淘汰
- [ ] 对比状态、候选集合、输入输出 hash 和 artifact 引用
- [ ] 人工核对报告业务信息，不要求逐字一致
- [ ] 复现 2026-08-13 基线
- [ ] 完成至少一个新交易日真实回放
- [ ] 归类并处理数据、规则、解释、合同和实现差异
- [ ] 归档测试、原始交付物、数据库记录和差异报告

## Phase 6：旧编排退役

- [ ] 验收后显式激活新工作流
- [ ] 标记旧入口 deprecated
- [ ] 停止旧入口产生新的正式运行
- [ ] 保留历史报告、结果、质量记录和回放能力
- [ ] 完成回滚窗口验收
- [ ] 清理确认重复且无调用方的旧逻辑

## 发布门禁

- [ ] 两个策略版本和工作流版本不可变且可追溯
- [ ] 下游输入绑定上游 StageResult、run id 和 artifact hash
- [ ] 2026-08-13 的 23 → 20 → 5 → 2 → 0 基线可解释复现
- [ ] JSON 作为机器权威，Markdown 不被解析为业务状态
- [ ] error/warning/review 和坏项隔离全链路通过
- [ ] CandidateAdmission 全链路通过
- [ ] 全量测试、Ruff、架构检查、迁移检查和 `git diff --check` 通过
- [ ] 旧路径可回滚，且未混入其他 dirty 改动
