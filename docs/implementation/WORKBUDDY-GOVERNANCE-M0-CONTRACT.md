# WorkBuddy 日报治理 MVP：M0 合同决策

> 状态：Re-frozen for M1
> 日期：2026-08-13
> 对应计划：`docs/plan/invest-infra-workbuddy-daily-report-governance-mvp-plan-v1.0.md`
> 生产规则：`WORKBUDDY-REPORT-RULES.md` 1.1.2

## 1. M0 边界

本文冻结治理工具进入 M1 前必须确定的输入、状态、版本、归档和 CLI 合同。本文不授权或实现校验器、数据库、API、Web 或调度。

## 2. 支持版本与输入

首个受支持规则版本固定为：

```text
report_rules_version = 1.1.2
```

输入目录必须提供本次运行对应的三个逻辑角色：

```text
result JSON
report Markdown
quality report JSON
```

文件名和时间后缀不是治理正确性的硬门槛。治理器优先识别规范名称，同时允许 CLI 显式指定三个文件；每个运行使用独立目录。治理器通过文件内容识别运行身份，不从文件名推导 `workflow_run_id`。生产者 manifest 不是输入合同的一部分。

`result.json` 必须提供以下核心字段，`report.md` 只需投影运行 ID、交易日和关键结果，`quality_report.json` 只需记录运行 ID、交易日和生产者自检总体状态：

```text
workflow_run_id
trade_date
report_rules_version
strategy_version
producer_status
```

`result.status` 兼容映射为 `producer_status` 并记 warning；不要求 `quality_report` 重复 `producer_status`。`sources`、`stages` 必须存在；存在评分、排名或候选结果时，对应的 `scores`、`ranking`、`candidates` 必须存在。`task_id`、模板版本、开始/结束时间、生产者 hash 和质量检查证据均为可选诊断字段。schema 接受简写 `1.0` 和规范命名空间形式，解析后统一为内部版本 `1.0`。

未知 `report_rules_version`、无法识别的 schema major version 或核心身份不一致是硬失败。历史报告不得用当前规则静默重解释。

## 3. 治理状态判定

状态优先级固定为：

```text
rejected > partial > accepted
```

| 条件 | 治理状态 |
|---|---|
| 任一结果真实性硬检查失败或版本不受支持 | `rejected` |
| 所有硬检查通过，但存在按合同披露的必需数据缺失 | `partial` |
| 所有硬检查通过，且必需数据完整 | `accepted` |

生产者状态只作为事实记录。生产者 `succeeded` 不构成治理通过证据；生产者 `failed_validation`、`failed_execution` 或 `needs_rule_confirmation` 不能得到 `accepted`。

## 4. 硬检查与状态矩阵

以下检查任一失败均产生 `rejected`：

- 三件套存在、UTF-8、JSON 可解析；
- schema major version 可识别且规则版本受支持；
- 跨文件核心身份和关键结果一致；
- 阶段计数、集合互斥、集合并集和阶段衔接成立；
- 缺失数据未被评分或纳入完整排名；
- 评分输入、公式、权重和综合分在容差内可复算；
- 排名按综合分降序，同分按稳定主体键升序；
- 候选状态与排名规则一致；
- Override 在运行前批准、条件可计算且实际命中；
- `source_ref` 均能解析到来源定义；
- `verified` 来源的原始文件存在且 hash 可复算；
- Markdown 的运行 ID、交易日、候选主体、综合分、排名和候选状态与 JSON 一致；生产者状态如被展示则必须一致；
- 覆盖率名称、分子、分母、scope 和 rate 可复算；
- 治理侧能够独立读取并计算 `result`、`report` 的 size/hash。

以下条件仅在所有硬检查通过时产生 `partial`：

- `missing_data_symbols` 非空；或
- 任一必需维度明确标记 `dimension_status=missing`，对应 `score=null`、`overall_score=null`、`ranking_status=incomplete`。

以下生产者格式或自检瑕疵记 warning，不改变治理状态：

- 文件名不规范或缺少时间后缀，但运行目录独立且文件角色明确；
- schema 使用兼容简写；
- 使用 `template_version` 别名；
- Markdown 未重复非核心追溯字段；
- 生产者质量报告证据过于简略、检查未执行却标记通过，或生产者 hash 摘要错误；
- 生产者质量报告缺少 hash；
- `quality_report` 缺少重复的 `producer_status`、task/template/time 字段；
- 附加 coverage 或说明字段无法复算，但不影响候选、评分和排名事实。

治理器始终独立复算，不能用 warning 掩盖结果 JSON、Markdown关键结果或治理侧 hash 的真实冲突。

## 5. 阶段与缺失合同

每个阶段的主体集合必须满足：

```text
len(input_symbols) = len(passed_symbols) + len(rejected_symbols) + len(missing_data_symbols)
```

治理器根据集合自行计算各数量。生产者提供的 count 字段只作 warning 级交叉检查，不是额外硬门槛。

三个输出集合必须两两无交集，并集必须等于输入集合。上一阶段 `passed_symbols` 必须等于下一阶段 `input_symbols`。同一集合内不允许重复主体。

## 6. 评分与 Override

治理器不内置一套跨策略通用评分公式。受支持策略只需提供实际重算所需的最小合同：

```text
formula
weights
normalization
missing_value_behavior
ranking_tie_breaker
candidate_status_rule
```

`sector-seven-step-v2` 首版兼容合同冻结为：

