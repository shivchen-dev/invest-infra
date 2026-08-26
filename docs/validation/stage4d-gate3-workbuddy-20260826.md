# Stage 4D Gate 3：真实 WorkBuddy 研究交付验收记录

## 1. 验收范围

- 验收对象：`task-20260824-1638-510300`
- WorkBuddy 任务类型：`research`
- 期望交付：同一 ready 包内的 `result.json`、`report.md`、`evidence.json`
- 正式成功信号：三文件通过 schema、哈希和任务关联校验后原子发布
- 验收时间：2026-08-26（Asia/Shanghai）

## 2. 现场事实

共享目录中发现：

```text
research/inbox/task-20260824-1638-510300.ready/task.json
research/inbox/task-20260824-1638-510300.ready/task.md
research/results/510300_data_report_v1.0_20260824.md
```

该报告包含真实任务标识、运行标识、数据截止时间、来源和数据限制，内容不是系统生成的 Fake 结果；但它是 `results/` 下的单独 Markdown 文件，不是任务要求的 ready 交付包。

## 3. 系统侧验证

现有手工导入入口：

```bash
apps/pipeline/.venv/bin/python -m invest_pipeline.workbuddy_research_ingest_cli \
  --bridge-root <shared-workbuddy-root> \
  --archive-root <immutable-archive-root>
```

该入口只接收 `research` 阶段的 ready 包，并调用 `ingest_research_artifact` 校验：

- `result.json` 是对象且 schema 为 `workbuddy.invest-result/1.0`；
- `report.md` 存在且其 SHA-256 与 `result.json` 一致；
- 任务 ID、状态、来源和必需字段满足合同；
- `evidence.json` 等交付内容完成后才允许归档。

因此，当前单独的 `510300_data_report_v1.0_20260824.md` 不能被合法导入，也不能据此创建正式 `ResearchResult`。未对共享目录执行改写或补包操作。

## 4. 验收结论

**真实 WorkBuddy 手工验收：未通过，状态为待补交付，不是系统故障。**

已确认真实研究内容存在；未确认正式研究结果闭环完成。依据当前合同，不能把这份 Markdown 报告包装成 `result.json` 或 `evidence.json`，也不能将 Gate 3 标记为完成。

## 5. 下一步

WorkBuddy 需要针对原任务补交并原子发布：

```text
research/results/task-20260824-1638-510300.ready/
├── result.json
├── report.md
└── evidence.json
```

补交后重新运行一次手工导入，验证归档、Research Run/Result 状态、Research Case 时间线和失败/重复导入行为；在此之前 Gate 3 仅完成 Fake 链路与系统侧准备，不能宣称 MVP 完成。
