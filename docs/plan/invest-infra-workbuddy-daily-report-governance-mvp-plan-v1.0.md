# WorkBuddy 候选线索治理 MVP 实施计划

> 文档版本：v2.0
> 文档状态：Frozen for Implementation
> 日期：2026-08-14
> 生产规则：`WORKBUDDY-REPORT-RULES.md` 2.0.0

## 1. 目标

将 WorkBuddy 定位为外部候选生产者。投研系统以宽进严管方式接收候选：入口只保证“可识别、可去重、可留档”，正式身份、数据和来源验证由 `invest-infra` 完成；选股、评分和排名仍由 WorkBuddy 负责。

## 2. 职责边界

### WorkBuddy

- 按用户策略执行筛选；
- 输出 `workflow_run_id`、`trade_date`、`strategy_id`、状态和候选数组；
- 每个候选只必须有 `symbol` 和简短 `reason`；
- 如实披露 partial / failed；
- 不负责正式投研验证与排名。

### invest-infra

- 解析 2.0.0 最小候选 JSON；
- 映射证券主数据、去重并标记无法映射项；
- 不可变留存原始输入和导入 findings；
- 将合法候选写入 ExternalObservation，进入待验证状态；
- 在后续流程完成正式数据验证和准入，准入后进入 Research Case；
- 不重复开发 WorkBuddy 的选股、评分和排名功能。

## 3. 最小流程

```text
WorkBuddy candidate artifact
→ parse + run identity validation
→ item-level symbol/reason validation
→ symbol resolution + deduplication
→ immutable raw archive
→ ExternalObservation pending_validation
→ formal data validation / admission
→ invest-infra research pipeline
```

单个坏候选只产生 item-level finding，不拒绝整批。无法映射的 symbol 进入待解析状态，不影响其他候选。

## 4. 明确非目标

候选入口不校验：

- 阶段集合和阶段衔接；
- 综合分、维度分、权重或归一化公式；
- 生产端排名和 Override；
- `source_refs` 完整性或原始响应 hash；
- Markdown 和 JSON 的逐字段一致性；
- 生产者 quality report 和 manifest。

现有 `workbuddy_reports` 模块及 legacy 报告审计合同退出当前生产路径，仅保留历史资料。

## 5. 实施阶段

### M0：合同收缩

- [x] 生产规则升级为 2.0.0；
- [x] 冻结最小候选合同；
- [x] 明确 legacy 报告审计与候选入口分离。

### M1：候选适配与轻量校验

- [x] 实现 2.0.0 candidates JSON parser；
- [x] 明确不实现 1.1.1 / 1.1.2 历史三件套兼容；
- [x] 实现 run-level 和 item-level 轻量校验；
- [x] 输出标准化 candidate intake result。

### M2：归档、去重与外部候选准入接入

- [x] 原始产物不可变归档；
- [x] 实现运行幂等与内容冲突保护；
- [x] 实现 symbol resolution 和业务去重；
- [x] 投影至 ExternalObservation pending_validation（纯函数切片，数据库准入由 Stage 4D 负责）。

### M3：真实样本验收

- [x] 1.1.x legacy 样本不纳入当前真实验收范围；
- [x] 评分不可复算、ranking 缺失、source refs 不完整不阻断外部候选准入；
- [x] 验证单项拒绝、去重、幂等和原始归档；
- [x] Pipeline 回归通过。

## 6. Definition of Done

- WorkBuddy 只需输出可识别候选及入选理由；
- 一个坏候选不影响同批其他候选；
- 现有真实样本不再因报告审计问题无法入池；
- 投研系统承担正式身份、数据、来源验证和研究责任，不重复实现 WorkBuddy 的选股、评分、排名；
- 原始候选输入可留档、重复导入幂等、冲突不覆盖；
- legacy 严格审计退出当前生产范围，不阻断 2.0.0 外部候选准入。

## 7. 暂缓

- API / Web；
- Dagster Sensor；
- 生产端正式评分审计；
- 将 WorkBuddy 观点直接升格为 Evidence 或投资建议。
