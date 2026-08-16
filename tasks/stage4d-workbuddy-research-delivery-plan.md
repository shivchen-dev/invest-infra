# Stage 4D WorkBuddy 研究交付链实施计划

## Overview

把 WorkBuddy 从“能访问投研 API”推进到“能产生可验证交付物并进入投研 ResearchCase/ResearchResult”。唯一交接面是 Windows 容器默认共享目录：WorkBuddy 使用 `Z:\...`，投研系统宿主机使用 `/home/claw/windows-ltsc/shared/...`。完成信号以交付物、校验和入库状态为准，不以 Gateway 状态或最终响应帧为准。

## Architecture decisions

- WorkBuddy 只接收研究任务、只读 API 和交付物合同，不接触投研内部队列、租约和 Gateway 状态机。
- `result.json` + `report.md` 是最小交付物；成功、部分成功、无数据和失败都必须结构化落盘。
- 原始交付物不可变归档，摄取按任务 ID + 内容 hash 幂等。
- API 可达只是健康检查；有可用数据、交付物验证通过和 ResearchResult 入库才是逐级完成信号。
- 自动定时在人工垂直切片通过后启用。
- 长期治理只聚焦交付物生命周期、合同版本兼容、幂等追溯和单一共享根，不引入过度工程化组件。
- 共享目录按 `strategy/candidate/research/observation` 稳定阶段分区；每个阶段内部使用 `inbox/processing/results/archive/failed` 生命周期目录。
- 具体策略及版本只写入任务元数据，不为策略建立独立目录；旧单层 `inbox/results` 仅作迁移兼容。

## Shared-directory stage contract

```text
Z:\workbuddy\<strategy|candidate|research|observation>\<inbox|processing|results|archive|failed>\
```

宿主机观察相同相对路径：

```text
/home/claw/windows-ltsc/shared/workbuddy/<strategy|candidate|research|observation>/<inbox|processing|results|archive|failed>/
```

阶段与合同固定映射：

| Stage | Result contract |
|---|---|
| `strategy` | `strategy.json` + `strategy.md` + `validation.json` + optional `change-proposal.json` |
| `candidate` | `candidates.json` + `report.md` |
| `research` | `result.json` + `report.md` + `evidence.json` |
| `observation` | `review.json` + `report.md` |

所有执行任务必须携带 `task_id`、`stage`、`strategy_id`、`strategy_version` 和 `schema_version`。首次策略制定任务尚无正式版本时，必须携带稳定的提案身份和目标版本候选；目录负责物理路由，元数据负责策略身份和业务追溯。

## Task list

### Phase 0: Data foundation

- [ ] 确认 API 数据导入、数据库连接和 provider 配置。
- [ ] 让 `data-freshness`、ETF instruments、daily-bars 返回一个已知 ETF 的真实数据。
- [ ] 固化无数据状态为 `failed` 或 `blocked_no_data`，禁止伪成功。

Acceptance: `universe_count > 0`、`daily_bar_count > 0`，并能追溯 `as_of`、`trade_date`、`source_provider`。

### Phase 1: WorkBuddy task/result contract

- [ ] 冻结任务字段、只读接口、API 地址、时间范围和输出目录。
- [ ] 冻结 `result.json` / `report.md` 最小格式和错误分类。
- [ ] 固化 Z 盘路径与宿主机映射路径的代码/文档边界。
- [ ] 冻结四个阶段目录及其独立结果合同，停止新任务写入旧单层目录。

Acceptance: 不暴露凭据和宿主机路径；同一任务不会覆盖历史结果。

### Phase 2: Host-side artifact ingestion

- [ ] 发现完整结果包并执行 schema/hash/任务关联校验。
- [ ] 写入 ExternalArtifact / ExternalWorkflowRun，失败可重试。
- [ ] 成功、partial、failed、损坏和重复 fixture 均有确定结果。

Acceptance: 交付物成为唯一完成信号，重复扫描幂等，原始文件不可变归档。

### Phase 3: Real research vertical slice

- [ ] 发布一个已知 ETF 的实际研究任务。
- [ ] WorkBuddy 读取数据 API 并生成结构化报告。
- [ ] 摄取、验证身份/日期/来源，创建 ResearchCase、EvidencePack、ResearchRun 和 ResearchResult。

Acceptance: 全链路可由交付物、数据库记录和 hash 独立复核，不依赖 Gateway 最终响应。

### Phase 4: Scheduled operation

- [ ] 按阶段启用 WorkBuddy 定时取任务；strategy 阶段默认人工触发，不参与首批周期自动发布。
- [ ] 按阶段启用宿主机结果摄取定时任务。
- [ ] 监控 backlog、超时、无数据、失败、重复和未归档结果。

Acceptance: 连续两轮运行后，成功/无数据/失败均正确归档，重启不丢任务、不重复入库。

## Checkpoints

- After Phase 0: API 不仅可达，而且有可研究数据。
- After Phase 2: 交付物摄取和幂等成立。
- After Phase 3: 一个真实 ETF 研究任务完成 ResearchResult。
- After Phase 4: 才允许打开自动定时。

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| API 200 但数据库为空 | 伪成功 | P0 强制数据量和 freshness 门槛 |
| WorkBuddy 只写报告不写结构化结果 | 无法入库 | failed/partial 也必须写 result.json |
| 路径命名空间混用 | 任务不可见或结果误读 | 明确 `workbuddy_path` / `host_observation_path` |
| 重复扫描 | 重复 ResearchResult | task ID + content hash 幂等 |
| Gateway 无最终帧 | 错误判断失败 | 以结果目录和数据库状态为准 |

## Stop conditions

- Phase 0 未通过，不做真实投研结论验收。
- Phase 2 未通过，不开启自动定时。
- Phase 3 未通过，不宣称 WorkBuddy 已完成投研团队替代闭环。

## Minimal long-term governance

- [ ] 每个阶段的生命周期固定为 `inbox → processing → results → archive/failed`
- [ ] 已完成归档按保留期清理，但保留索引、hash 和入库记录
- [ ] 任务/结果使用显式 `schema_version`
- [ ] 同一主版本保持向后兼容，不兼容版本进入 failed
- [ ] `task_id + schema_version + content hash` 实现幂等追溯
- [ ] 不增加第二共享根，不静默切换目录
