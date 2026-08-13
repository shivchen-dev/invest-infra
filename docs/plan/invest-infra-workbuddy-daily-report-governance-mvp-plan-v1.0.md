# WorkBuddy 每日报告治理 MVP 实施计划

> 文档版本：v1.3
> 文档状态：Draft for Review
> 制定日期：2026-08-13
> 适用仓库：`invest-infra`
> 关联计划：Stage 4D Unified Investment Workbench
> 生产规则：`WORKBUDDY-REPORT-RULES.md` 1.1.1、1.1.2
> 实施原则：先解决校验可信、历史不覆盖和正式版本指向，不提前建设完整集成平台

## 1. 目标

在 `invest-infra` 中建立一个最小、独立、确定性的治理工具，管理 WorkBuddy 每日生成的：

```text
result.json
report.md
quality_report.json
```

治理工具完成三件事：

1. 独立校验 WorkBuddy 结果，不能采信生产者自报的质量结论；
2. 按交易日和运行 ID 不可变归档，每次重跑保留独立版本；
3. 仅在治理校验通过后更新 `latest-accepted.json`。

## 2. 明确非目标

本 MVP 不包含：

- PostgreSQL 表和 Migration；
- API、Web 页面和 Dashboard；
- Dagster Sensor 或常驻服务；
- ExternalObservation、Evidence 或 Research Case 转换；
- 月度索引和复杂检索；
- WorkBuddy 任务配置修改；
- 原始连接器响应的长期归档；
- 自动投资建议或交易。

这些能力仍属于 Stage 4D 后续范围，不作为日报治理第一步的前置条件。

本 MVP 生成的不可变治理归档是 Stage 4D 数据库投影、API 和 Web 展示的唯一准入输入。Stage 4D 不得直接消费未经治理的 WorkBuddy 生产目录；数据库只保存业务状态、结构化查询字段、逻辑 URI、hash、版本和关联，完整产物仍以本 MVP 的文件归档为权威源。

## 3. 职责边界

### WorkBuddy

- 调用连接器和生成数据；
- 输出结构化结果、Markdown 报告和生产者质量报告；
- 生成可关联同一次运行的 `workflow_run_id`；
- 不决定投研系统的最终治理状态。

### invest-infra

- 读取最终生成的最小三件套；
- 按三件套中冻结的 `report_rules_version` 选择受支持的质量合同；
- 独立执行确定性校验；
- 生成 `governed-quality-report.json`；
- 执行不可变归档；
- 维护最新合格版本指针。

## 4. 最小工作流

```text
WorkBuddy 三件套
→ invest-infra validate
→ governed-quality-report.json
→ archive 到 runs/<trade_date>/<workflow_run_id>/
→ 校验通过时原子更新 latest-accepted.json
```

治理结果只设三个状态：

```text
accepted   所有硬校验通过
partial    结构有效，但存在已披露的数据缺失
rejected   存在结构、计算、排名、来源或一致性错误
```

`partial` 和 `rejected` 均不得更新 `latest-accepted.json`。

生产者状态与治理状态分离：

- 生产者 `succeeded` 不自动等于治理 `accepted`；
- 独立硬校验全部通过且必需数据完整，治理状态为 `accepted`；
- 独立硬校验全部通过，但存在按规则披露的必需数据缺失，治理状态为 `partial`；
- 任一硬校验失败、未执行、规则合同不明确或规则版本不受支持，治理状态为 `rejected`。

`producer_status` 仅作为 `result` 输入事实记录，不得覆盖或直接决定 `governance_status`。旧报告的 `result.status` 可兼容映射为 `producer_status` 并记录 warning；不要求 `quality_report` 重复该字段。

### 4.1 规则版本兼容策略（PATCH/MINOR/MAJOR）

`report_rules_version` 采用 **显式兼容矩阵（set 查找）**，不做字符串范围比较。首版冻结 `COMPATIBLE_RULES_VERSIONS = {"1.1.1", "1.1.2"}`：

