# 原候选池两阶段选股报告工作流重建实施计划

## 1. 目标

沿用原候选池已经实际运行的业务顺序，将“板块七步策略报告 → 个股六维策略报告 → 正式准入 → 候选池”重建为可版本化、可回放、可审计的候选选择工作流。先冻结真实业务交付物和阶段衔接，再决定哪些步骤由代码确定性执行；不按现有代码结构反推或重写选股业务。

首个工作流固定复刻以下两个完整策略阶段：

1. `sector-seven-step-v2`：从市场与板块数据形成板块强度结构化结果、质量结果和人工报告，输出 TOP 板块及代表标的；
2. `tdx-six-dimension-v2`：消费第一阶段的正式输出，执行个股筛选并形成结构化候选结果、质量结果和人工报告。

目标链路：

```text
DataAcquisitionMatrixVersion + immutable InputSnapshot
  → CandidateSelectionWorkflowVersion
      → Sector StrategyVersion / StrategyTask
          → sector_result.json + sector_report.md + sector_quality.json
      → validated SectorStageResult
      → Stock StrategyVersion / StrategyTask
          → result.json + report.md + quality_report.json
      → validated StockStageResult
  → CandidateProposal
  → CandidateAdmission
  → CandidateEntry
  → formal Candidate Pool
```

`CandidateSelectionWorkflowVersion` 只对外提供“以冻结输入运行两阶段选股并返回候选提案”的小接口。各策略内部的筛选、评分、否决、排序和解释步骤保留在策略模块内部，不全部提升为独立策略或公共工作流节点。

## 2. 现场行为基线

首个回放基线使用 2026-08-13 原始交付物：

- 板块策略：23 个板块 → 初筛 20 个 → TOP5 板块及 5 只代表标的；
- 个股策略：5 只输入 → 筹码筛选通过 2 只 → 量价筛选通过 0 只；
- 个股报告最终状态为 `needs_rule_confirmation`，未形成正式候选；
- 第二阶段明确引用第一阶段报告及运行结果作为输入。

原始 Markdown、结构化 JSON 和质量报告共同构成行为证据。Markdown 用于人工理解和审核；JSON 是机器流转权威；质量报告记录生产者自检，但不替代投研系统正式验收。

## 3. 范围

### 纳入范围

- 冻结板块策略、个股策略及两阶段衔接的最小合同；
- 将用户原始策略文档登记为 StrategySourceDocument，并在工程化前形成 StrategyCapabilityAssessment；
- 建立两个完整 `StrategyVersion`，不把每条内部规则都拆成独立策略；
- 为两个策略版本建立独立 StrategyAutomationDefinition，再由候选选择工作流串联；
- 建立不可变 `CandidateSelectionWorkflowVersion` 和可回放 `CandidateSelectionRun`；
- 统一数据来源、Provider、回退、新鲜度、质量门禁及不可变 InputSnapshot；
- 保存工作流版本、两个策略版本、上下游运行身份、artifact hash、输入 hash 和输出 hash；
- 保留每阶段的结构化结果、Markdown 报告、质量报告、错误、警告和人工复核状态；
- 将合法的末阶段结果投影为 CandidateProposal，并经 CandidateAdmission 创建 CandidateEntry；
- 保持旧工作流结果可回放、可对比、可追溯和可回滚。

### 不纳入范围

- 不首轮建设通用 DAG、图形编排器、自定义表达式语言或动态插件体系；
- 不先验地把 `filter/score/veto/rank/top_n` 全部拆为独立 StrategyVersion；
- 不要求智能体报告完全遵循标题、顺序或固定措辞；
- 不通过解析 Markdown 推进机器状态；
- 不首轮更换实际行情 Provider；
- 不建设自动调参、自动市场状态切换或复杂回测平台；
- 不在双轨验收和回滚窗口结束前删除旧入口或原始交付物；
- 不允许 WorkBuddy 报告直接写正式候选池。

## 4. 架构决策

