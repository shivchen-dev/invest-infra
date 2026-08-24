# WorkBuddy 候选线索导入：M0 合同

> 状态：Frozen for implementation
> 日期：2026-08-14
> 生产规则：`WORKBUDDY-REPORT-RULES.md` 2.0.0

## 1. 业务定位

WorkBuddy 输出是待投研系统验证的外部候选线索，不是正式研究结论。外部候选准入与报告审计是两条独立流程：

```text
WorkBuddy candidates JSON → 轻量入口校验 → ExternalObservation
                                           ↓
                              正式数据验证 / 准入 → 研究

legacy 三件套不属于当前 Candidate Intake 入口；历史审计合同仅作归档参考
```

## 2. 入口硬门槛

只有下列问题可以阻断整批导入：

- 文件不是可解析 JSON；
- `workflow_run_id`、`trade_date`、`strategy_id`、`status`、`candidates` 缺失或类型错误；
- `trade_date` 不是真实的 `YYYY-MM-DD`；
- `workflow_run_id` 不符合安全单路径段要求；
- 同一运行 ID 以不同内容重复导入。

单个候选缺少非空 `symbol` 或 `reason` 时，只拒绝该项并记录 finding，不影响同批其他项。

## 3. 不阻断外部准入的内容

WorkBuddy 分数、排名、阶段过程、来源明细、Markdown、质量报告和生产者自检均为可选上下文。它们可被原样留存，但不能决定外部候选是否准入。

## 4. 投研系统责任

导入后由 `invest-infra` 负责：

- 将原始代码映射到证券主数据；
- 以 `(trade_date, strategy_id, normalized_symbol)` 去重；
- 留存原始 symbol、reason、可选分数与附件引用；
- 为无法映射项标记 `needs_symbol_resolution`，不回写 WorkBuddy 文件；
- 完成证券身份、时间、来源和正式数据验证；
- 通过准入后创建 Research Case 并进入研究流程；
- 不重复实现 WorkBuddy 的选股、评分和排名算法。

## 5. 导入结果

导入必须返回：

```text
workflow_run_id
accepted_count
rejected_item_count
duplicate_count
needs_symbol_resolution_count
findings[]
archive_uri
```

原始候选 JSON 按运行不可变归档。外部候选准入不使用 `latest-accepted.json`，也不依赖 legacy 报告审计的 `accepted/partial/rejected` 状态。

## 6. 兼容边界

- 生产规则 `2.0.0` 是当前唯一候选入口合同；
- `1.1.1` / `1.1.2` 三件套不再兼容、不再验收，也不再作为当前 Gate 的依赖；
- `workbuddy_reports` 及其 legacy 审计合同仅保留为历史资料，不属于当前生产路径。

## 7. M0 验收

- [x] 2.0.0 最小候选 JSON 可导入（纯 Python API）；
- [x] legacy 1.1.x 三件套明确移出当前入口与验收范围；
- [x] 一个坏候选不阻断其他合法候选；
- [x] 重复导入幂等，同 run ID 不同内容冲突拒绝；
- [x] 原始输入不可变归档；
- [x] legacy 严格审计与候选入口互不阻断。
