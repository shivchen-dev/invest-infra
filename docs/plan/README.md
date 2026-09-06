# invest-infra 计划目录与轻量治理规则

> 生效日期：2026-08-18
> 适用范围：`docs/plan/`

本目录是计划入口，不是动态进度表。每条活动主线只保留一份权威实施计划；计划定义目标、边界、依赖和验收标准，Git、CI 与真实验收记录定义实际完成事实。

`tasks/` 下的历史任务包和执行拆分文件不再作为派工、进度或完成状态权威，也不再要求维护。

## 1. 当前执行权威

| 优先级 | 主线 | 治理状态 | 当前检查点 | 唯一实施计划 |
|---|---|---|---|---|
| P0 | 目标 Dataset 来源准入 | `ACTIVE` | `READY_FOR_DS-C0`；实施 Dataset 绑定并执行双次 shadow，生产准入仍待 Gate B2A | [`invest-infra-target-dataset-source-admission-plan-v1.0.md`](invest-infra-target-dataset-source-admission-plan-v1.0.md) |
| P1 | Stage 4D 研究交付收口 | `BLOCKED` | 等待 v2.1.0 策略治理及 Gate B2A | [`invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`](invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md)；前置切片见 [`invest-infra-candidate-strategies-mvp-plan-v1.0.md`](invest-infra-candidate-strategies-mvp-plan-v1.0.md) |

策略源、审核、数据获取与确定性执行的规范合同见 [`../governance/invest-infra-strategy-source-to-automation-workflow.md`](../governance/invest-infra-strategy-source-to-automation-workflow.md)，它不承担开发排期或动态进度。

## 2. 状态与事实来源

- `ACTIVE`：当前有效实施边界；阶段就绪度放在“当前检查点”，不新增治理状态。
- `BLOCKED`：计划仍有效，但不得实施阻塞 Gate 之后的任务。
- `CLOSED`、`DEFERRED`、`REFERENCE_*`：退出当前执行面，统一进入归档。
- 代码、CI/测试、独立验收和用户授权分别定义实现、验证、验收和范围事实；任一项不能替代其他项。

业务定位与架构边界以项目 [`README.md`](../../README.md) 和 [`../ARCHITECTURE-GOVERNANCE.md`](../ARCHITECTURE-GOVERNANCE.md) 为准，本索引不复制。

## 3. 计划变更规则

- 每条活动主线只保留一份权威实施计划；可独立验收的前置切片可单列，但必须由主计划引用。
- 新计划必须有明确输入、输出、非目标和 Gate，并说明替代、依赖或合并关系。
- 完成阶段的详细过程进入 `docs/validation/`；活动计划只保留完成摘要、证据指针和未完成工作。
- 活动计划完成必须有真实验收或明确关闭记录，不能由复选框、历史任务包或代理完成状态代替。
- `tasks/` 是历史执行拆分，不是派工、进度或完成状态权威。

## 4. 归档与未排期项

完成、延期和参考计划的状态、替代关系与路径见 [`archive/README.md`](archive/README.md)。归档文档不得直接恢复派工；恢复前必须重新形成活动计划并取得授权。

以下内容未排期：`strategy-iteration`、`position-discipline`、`decision-feedback-loop`。只有对应事实源和前置 Gate 完成后，才能单独授权。

## 5. 维护检查

每次计划变化必须核对页首状态、当前检查点、验收指针、归档替代关系和仓库内引用，并运行 Markdown 本地链接与 `git diff --check`。
