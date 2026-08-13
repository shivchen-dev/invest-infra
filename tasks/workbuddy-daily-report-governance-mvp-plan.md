# Implementation Plan: WorkBuddy Candidate Intake MVP

## Overview

将原“严格日报治理”降级收缩为“候选线索入口”。WorkBuddy 产出候选，`invest-infra` 负责映射、去重、数据补全、研究、评分、排名和发布。

## Architecture Decisions

- 候选入口与 legacy 报告审计是两个深模块，互不阻断；
- 生产端必需信息只包含运行身份、策略身份、候选 symbol 和 reason；
- 批次结构错误才拒绝整批，候选内容错误按项隔离；
- 原始输入不可变归档，标准化与后续研究结果另行存储；
- 不使用 legacy `accepted/partial/rejected` 或 `latest-accepted.json` 决定入池。

## Phase 1: Candidate Contract and Adapter

- [ ] Task 1：定义标准化 Candidate Intake DTO 和 item finding
- [ ] Task 2：解析生产规则 2.0.0 候选 JSON
- [ ] Task 3：从 1.1.1 / 1.1.2 三件套兼容提取 candidates

### Checkpoint

- [ ] 评分、ranking、stages、source refs 缺失不阻断候选提取
- [ ] 单个坏候选不阻断整批

## Phase 2: Archive, Resolution and Deduplication

- [ ] Task 4：实现原始候选 artifact 不可变归档
- [ ] Task 5：实现 run 幂等和同 ID 不同内容冲突保护
- [ ] Task 6：实现 symbol resolution 和 `(trade_date, strategy_id, normalized_symbol)` 去重
- [ ] Task 7：投影至投研系统候选池

### Checkpoint

- [ ] 无法映射 symbol 标记待确认，不回写生产文件
- [ ] 重复导入幂等，冲突不覆盖

## Phase 3: Real-sample Acceptance

- [ ] Task 8：用现有 1.1.1 真实样本验证候选提取
- [ ] Task 9：用 2.0.0 最小样本验证生产端新合同
- [ ] Task 10：运行 focused 和 Pipeline 回归，复核完整 diff

## Risks and Mitigations

| 风险 | 控制 |
|---|---|
| symbol 口径不一致 | 保留 raw symbol，投研系统集中映射 |
| AI 输出个别脏数据 | item-level 隔离，不拒绝整批 |
| 严格审计再次成为前置 | 模块和状态机彻底分离 |
| 原始输入被清洗覆盖 | raw archive 不可变，标准化结果另存 |