1. **业务工作流优先。** 以两份真实策略报告的生成与衔接顺序定义工作流，不以现有类、表或函数划分业务阶段。
2. **完整策略作为深模块。** 板块策略和个股策略分别通过小接口接收冻结输入并返回阶段结果；内部规则、步骤和模型解释由各自实现隐藏。
3. **报告与机器合同分离。** Markdown 是人工交付模板；结构化 JSON 是流转权威；格式差异不成为无关硬门禁。
4. **代码辅助而非替代业务。** 代码负责数据快照、确定性计算、合同校验、hash、幂等、追溯和正式准入；策略分析与解释仍由策略执行流程产生。
5. **阶段输出显式传递。** 第二阶段只消费已校验的 SectorStageResult 和其 artifact 引用，不依赖文件名猜测或 Markdown 抽取。
6. **最窄范围校验。** 信封错误可阻断阶段；业务内容可 warning/review；单个坏候选隔离，不拖垮合法候选。
7. **正式候选只来自准入。** Candidate Pool 是工作流末端的正式结果，不是任一策略报告的直接输出。
8. **兼容优先、删除延后。** 新工作流完成真实回放和双轨验收前，旧入口只允许保留和标记迁移状态，不删除。

## 5. 实施阶段

### Phase 0：原始报告与行为基线冻结

- 归档并登记两份原始 Markdown、两个结构化结果和两个质量报告的路径、hash、schema 事实和运行身份；
- 记录两阶段真实输入输出关系及 23 → 20 → 5 → 2 → 0 的阶段计数；
- 盘点策略内部确定性规则、模型解释、人工判断、数据缺失和异常处理；
- 盘点旧 Candidate Pool、WorkBuddy 目录、调度、摄取和正式准入入口；
- 明确允许差异、必须一致项、降级规则和回滚方式。

### Phase 1：两阶段策略与交付合同冻结

- 冻结 Sector StrategyVersion 和 Stock StrategyVersion 的职责、输入和输出；
- 登记两个阶段的 StrategySourceDocument，并绑定策略范围能力评估；
- 冻结 CandidateSelectionWorkflowVersion、CandidateSelectionRun 和阶段依赖合同；
- 为每阶段设计最小结构化结果、Markdown 推荐模板和质量结果合同；
- 通用信封只保留身份、stage/schema version、状态、时间、artifact inventory 和 hash；
- 业务载荷区分 required/optional/extension；校验区分 error/warning/review；
- 提供最小成功、partial、needs_rule_confirmation、failed、坏项隔离和重复交付 fixtures；
- 通过策略治理人工审核后创建不可变策略版本和工作流版本，暂不激活生产。
- 为两个策略版本设计不复制业务规则的 StrategyAutomationDefinition，先人工触发验收，暂不开启周期调度。

### Phase 2：数据与代码辅助能力

- 建立或复用 DataAcquisitionMatrixVersion，保持首轮实际 Provider 不变；
- 生成不可变 InputSnapshot，保存成员、时间范围、来源、质量结果和 hash；
- 逐条分类现有规则：确定性代码、策略内部判断、模型解释或正式准入门禁；
- 只将已经确定且需要复算的指标和规则抽入代码模块；不为统一外观强制代码化；
- 提供受控数据读取、阶段输入组装、确定性复算、artifact 校验和 hash 支持；
- 覆盖缺数据、过期、Provider 失败、fallback、partial 和 needs_review 路径。

### Phase 3：两阶段工作流执行与交付

- 由 active CandidateSelectionWorkflowVersion 创建板块 StrategyTask；
- 摄取并校验板块结构化结果、Markdown 报告和质量报告，形成 SectorStageResult；
- 仅在阶段合同允许时，将 TOP 板块及代表标的作为正式下游输入；
- 创建个股 StrategyTask，并绑定上游 run id、artifact hash 和两个策略版本；
- 摄取并校验个股结构化结果、Markdown 报告和质量报告，形成 StockStageResult；
- 保存完整阶段计数、淘汰原因、警告、复核状态和原始 artifact；
- 由合法末阶段结果生成 CandidateProposal，不直接生成 CandidateEntry。

### Phase 4：正式候选准入

- 对 CandidateProposal 执行 symbol、日期、来源、重复、新鲜度和正式数据校验；
- 合法项继续，缺失但可恢复项进入 review，非法项隔离；
- 保留候选对工作流版本、两个策略版本、两个阶段运行和原始报告的归因；
- CandidateEntry 只能由 CandidateAdmission 创建；未准入项不能触发 ResearchCase/ResearchRun；
- WorkBuddy 既有 ExternalObservation provenance 保留，不形成正式状态旁路。

