# Strategy 交付物最小自动摄取与归档实施计划

## 1. 目标

为 `workbuddy/strategy` 分区建立首个可运行的文件级闭环：发现完整的
`results/<task_id>.ready`，原子认领任务与结果，按任务类型调用 Phase A 或
Phase B 校验器，生成投研系统侧的归档证据，并将成功包归档、失败包隔离。

首版解决交付目录持续堆积和手工移动易破坏追溯的问题。它只证明“交付包已由
投研系统校验并归档”，不创建 `StrategyProposal`、`StrategyVersion`，不写业务
数据库，也不代表 CIA 审查通过。

## 2. 范围

### 2.1 本期包含

- 仅扫描 `workbuddy/strategy/results/*.ready`；
- 同时认领匹配的 `inbox/<task_id>.ready` 和结果包；
- 识别 Phase A 能力评估及 Phase B 策略工程化任务；
- 调用现有两个阶段校验器，不重复实现 Schema 规则；
- 生成 `manifest.json` 和 `validation-record.json`；
- 成功进入 `archive/<task_id>/`，失败进入 `failed/<task_id>/`；
- 支持重复扫描、目标冲突、进程中断恢复和已验收遗留任务重放；
- 提供单次执行 CLI，周期调度另行授权。

### 2.2 本期不包含

- 数据库事务及领域对象入库；
- CIA/RAA 审批、正式策略版本创建或激活；
- candidate/research/observation 分区；
- Dagster/systemd 定时运行；
- 自动删除 archive、failed 或无匹配任务的孤立结果；
- 通用工作流引擎、消息队列或跨主机锁。

## 3. 权威状态流

```text
inbox/<task_id>.ready + results/<task_id>.ready
  -> processing/<task_id>/task + processing/<task_id>/result
  -> validator route
  -> manifest.json + validation-record.json
  -> archive/<task_id>/                 (校验通过)
     或 failed/<task_id>/               (校验失败)
```

完成信号是归档目录包含任务原件、结果原件、manifest 和 validation record，且
重新计算的 SHA-256 与 manifest 一致。WorkBuddy 的完成状态、目录出现或生产者
自带的 `validation-report.json` 均不能替代宿主机校验。

## 4. 关键设计决定

### 4.1 复用现有生命周期内核

复用 `StagePackageWorker` 的安全路径、`.ready` 发现、原子 rename 和目标冲突
保护。首个实现只为 strategy 增加组合包处理器和 CLI，不把 Phase A/B 业务规则
塞进通用 Worker。

### 4.2 任务与结果作为一个归档单元

结果认领后，匹配任务必须一并进入同一个 processing 包。缺失任务、任务身份不
匹配或目标目录已存在时不得猜测补全，也不得覆盖；保存诊断并进入 failed 或保持
待处理冲突状态。

### 4.3 校验路由最小化

从 `task/task.json` 的显式 schema/任务类型选择校验器：

- Phase A：`validate_strategy_delivery.py`；
- Phase B：`validate_strategy_proposal.py`。

未知类型 fail closed。Markdown 只检查合同要求的文件存在，不解析标题或正文。

### 4.4 归档证据由投研系统生成

`manifest.json` 至少记录：worker schema version、task ID、任务类型、处理时间、
校验器及版本标识、任务和结果文件相对路径、字节数、SHA-256。

`validation-record.json` 至少记录：校验状态、退出码、error/warning/review 摘要、
校验报告引用和处理结果。生产者自带报告作为原始结果保留，但不是归档决定依据。

### 4.5 幂等与冲突

- `archive/<task_id>` 已存在且 manifest 内容哈希一致：返回 `already_archived`，
  不覆盖、不重复归档；
- 同 task ID 但内容不同：返回 `archive_conflict`，保留现场等待人工处理；
- `failed/<task_id>` 已存在：不得覆盖，使用确定性冲突结果；
- processing 残留通过恢复命令检查结构后继续校验，不自动回滚为 ready；
- 任一状态转换使用同一共享根内的原子 rename，禁止先删源目录。

### 4.6 遗留任务重放边界

首批只重放已独立验收通过且任务/结果成对存在的四个 Phase A 包。旧
`strategy-tdx-main-force-20260814-2350` 缺少有效任务且属于
`legacy_unapproved/test_only/non_authoritative`，不得由 Worker 猜测归档，继续
保留为孤立测试材料，后续按显式处置决定处理。

## 5. 依赖顺序

```text
归档合同与校验路由
  -> strategy 组合包处理器
  -> manifest / validation record
  -> CLI 与恢复语义
  -> fixture 验收
  -> 四个遗留 Phase A 包重放
```

## 6. 实施任务

### Task 1：冻结归档合同与路由

定义组合包目录、manifest、validation record、Phase A/B 路由及错误分类。