- **PATCH**（如 `1.1.1` → `1.1.2`）：共用同一最小事实合同，直接纳入 `COMPATIBLE_RULES_VERSIONS`；
- **MINOR**（如 `1.1.2` → `1.2.0`）：默认不进入兼容矩阵；必须由 WorkBuddy 升级 `WORKBUDDY-REPORT-RULES.md` 并经过 contract 重新冻结；
- **MAJOR**（如 `1.1.2` → `2.0.0`）：默认不进入兼容矩阵；必须建立新的治理合同；
- 不在矩阵内的版本一律 `unsupported_version`（exit 4）。
- 真实 1.1.1 样本不再因版本号被单独拒绝；其最终 `accepted` / `partial` / `rejected` 完全由内容校验决定。**不要求 WorkBuddy 必须按 1.1.2 重新生成才能进入 accepted 回归。**

## 5. 目录设计

治理根目录通过配置传入，不硬编码 Windows 或 Linux 绝对路径。

```text
<governance-root>/
├── runs/
│   └── YYYY-MM-DD/
│       └── <workflow_run_id>/
│           ├── result.json
│           ├── report.md
│           ├── quality_report.json
│           ├── governed-quality-report.json
│           └── manifest.json  # 仅由 invest-infra 治理侧生成
└── latest-accepted.json
```

`accepted`、`partial`、`rejected` 统一归档到 `runs/`，状态写入治理报告和 manifest，不建立第二套事实目录。

同一 `workflow_run_id` 重复导入时：

- 内容 hash 完全一致：返回幂等成功；
- 内容不同：拒绝导入，不覆盖原归档。

## 6. 硬校验范围

### 6.1 输入与合同

- 三个必需文件存在且为 UTF-8；
- JSON 可解析；
- `result` 的最小事实字段存在且类型正确；
- `workflow_run_id`、`trade_date`、`report_rules_version`、`strategy_version` 等核心身份一致；
- 出现的时间字段包含时区；
- 每个关键数据的 `source_ref` 均存在且指向已定义来源；
- `traceability_status=verified` 时，原始响应文件必须存在且 `raw_response_sha256` 可复算；
- `traceability_status=reported` 仅表示来源声明完整，不代表治理侧已独立验证来源内容。

首期可用轻量 Python 校验，不要求立即引入新的 Schema 依赖。合同稳定后再决定是否引入 JSON Schema 库。

每次校验必须使用三件套中冻结的 `report_rules_version`，不得默认套用当前最新版规则重新解释历史报告。治理工具不支持该规则版本时，结果为 `rejected`，并明确报告不支持的版本。

文件名、schema 简写、`template_version` 字段别名、Markdown 非核心元数据和生产者自检证据措辞不作为结果真实性硬门槛；治理器兼容解析并记录 warning。治理侧始终独立复算关键结果和 hash。

### 6.2 阶段一致性

对每个阶段独立验证：

```text
len(input_symbols) = len(passed_symbols) + len(rejected_symbols) + len(missing_data_symbols)
passed_symbols、rejected_symbols、missing_data_symbols 两两无交集
三集合并集等于 input_symbols
上一阶段 passed_symbols = 下一阶段 input_symbols
```

治理器根据主体集合自行计算各数量。生产者提供的 count 字段只作 warning 级交叉检查，不是额外硬门槛。

缺失数据标的不算淘汰，必须放入 `missing_data_symbols` 单列。

### 6.3 缺失数据

- 缺失维度必须为 `score=null`；
- 任一必需维度缺失时 `overall_score=null`；
- 缺失标的不得进入完整排名；
- 报告状态不得为 `accepted`。

### 6.4 评分与排名

- 按冻结公式重算单维分和综合分；
- 比较生产者值与治理重算值；
- 完整排名必须按综合分降序；
- 排名序号必须与排序结果一致；
- 主观解释不得直接作为硬淘汰条件；
- Override 只有命中预先配置的明确规则才有效，“原报告保留”不是合法理由。

### 6.5 报告一致性

首期只比对 Markdown 中的关键结果字段：

- 交易日和运行 ID；
- 候选代码、综合分、排名和候选状态；
- 若展示生产者状态，则与 `result` 一致。

不得以“由同一函数渲染”代替实际文件比对。
候选状态只允许使用生产规则定义的 `优先验证`、`继续观察`、`数据不足`、`规则未通过`。

### 6.6 Hash

- 对归档中的每个文件计算完整 SHA-256，即 64 个小写十六进制字符（256 bit）；
- `manifest.json` 保存文件名、字节数和 SHA-256；
- 不采信 WorkBuddy 截断或不可复现的 `result_hash`；
- `manifest.json` 最后生成，不将自身 hash 写入自身。