### Phase 5：双轨报告回放与切换

- 使用相同数据截止时间和等价输入运行旧工作流与新工作流；
- 比较两阶段结构化结果、阶段计数、TOP 板块、个股淘汰、状态、候选集合和 hash；
- 人工比较 Markdown 报告的业务信息完整性，不要求逐字一致；
- 对差异分类为数据、规则、策略解释、合同归一化或实现缺陷；
- 完成 2026-08-13 原始样本和至少一组新的真实交易日回放；
- 验收通过后显式激活新工作流，并将旧入口标记 deprecated。

### Phase 6：旧编排退役

- 停止旧入口产生新的正式 CandidatePoolRun；
- 保留历史报告、结构化结果、质量报告、读取和回放能力；
- 清理确认重复且无调用方的数据获取、任务发布和摄取逻辑；
- 只有回滚窗口结束且验收证据归档后，才删除无调用方的旧代码。

## 6. 验收门禁

- 两个策略版本及 CandidateSelectionWorkflowVersion 发布后不可变；
- 第二阶段输入可追溯到第一阶段 run id、正式结构化结果和 artifact hash；
- 同一工作流版本、两个策略版本、数据矩阵版本和 InputSnapshot 可重复得到一致的阶段身份与 hash；
- 2026-08-13 基线可解释复现 23 → 20 → 5 → 2 → 0 及 `needs_rule_confirmation`；
- Markdown 表达允许合理变化，机器流转不依赖 Markdown 标题或自然语言解析；
- Provider、fallback、数据范围、质量结果和每阶段原始 artifact 可追溯；
- CandidateProposal 不能绕过 CandidateAdmission 创建 CandidateEntry；
- 坏项隔离、重复幂等、warning/review、未准入阻断研究均有测试；
- 旧入口在新路径验收和回滚窗口结束前仍可使用；
- 全量测试、架构检查、迁移检查和 `git diff --check` 通过。

## 7. 主要风险

| 风险 | 影响 | 控制措施 |
|---|---|---|
| 按代码结构重写业务 | 原有策略语义丢失 | 先冻结真实报告工作流和回放基线 |
| 将内部规则过度拆成策略 | 工作流接口膨胀、难以维护 | 两个完整策略作为深模块，内部步骤默认隐藏 |
| 报告模板门禁过高 | 智能体结果无法流转 | 严格信封、宽容业务载荷、Markdown 只作人工模板 |
| 数据与规则同时变化 | 无法定位差异来源 | 固定数据截止时间和 Provider 后再做双轨比较 |
| 上游报告靠文件名或文本传递 | 下游输入不可复现 | 使用正式 StageResult、run id 和 artifact hash |
| WorkBuddy 结果直接入池 | 污染正式候选 | CandidateProposal + CandidateAdmission 硬门禁 |
| 过早删除旧链路 | 无法回滚 | deprecated 优先，回滚窗口后再删除 |

## 8. 基线与参考实现

- 原板块报告：`/home/claw/windows-ltsc/shared/选股报告/板块强度排行榜_2026-08-13.md`
- 原板块结果：`/home/claw/windows-ltsc/shared/选股报告/sector_result_2026-08-13.json`
- 原板块质量结果：`/home/claw/windows-ltsc/shared/选股报告/sector_quality_2026-08-13.json`
- 原个股报告：`/home/claw/windows-ltsc/shared/选股报告/report_2026-08-13.md`
- 原个股结果：`/home/claw/windows-ltsc/shared/选股报告/result_2026-08-13.json`
- 原个股质量结果：`/home/claw/windows-ltsc/shared/选股报告/quality_report_2026-08-13.json`
- 旧候选池应用服务：`apps/pipeline/src/invest_pipeline/candidate_pool_service.py`
- WorkBuddy 候选摄取：`apps/pipeline/src/invest_pipeline/workbuddy_candidates/`
- WorkBuddy Bridge：`apps/pipeline/src/invest_pipeline/integrations/bridge_ingestor.py`
- 策略库总计划：`tasks/stage4d-strategy-library-workflow-plan.md`
