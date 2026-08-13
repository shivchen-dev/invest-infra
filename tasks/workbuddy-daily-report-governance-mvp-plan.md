# Implementation Plan: WorkBuddy Daily Report Governance MVP

## Overview

在现有 Pipeline 中增加一个无数据库依赖的日报治理模块，独立校验 WorkBuddy 三件套、生成治理质量报告、不可变归档运行，并维护最新合格版本指针。

## Architecture Decisions

- WorkBuddy 是结果生产者，`invest-infra` 是治理结论 owner。
- 首期只实现校验、归档和 latest 指针。
- 校验器采用纯函数设计，源文件只读。
- 只有 `accepted` 可更新 `latest-accepted.json`。
- 不新增第三方依赖，除非实现时确认标准库无法满足冻结合同。
- 规则版本采用显式兼容矩阵：`COMPATIBLE_RULES_VERSIONS = {"1.1.1", "1.1.2"}`；
  不在矩阵内的版本一律 `unsupported_version`（exit 4）。

## Phase 1: Contract and Validator

- [x] Task 1：冻结输入合同、治理状态、评分和 Override 规则
- [x] Task 2：实现结构、阶段和来源校验
- [x] Task 3：实现缺失值、评分、排名和 Markdown 一致性校验
- [x] Task 4：生成 governed quality report

### Checkpoint: Validator

- [x] 2026-08-13 真实样本的已知问题全部被识别
- [x] 校验过程不修改源目录
- [x] focused tests 通过
- [x] `COMPATIBLE_RULES_VERSIONS` 显式矩阵覆盖 1.1.1 / 1.1.2，1.1.3 / 2.0.0 fail-closed

## Phase 2: Archive and Index

- [x] Task 5：实现完整 hash 和 manifest
- [x] Task 6：实现不可变归档及重复导入幂等
- [x] Task 7：实现 accepted-only latest 指针原子更新
- [x] Task 8：提供 validate/import CLI

### Checkpoint: Archive

- [x] 同日多次运行不覆盖
- [x] partial/rejected 不更新 latest
- [x] 同 run ID 不同内容被拒绝
- [x] focused tests 通过

## Phase 3: Acceptance

- [x] Task 9：真实样本 opt-in 回归（环境变量 `WORKBUDDY_REAL_SAMPLE_DIR`）
- [x] Task 10：运行 Pipeline 相关回归测试并复核完整 diff

### Checkpoint: Complete

- [x] MVP Definition of Done 全部满足
- [x] 未引入数据库、API、Web、Dagster 或 ExternalObservation
- [x] 真实 1.1.1 样本不再因版本号被单独拒绝；最终 accepted/partial/rejected 仍由内容校验决定
- [x] 默认测试不依赖仓库外路径；ARC 手工 CLI 验收仍受支持

## Risks and Mitigations

| 风险 | 影响 | 控制 |
|---|---|---|
| WorkBuddy 字段继续变化 | 校验器频繁失效 | 冻结合同版本，未知版本拒绝 |
| Markdown 自由文本难以稳定解析 | 一致性误报 | 只校验固定结构字段 |
| 主观评分无法复算 | 治理结果不可信 | 主观项不得作为硬条件 |
| 归档半途失败 | 产生不完整运行 | 临时目录完成后原子 rename |
| 现有工作树有其他改动 | 误覆盖用户工作 | 仅修改本任务文件，验收完整 diff |
| 真实样本 1.1.1 / 1.1.2 状态混淆 | 拒绝本应接受的真实样本 | 显式兼容矩阵 + opt-in 真实样本回归 |

## Open Questions Before Implementation

- 治理根目录环境变量名在 M1 CLI 实现前确定；CLI 显式 `--root` 是首要合同，不阻断 M0。

## M0 Decision Record

- 合同文件：`docs/implementation/WORKBUDDY-GOVERNANCE-M0-CONTRACT.md`；
- 兼容规则版本：`COMPATIBLE_RULES_VERSIONS = {"1.1.1", "1.1.2"}`（PATCH/MINOR/MAJOR 策略）；
- `SUPPORTED_RULES_VERSION = "1.1.2"`（冻结目标合同）；
- Override 首版默认禁用；
- 所有治理状态统一归档到 `runs/`；
- 2026-08-13 19:45 遗留四件套固定为 rejected regression fixture（声明历史 1.1.0）；
- 1.1.1 真实样本不再因版本号被单独拒绝；最终 accepted/partial/rejected 由内容校验决定；
- 真实样本回归采用 opt-in `WORKBUDDY_REAL_SAMPLE_DIR`，默认测试不依赖仓库外路径；
- 生产格式瑕疵进入兼容层/warning，只有结果真实性冲突才 rejected；
- M1/M2 收口补丁：`trade_date` 强约束为严格 `YYYY-MM-DD` 且必须是真实日期，
  `workflow_run_id` 必须以字母或数字开头，仅允许安全单路径段字符（`[A-Za-z0-9._-]`，长度 1–128）；
  校验器为 fail-closed 边界，archive 侧冗余再校验一次以防止直接调用绕过。
