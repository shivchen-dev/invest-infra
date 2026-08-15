# Strategy 交付物最小自动摄取与归档执行清单

对应计划：`tasks/strategy-artifact-ingestion-archive-mvp-plan.md`

## Task 1：归档合同与路由

- [x] 冻结 processing/archive/failed 组合包目录结构。
- [x] 冻结 `manifest.json` 最小字段及逐文件 SHA-256 规则。
- [x] 冻结 `validation-record.json` 状态、诊断和校验报告引用。
- [x] 冻结 Phase A/B 显式校验路由及未知类型 fail-closed 行为。
- [x] 建立成功、失败、缺任务、未知类型最小 fixture。

## Task 2：strategy 组合包处理器

- [x] 复用 StagePackageWorker 的安全路径和原子 rename 约束。
- [x] 实现匹配 task/result 的组合认领。
- [x] 实现 processing/archive/failed 目标冲突保护。
- [x] 覆盖缺任务、身份错配、symlink、claim/finish 冲突测试。

## Task 3：校验与归档证据

- [x] 接入 `validate_strategy_delivery.py`。
- [x] 接入 `validate_strategy_proposal.py`。
- [x] 生成宿主机 `validation-record.json`。
- [x] 生成覆盖任务和结果原件的 `manifest.json`。
- [x] 校验失败或异常时保留原件并进入 failed。
- [x] 覆盖 Phase A/B 成功、损坏、hash 错误和异常测试。

## Checkpoint A：文件级闭环

- [x] focused tests 通过：归档处理器与 CLI 测试通过。
- [x] pipeline Ruff 通过：`uv run ruff check src tests` 通过；全量测试通过。
- [x] 成功/失败 fixture 证据包完整且不可覆盖。
- [x] ARC 完整 diff 审核确认没有数据库或审批越权。

验收记录（2026-08-15）：全量 `pytest` 为 `2380 passed, 1 skipped`；归档代码与测试已
独立检查，真实共享根的两份 `-0003` 包 manifest 哈希一致。全仓库 `ruff format
--check` 仍受既有未格式化文件影响，但不影响本次既有提交的 Ruff 规则检查；未对无关
文件做格式化。

## Task 4：单次 CLI 与恢复

- [x] 提供显式共享根的单次扫描入口。
- [x] 提供 processing 残留恢复入口。
- [x] 输出 per-task 确定状态和进程退出码。
- [x] 覆盖空目录、混合结果、重复执行和恢复测试。
- [x] 默认不启用后台循环、Dagster 或 systemd。

## Task 5：遗留 Phase A 重放

- [x] 记录处理前 inbox/results/archive/failed 清单和 hash。
- [x] 用副本 dry-run 四个成对 Phase A 包。
- [x] 经用户授权后正式处理四个成对包；其中 2 个通过进入 archive，2 个因生产包合同错误进入 failed。
- [x] 验证 2 个归档包 manifest 与实际文件 hash 一致；2 个失败包保留 validation record。
- [x] 二次运行验证幂等；仅孤立结果继续报告 `missing_task`。
- [x] 孤立 `strategy-tdx-main-force-20260814-2350` 保持不动并报告 skipped/orphaned。

处理结果：四个输入包均已被 Worker 确定性处理；“四包全部进入 archive”未成立，原因是其中两个生产包自身不符合当前 Phase A 合同，未被降级归档。

## Checkpoint B：首版完成

- [x] strategy 文件级自动摄取与归档闭环成立。
- [x] archive/failed 原始材料及诊断可重放、可复核。
- [x] 未宣称数据库摄取、正式策略版本或 CIA 审查完成。
- [x] 周期调度、数据库入库和其他 stage 保持未实施。

首版验收结论：已完成文件级自动归档 MVP。当前仍有一个缺少匹配任务包的孤立结果
`strategy-tdx-main-force-20260814-2350.ready`，Worker 按 fail-closed 规则保持其原位
并报告 `missing_task`，不纳入首版成功包数量。
