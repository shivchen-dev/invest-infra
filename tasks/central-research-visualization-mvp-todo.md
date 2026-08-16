# 中心投研可视化平台 MVP Todo

> 计划：`docs/plan/invest-infra-central-research-visualization-mvp-plan-v1.0.md`
> 状态规则：`[ ]` 未开始，`[~]` 进行中，`[x]` 完成，`[!]` 阻塞。
> 当前状态：ACTIVE_EXECUTION，Slice 1 代码已完成，Slice 2.1 API 代码已完成；真实环境 Gate A 与 Web/后续切片仍未收口。
> 任务治理：`tasks/README.md`

## Slice 0：信息架构与合同冻结

- [x] 0.1 冻结中心首页最小问题集和导航结构
  - 验收：`/dashboard` 是唯一中心入口；现有详情页职责不重复。
  - 验证：页面—问题—来源映射逐项审查。
  - 依赖：无。
  - 预计范围：S，文档/API contract。
- [x] 0.2 冻结 `ResearchCenterResponse` v1 只读合同
  - 验收：所有字段均有真实 Reader 来源或明确 unavailable 原因。
  - 验证：schema examples 与 contract tests 设计评审。
  - 依赖：0.1。
  - 预计范围：M，3–5 个文件。
- [x] 0.3 冻结统一状态与时间语义
  - 验收：freshness、quality、partial、stale、unavailable 不混用；`as_of/observed_at/generated_at` 定义明确。
  - 验证：现有端点映射检查。
  - 依赖：0.1。
  - 预计范围：S，1–2 个文件。

### Checkpoint 0

- [x] 字段无模拟数据和隐式零值
- [x] 不包含回测、自动批准、自动交易字段
- [x] 用户审核并授权 Slice 1

## Slice 1：市场真实状态

- [x] 1.1 实现中心 Read Model 的市场状态切片
  - 验收：组合 Market Breadth、数据新鲜度和市场日期；返回确定性空/错误状态。
  - 验证：Application focused tests。
  - 依赖：Checkpoint 0。
  - 预计范围：M，3–5 个文件。
- [x] 1.2 暴露中心只读端点并同步 OpenAPI
  - 验收：响应版本固定；错误脱敏；生成客户端无 drift。
  - 验证：API tests、OpenAPI drift check。
  - 依赖：1.1。
  - 预计范围：M，3–5 个文件。
- [x] 1.3 交付市场状态卡片
  - 验收：展示来源、日期、freshness、quality；loading/empty/stale/partial/failed 齐全。
  - 验证：Web component tests、typecheck、build。
  - 依赖：1.2。
  - 预计范围：M，3–5 个文件。

### Gate A：真实市场可视化

- [ ] 真实环境可读取一个 Market Breadth snapshot 或显示准确 unavailable 原因
- [ ] 所有市场字段可追溯到来源和观察日期
- [ ] API/Web focused tests 与构建通过
- [ ] 用户审核并授权 Slice 2

## Slice 2：研究与机会工作台

- [x] 2.1 聚合 Research Case/Run/Evidence 摘要
  - 验收：研究数量、最新研究、运行和证据状态来源明确。
  - 验证：Application/API focused tests。
  - 依赖：Gate A。
  - 预计范围：M，3–5 个文件。
- [x] 2.2 聚合内部候选与外部机会摘要
  - 验收：Candidate Pool、ExternalObservation、Admission 三类状态不混用。
  - 验证：Application/API focused tests、全量 API tests、Ruff、OpenAPI drift、架构边界检查。
  - 依赖：Gate A。
  - 预计范围：M，3–5 个文件。
- [x] 2.3 重组中心首页与详情入口
  - 验收：首页只显示摘要；每项进入现有详情页；状态视觉分层。
  - 验证：Dashboard tests、router tests、Web typecheck、production build；人工导航待 Checkpoint 2 联合验收记录。
  - 依赖：2.1、2.2。
  - 预计范围：M，3–5 个文件。

### Checkpoint 2

- [ ] 市场事实、外部观察和研究判断视觉分层
- [ ] 空、部分、冲突和失败状态有稳定呈现
- [ ] Web typecheck、tests、build 通过

## Slice 3：交付链与可信度

- [ ] 3.1 聚合 Pipeline、Integration 和归档状态
  - 验收：文件归档、业务准入和研究完成保持独立状态。
  - 验证：Application/API focused tests。
  - 依赖：Checkpoint 2。
  - 预计范围：M，3–5 个文件。
- [ ] 3.2 交付可信度与交付链卡片
  - 验收：无宿主机路径泄漏；cancelled orphan 可解释且不阻断其他内容。
  - 验证：Web tests、安全脱敏测试、刷新恢复检查。
  - 依赖：3.1。
  - 预计范围：M，3–5 个文件。
- [ ] 3.3 完成中心平台真实环境验收
  - 验收：至少覆盖真实、stale/unavailable、外部交付异常三种状态。
  - 验证：保留命令、响应摘要、`as_of` 和来源记录。
  - 依赖：3.2。
  - 预计范围：S，验收记录。

### Gate B：中心只读平台 MVP

- [ ] 中心首页回答六个最小研判问题
- [ ] 浏览器无业务写操作且不读取共享目录
- [ ] OpenAPI、API、Web 和全量回归通过
- [ ] 真实环境验收可复现
- [ ] 用户审核通过

## Slice 4：策略迭代只读窗口（独立授权）

- [ ] 4.0 冻结 `strategy-iteration` 最小合同并确认真实样本
- [ ] 4.1 实现策略版本/变更只读查询切片
- [ ] 4.2 展示原始假设、变更、原因、环境和失效条件
- [ ] 4.3 验证历史不可覆盖、提案与人工决定分离

前置 Gate：4.0 未通过时，只允许显示明确空状态，不实施 4.1–4.3。

## Slice 5：持仓纪律只读窗口（独立授权）

- [ ] 5.0 冻结 `position-discipline` 最小合同和持仓事实权威源
- [ ] 5.1 实现持仓纪律只读查询切片
- [ ] 5.2 展示仓位上限、周期、加减仓/退出条件和偏离状态
- [ ] 5.3 验证实际持仓与 ETF 成分 Exposure 不混淆

前置 Gate：5.0 未通过时，只允许显示明确空状态，不实施 5.1–5.3。

## 明确不在本 Todo

- 回测、参数寻优和收益证明
- 自动策略批准、激活和淘汰
- 自动交易、下单和仓位调整
- 通用 BI、通用流程设计器
- 未冻结合同的数据录入页面