Acceptance criteria:

- 每个 required 字段均对应身份、完整性、恢复或审计需求；
- 未知任务类型、缺失任务、身份不一致和不安全路径均有确定结果；
- 不把 Markdown 样式或业务结论设为归档硬门禁。

Verification:

- 最小成功、校验失败、缺任务和未知类型 fixtures 可表达；
- 治理文档审核清单逐项通过。

Dependencies: None.

Estimated scope: Small，合同文档和 fixture 定义。

### Task 2：实现 strategy 组合包处理器

在通用 Stage Worker 上组合任务与结果认领，完成安全路径、冲突和状态移动。

Acceptance criteria:

- 不覆盖 processing/archive/failed 现有目录；
- task/result 任一认领失败不会伪造成功归档；
- 所有归档路径仅由已验证 task ID 构造。

Verification:

- focused tests 覆盖成功、缺任务、身份错配、symlink、claim 冲突和 finish 冲突；
- `uv run ruff check src tests` 通过。

Dependencies: Task 1.

Estimated scope: Medium，处理器及单元测试。

### Task 3：接入校验器并生成归档证据

按显式任务类型调用 Phase A/B 校验器，保存宿主机校验结果，生成 manifest 和
validation record 后再完成 archive/failed 状态转换。

Acceptance criteria:

- 生产者报告不能替代宿主机校验；
- manifest 覆盖归档任务和结果的全部文件并可重新验证；
- 校验器异常、非零退出或报告损坏均进入 failed，原件不丢失。

Verification:

- focused tests 覆盖 Phase A/B 成功、JSON 损坏、hash 不匹配和校验器异常；
- 归档后逐文件重算 SHA-256 与 manifest 一致。

Dependencies: Tasks 1-2.

Estimated scope: Medium，路由/证据生成及测试。

### Checkpoint A：文件级闭环审核

- 所有 focused tests 和 pipeline Ruff 通过；
- 成功与失败 fixture 均形成完整、不可覆盖的证据包；
- ARC 独立检查完整 diff，确认未引入数据库或审批权限。

### Task 4：实现单次 CLI 与中断恢复

提供显式共享根、单次扫描和 processing 恢复入口；默认不启动后台循环。

Acceptance criteria:

- CLI 输出每个 task ID 的确定状态并以非零退出表示本轮存在硬失败；
- 重复运行成功包返回 `already_archived`；
- processing 残留只能经恢复路径继续，不被静默删除或覆盖。

Verification:

- CLI tests 覆盖空目录、混合成功/失败、重复执行和恢复；
- 帮助文本不暴露 Windows 容器内不可用的宿主机路径。

Dependencies: Task 3.

Estimated scope: Small，CLI 及测试。

### Task 5：遗留 Phase A 重放验收

先以副本 dry-run，再用正式 Worker 处理四个已验收修正包。

Acceptance criteria:

- 四个成对包进入 archive，inbox/results 不再保留对应活动目录；
- 每包均有可复核 manifest 和 validation record；
- 孤立旧测试结果不移动、不删除，并明确报告为 skipped/orphaned。

Verification:

- 对四个 archive 包重算哈希；
- 再运行一次不产生重复目录或内容变化；
- 对比处理前后目录清单，无未授权材料丢失。

Dependencies: Tasks 1-4 and Checkpoint A approval.

Estimated scope: Small，真实 fixture 验收。

### Checkpoint B：首版完成

- `results/*.ready` 的文件级处理闭环可重复执行；
- archive/failed 证据完整且原始材料可重放；
- 未声明数据库摄取、正式策略创建或 CIA 批准完成；
- 周期调度、数据库入库和其他 stage 继续保持未实施。

## 7. 风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| task/result 双目录移动中断 | processing 半包 | 分步状态记录，恢复命令只继续不猜测回滚 |
| 同 task ID 内容变化 | 覆盖历史 | 目标存在即比较 manifest；不一致返回 conflict |
| 校验器路由猜错 | 错误归档 | 仅根据显式合同标识路由，未知类型 fail closed |
| 生产者自检伪成功 | 不合格包归档 | 宿主机独立执行校验器并生成决定记录 |
| dirty worktree 混入实现 | 污染其他 Stage 4D 工作 | 编码代理只改计划列明文件，ARC 按 diff 和测试独立验收 |
| 首版被误称正式摄取 | 权威边界混乱 | 文档、CLI 状态和报告统一称 file-level validated archive |

## 8. 实施门禁

本计划经用户审核并明确授权实施后才进入编码。由于预计代码改动超过 10 行，编码
必须交由默认 OpenCode 编码代理执行，ARC 独立检查输出、完整 diff、测试和真实
目录重放。任何自动调度、数据库写入或孤立旧任务删除均需另行授权。