WorkBuddy 输入固定为 `result.json`、`report.md`、`quality_report.json` 三件套，不要求生产者 manifest。此处 `manifest.json` 是 invest-infra 对独立校验后的最终归档生成的治理 manifest。

## 7. 治理质量报告

`governed-quality-report.json` 至少包含：

```text
schema_version
workflow_run_id
trade_date
producer_status
governance_status
validated_at
checks[]
errors[]
warnings[]
recalculated_scores[]
file_hashes[]
```

`producer_status` 由 `result.producer_status` 或兼容的 `result.status` 得到；它不是从 `quality_report` 读取。治理报告中的 `file_hashes` 始终由治理侧独立生成。

每个检查项必须包含实际检查结果和证据，不允许使用“将在之后验证”或“理论上保证一致”等描述标记通过。

## 8. CLI 接口

首期只提供两个入口：

```bash
python -m invest_pipeline.workbuddy_reports validate --source-dir <dir>
python -m invest_pipeline.workbuddy_reports import --source-dir <dir> --root <governance-root>
```

`validate` 不写入治理目录，只输出校验结论；`import` 校验后归档，并在 `accepted` 时原子更新 latest 指针。

是否增加 Make 命令在实现阶段按仓库现有约定决定，不作为架构前提。

## 9. 实施阶段

### M0：合同冻结

- 以 `docs/implementation/WORKBUDDY-GOVERNANCE-M0-CONTRACT.md` 记录冻结决策；
- 冻结所需输入字段、治理状态和检查项；
- 冻结受支持的 `report_rules_version` 及对应校验合同；
- 冻结评分公式及合法 Override 规则；
- 使用 2026-08-13 真实样本定义预期失败项。

停止条件：实际重算所需的公式、权重、归一化集合、数值容差、排名规则或 Override 规则未明确前，不实现对应策略的评分重算。

### M1：独立校验器

- 实现输入、阶段、缺失、评分、排名、来源和 Markdown 一致性校验；
- 生成 governed quality report；
- 不读取数据库，不修改源文件。

### M2：归档与 latest 指针

- 建立按交易日/run ID 的不可变归档；
- 生成 manifest；
- 实现重复导入幂等；
- 使用临时文件加原子 rename 更新 `latest-accepted.json`。

### M3：真实样本验收

- 用 2026-08-13 三件套执行回归；
- 应识别排名顺序、自报假校验、截断 hash、非法 Override 和覆盖率口径问题；
- 修正后的完整样本才能获得 `accepted`。

## 10. 测试范围

- 缺少任一输入文件；
- JSON 无法解析；
- run ID 或交易日不一致；
- 规则、策略或自动化模板版本不一致；
- `report_rules_version` 不受支持；
- 阶段数量错误；
- 阶段衔接错误；
- 缺失数据仍被评分；
- 综合分计算错误；
- 排名顺序错误；
- Override 无合法规则；
- Markdown 与 JSON 不一致；
- source reference 不存在；
- `verified` 来源的原始文件或 hash 不可复算；
- `reported` 来源未被误判为已独立验证；
- hash 完整且可复算；
- 同一运行重复导入；
- 同一运行不同内容冲突；
- partial/rejected 不更新 latest；
- accepted 原子更新 latest；
- 历史运行不被覆盖。

## 11. Definition of Done

- 当前真实样本能得到独立、可解释的治理结论；
- WorkBuddy 的自报质量状态不能覆盖治理结果；
- 每次运行按其冻结且受支持的 `report_rules_version` 可复现校验；
- 分数、排名和覆盖率由投研系统独立计算；
- 每个归档文件有完整 SHA-256；
- 同日多次运行均被保留；
- 只有 accepted 更新 `latest-accepted.json`；
- 重复导入幂等，内容冲突不会覆盖历史；
- focused tests 和 pipeline 现有相关测试通过；
- 不引入数据库、服务、调度和 UI。
- 治理归档包含 Stage 4D 数据库投影所需的状态、版本、逻辑路径和完整性信息。

## 12. Stage 4D 交接范围

以下能力由 Stage 4D 单独实施，不属于本治理 MVP：

- PostgreSQL 索引；
- Artifact Bridge 标准目录；
- Dagster 自动导入；
- API/Web 展示；
- ExternalObservation 转换。

本治理 MVP 完成不自动授权上述 Stage 4D 实施内容。
