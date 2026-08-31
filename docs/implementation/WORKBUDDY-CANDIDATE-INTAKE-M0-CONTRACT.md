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

`candidates.json` 是当前唯一权威入口；`.ready` 包只携带 `candidates.json` 与
`manifest.json`，不新增 `lineage.json` 或第二套 artifact 合同。两阶段策略身份与
`StageResult` 证据嵌入在 `candidates.json` 顶层 `lineage` 字段中。

## 2. 入口硬门槛

只有下列问题可以阻断整批导入：

- 文件不是可解析 JSON；
- `workflow_run_id`、`trade_date`、`strategy_id`、`status`、`candidates` 缺失或类型错误；
- `trade_date` 不是真实的 `YYYY-MM-DD`；
- `workflow_run_id` 不符合安全单路径段要求；
- 同一运行 ID 以不同内容重复导入；
- 顶层 `lineage` 存在但形态、阶段顺序、hash/身份/as-of/上下游绑定不符合本合同的 §8。

单个候选缺少非空 `symbol` 或 `reason` 时，只拒绝该项并记录 finding，不影响同批其他项。
当 `lineage` 存在但某个候选缺少或错填 `terminal_stage_result_id` /
`terminal_stage_result_sha256` 时，仅拒绝该项；同批合法候选继续被接受。

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
lineage        // 规范化两阶段 lineage；旧 2.0.0 payload 读取时为 null
```

原始候选 JSON 按运行不可变归档。外部候选准入不使用 `latest-accepted.json`，也不依赖 legacy 报告审计的 `accepted/partial/rejected` 状态。

## 6. 兼容边界

- 生产规则 `2.0.0` 是当前唯一候选入口合同；
- `1.1.1` / `1.1.2` 三件套不再兼容、不再验收，也不再作为当前 Gate 的依赖；
- `workbuddy_reports` 及其 legacy 审计合同仅保留为历史资料，不属于当前生产路径；
- 旧 2.0.0 payload（顶层不带 `lineage`）继续可读，parser 返回 `lineage=None`，不允许
  从 `strategy_id`、文件名、Markdown、环境变量、网络或前端常量推断 lineage。

## 7. M0 验收

- [x] 2.0.0 最小候选 JSON 可导入（纯 Python API）；
- [x] legacy 1.1.x 三件套明确移出当前入口与验收范围；
- [x] 一个坏候选不阻断其他合法候选；
- [x] 重复导入幂等，同 run ID 不同内容冲突拒绝；
- [x] 原始输入不可变归档；
- [x] legacy 严格审计与候选入口互不阻断；
- [x] 顶层 `lineage` 合法时规范化两阶段 stage 与候选 terminal 引用；
- [x] 顶层 `lineage` 缺失或为 `null` 时旧 payload 读回，`lineage=None`；
- [x] lineage 形态、阶段顺序、hash/身份/as-of/上下游绑定错误均触发稳定原因
      `invalid_lineage_shape` / `invalid_stage_order` / `strategy_identity_mismatch`
      / `as_of_mismatch` / `upstream_binding_mismatch` 之一的 batch 级 `ValueError`，
      不泄露宿主机路径、原始异常、凭据或 raw payload；
- [x] 候选 terminal 错配仅影响该候选（item 级 `candidate_terminal_mismatch`
      finding），不阻断同批合法候选。

## 8. 两阶段 lineage 合同（顶层 `lineage` 可选）

`candidates.json` 顶层可携带 `lineage`，schema 版本为 `candidate-lineage/1.0`。lineage
为缺失或 `null` 时视为旧 2.0.0 payload；其他形态错误必须以 batch 级 `ValueError`
拒绝整批。

### 8.1 顶层结构

```text
lineage.schema_version = "candidate-lineage/1.0"
lineage.stages         = [stage_0, stage_1]   // 严格 2 个有序 stage
```

- `stage_0.stage_key = "sector_selection"`（板块强度）
- `stage_1.stage_key = "stock_screening"`（个股筛选）

任何缺字段、错字段、错顺序、错长度、错 schema 版本均视为 `invalid_lineage_shape`
或 `invalid_stage_order`。

### 8.2 每个 stage 必填字段

```text
stage_key                // 必须等于该 stage 在 stages 中的预期 key
stage_result_id          // 非空；符合安全单路径段（与 workflow_run_id 同规则）
stage_result_sha256      // 64 位小写十六进制
strategy_key             // 非空字符串
strategy_version         // 非空字符串
strategy_artifact_hash   // 64 位小写十六进制
as_of                    // 非空字符串；与对端 stage 完全一致
```

`stage_result_id` 必须与现有 `workflow_run_id` 同享 `_RUN_ID` 规则
（`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`），不接受路径分隔符或穿越段。
`stage_result_sha256` / `strategy_artifact_hash` 必须是 64 位小写十六进制。
缺失、空串、非法格式或不安全 ID 触发 batch 级 `strategy_identity_mismatch`。

### 8.3 板块阶段附加字段（`sector_selection`）

```text
constituent_snapshot_sha256   // 64 位小写十六进制
```

### 8.4 个股阶段附加字段（`stock_screening`）

```text
upstream_stage_result_id       // 非空；安全单路径段；必须 === stage_0.stage_result_id
upstream_stage_result_sha256   // 64 位小写 hex；必须 === stage_0.stage_result_sha256
```

`upstream_stage_result_id` 同样必须满足 `_RUN_ID` 安全单路径段规则，与 §8.2
`stage_result_id` 同享同一身份白名单。任一上游绑定缺失、空串、不安全 ID 或与
`stage_0` 不一致触发 batch 级 `upstream_binding_mismatch`。

### 8.5 候选 terminal 引用

```text
candidate.terminal_stage_result_id      // 必须 === stage_1.stage_result_id
candidate.terminal_stage_result_sha256  // 必须 === stage_1.stage_result_sha256
```

候选缺字段或错配时只影响该候选，触发 item 级 `candidate_terminal_mismatch` finding；
同批合法候选继续被接受。

### 8.6 as-of 一致性

`stage_0.as_of` 与 `stage_1.as_of` 必须完全一致；否则触发 batch 级 `as_of_mismatch`。

### 8.7 旧 2.0.0 读回语义

- 顶层 `lineage` 缺失或 `null`：`CandidateIntakeResult.lineage = None`，其他字段
  与现有 2.0.0 行为完全一致。
- 顶层 `lineage` 形态合法：parser 同时校验 candidates 的 terminal 引用；其他
  已知/未知候选字段（含 `score`、`reason`、第三方扩展）继续原样保留在
  `CandidateItem.raw` 中，schema 与字段名不动。
- 旧 2.0.0 payload 不允许通过 `strategy_id`、文件名、Markdown、环境变量或网络
  来源反推 lineage；projection 与 Bridge 也不允许在不存在的 lineage 上猜测
  stage identity。

### 8.8 错误原因稳定性

`ValueError` 的 reason 字符串必须取自以下集合，且不含宿主机路径、原始异常、
凭据或 raw payload 正文：

```text
invalid_lineage_shape
invalid_stage_order
strategy_identity_mismatch
as_of_mismatch
upstream_binding_mismatch
candidate_terminal_mismatch
```