- 归一化集合为 `stage_scoring.input_symbols` 对应的完整评分主体；
- 各维按样本声明的 min-max 尺度计算，`max == min` 时该维统一记 `0`；
- 使用未舍入维度值计算综合分，治理比较绝对容差为 `0.01`；
- 排名按综合分降序，同分按原始 `sector_id` 升序；
- 多板块命中允许存在，但同一主体在同一板块内不得重复计数；
- 候选状态按策略声明的 Top N 规则复算；
- 主体键使用原始 `sector_id`，不要求治理器进行名称规范化。

Override 默认禁用。`overrides=[]` 是首个可实施合同；启用任一 Override 前必须另行冻结规则 ID、版本、布尔条件、允许绕过项、必需字段和运行前批准证据。

## 7. 归档合同

所有治理结果统一写入：

```text
<root>/runs/<trade_date>/<workflow_run_id>/
```

不建立第二套 `rejected/` 事实目录。状态记录在 `governed-quality-report.json` 和治理 manifest 中。

`<trade_date>` 必须严格匹配 `YYYY-MM-DD` 且为真实日历日期；`<workflow_run_id>` 必须以 ASCII 字母或数字开头，长度 1–128，仅允许 ASCII 字符集 `[A-Za-z0-9._-]`。安全的普通点号（如 `wr.001`）允许；单独的 `.`、`..`、以 `.` 开头的形式（含 `.hidden`）、路径分隔符（`/`、`\`）、空白、控制字符与超长字符串一律在校验器边界 fail-closed（`input_error`），archive 模块再冗余校验一次以防止直接调用绕过。任何被拼接进归档路径的字段都不允许从非受信任输入直接构造。

导入协议：

1. 在 `runs/<trade_date>/` 内创建同文件系统临时目录；
2. 复制三件套并生成治理报告；
3. 重新读取全部归档文件，生成治理 manifest；
4. 完整校验后原子 rename 为最终 run 目录；
5. 目标已存在且内容 hash 完全一致时返回幂等成功；
6. 目标已存在但内容不同则拒绝，绝不覆盖；
7. 仅最终状态为 `accepted` 时更新 latest 指针。

并发导入以最终目录的原子创建/rename 决胜；失败进程清理自己的临时目录，不修改已完成归档。

## 8. latest 指针合同

`latest-accepted.json` 是全局最新合格运行指针，至少包含：

```text
schema_version
trade_date
workflow_run_id
relative_run_path
governance_status
governed_report_sha256
manifest_sha256
updated_at
```

排序键固定为 `(trade_date, finished_at, workflow_run_id)`。只有候选排序键严格大于现有指针时才允许更新，导入旧交易日不得让指针倒退。指针在治理根目录内通过临时文件、fsync 和原子 replace 更新。

## 9. CLI 合同

```text
python -m invest_pipeline.workbuddy_reports validate --source-dir <dir>
python -m invest_pipeline.workbuddy_reports import --source-dir <dir> --root <root>
```

stdout 固定输出一个 JSON 对象；诊断日志写 stderr。`validate` 不修改源目录或治理目录。

退出码：

| 退出码 | 含义 |
|---:|---|
| 0 | `accepted`，或 import 幂等成功 |
| 2 | `partial` |
| 3 | `rejected` |
| 4 | 输入/参数/不支持版本错误 |
| 5 | 归档冲突或 I/O 失败 |

`import` 对 `partial` 和 `rejected` 仍保存不可变治理归档，但不更新 latest 指针。

## 10. 2026-08-13 遗留样本基线

样本：`result/report/quality_report_2026-08-13_194500`。

预期总状态：`rejected`。至少应识别：

1. `report_rules_version=1.1.0`，不属于首个受支持的 1.1.2 合同；
2. 质量报告和 Markdown 仍要求、引用生产者 manifest；
3. `source_refs` 中存在把整个 Python 对象字符串拼入 ID 的 `src_sector_{...}`，且样本未提供可解析的来源定义集合；
4. 生产者自检证据模糊和 manifest 引用作为 warning 记录，不单独构成 rejected。

该样本用于证明治理器不采信生产者自报的 14/14 通过。

规则 1.1.2 三件套作为 M1 golden candidate 的目标合同。2026-08-14 实盘核对发现现存 `sector_result_2026-08-13.json` 与 `sector_quality_2026-08-13.json` 仍声明 `report_rules_version=1.1.1`，因此当前真实样本必须按 unsupported version 拒绝，不能作为 1.1.2 golden fixture；需由 WorkBuddy 按 1.1.2 重新生成后再执行 accepted 回归。文件命名、schema 简写、模板字段别名、Markdown 非核心元数据缺失、`result.status` 兼容映射和 `qc_14` 摘要错误均按兼容/warning 处理；M1 必须独立复算其阶段、评分、排名、关键 Markdown 字段和 hash 后，才能由治理器输出最终 `accepted`。

## 11. M0 完成门槛

- [x] 输入、版本、治理状态和硬检查矩阵已定义；
- [x] 归档、幂等、并发、latest 和 CLI 合同已定义；
- [x] 遗留真实样本的预期拒绝 Finding 已固定；
- [x] `sector-seven-step-v2` 最小评分兼容合同已冻结；
- [x] 规则 1.1.2 golden candidate 的目标合同已确定；
- [ ] WorkBuddy 已按 1.1.2 重新生成可供 accepted 回归的真实三件套；
- [x] 用户授权收缩并冻结 M0 合同。

M0 已完成，可以进入 M1；golden candidate 的 `accepted` 结论必须由 M1 独立校验器实际复算得出，不预先采信生产者结论。
