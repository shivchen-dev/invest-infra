# Stage 4D Gate 3：当前进度与自动化验证记录

## 1. 依据与范围

- 当前权威计划：`docs/plan/invest-infra-stage4d-mvp-phased-execution-plan-v1.0.md`
- 当前验收目标：`Observation → Admission → Evidence → Research Case → Research Run/Result → Research Workspace timeline`
- WorkBuddy 范围：当前 Candidate Schema 2.0.0；不包含 legacy 1.1.x 报告三件套
- JiuwenSwarm：按当前计划不再作为本阶段依赖或验收对象
- 验收时间：2026-08-26（Asia/Shanghai）

## 2. 已通过的自动化验证

### Pipeline

执行：

```bash
cd apps/pipeline
uv run --no-env-file pytest -q \
  tests/unit/test_workbuddy_research_artifacts.py \
  tests/unit/test_workbuddy_research_ingest_cli.py \
  tests/unit/test_workbuddy_stage_worker.py \
  tests/unit/test_workbuddy_shared_directory.py \
  tests/unit/test_external_research_handoff.py \
  tests/unit/test_research_context_projection.py \
  tests/unit/test_research_run_worker_cli.py
```

结果：`75 passed`。

Gate 3 核心聚焦测试另通过：`43 passed`，覆盖 Observation Admission、Fake ResearchRunner、Research Runtime、Orchestration 和 Research Run Worker。

### API

执行 Gate 3 Admission、Evidence、Research Run、Research Case 和 Workspace 相关测试，结果：`62 passed`，`1 warning`（Starlette/httpx 弃用提示，不影响断言）。

### Web

执行 Research Case、Workspace API、Research Run Timeline 相关入口；当前 Web 测试命令运行全量套件，结果：`28 files passed`、`216 tests passed`。

## 3. 当前能力确认

- 服务端 Admission 负责计算验证事实，客户端不提交验证布尔结论；
- Fake WorkBuddy → Orchestrator → Fake ResearchRunner 的成功/失败路径已有测试；
- Research Case 页面已展示发现、准入、Artifact、Evidence、Research Run/Result 时间线；
- `occurred_at` 缺失时页面明确显示时间未知；
- API OpenAPI 与 Web 生成客户端已同步。

## 4. 尚未完成的 Gate 3 项

以下项目仍不能标记为完成：

1. 使用当前有效的 WorkBuddy 2.0.0 Candidate 输入，完成一次真实的 Observation 准入后 Research Run/Result 手工联调；
2. 对应真实链路保留输入 hash、run/case/result 关联、执行命令和结果状态；
3. 完成 Gate 3 全量回归、构建和最终演示；
4. 补齐运行手册、架构说明与最终 Gate 3 验收记录。

旧的 1.1.x 报告样本和三件套不属于以上待办，不再追补、不再复验。

## 5. 全量回归

2026-08-26 复核结果：

- Pipeline：`2453 passed, 1 skipped`；
- API：`684 passed`，另有 1 条既有 Starlette/httpx 弃用 warning；
- Web typecheck：通过；
- Web 全量测试：`28 files passed`、`216 tests passed`。

## 6. 当前结论

**Gate 3 自动化验证通过，Gate 3 整体尚未完成。**

2026-08-26 已使用当前有效的真实 2.0.0 Candidate 归档执行重解析演练：

- `run_13e8593b12257afe` / `510300.SH`：`status=success`、`archive_idempotent=true`、`import_idempotent=true`；
- `run_dc1574b8250849a9` / `510500.SH`：`status=success`、`archive_idempotent=true`、`import_idempotent=true`；
- 两条 Observation 均已从 `needs_symbol_resolution` 转为 `pending_validation`，并关联现有 `core.instruments` UUID；
- payload、source URI、run/artifact identity 和 `admission_status=pending` 未被改写；
- 临时输入文件已清理，未生成新的 WorkBuddy 结果。

## 7. 真实 Admission 手工验收结果（2026-08-26）

使用仅监听本机 `127.0.0.1:8001`、开启 `STAGE4D_ADMISSION_COMMANDS_ENABLED=true` 的临时 API 进程，对上述两条真实 2.0.0 Observation 执行了服务端准入命令：

- `2033cf44-d331-52a6-8eb1-59b9e84c2462`（`510500.SH`）：`rejected`；`unit_ok=false`；
- `65027d0a-7679-55fd-88d7-8fa851522556`（`510300.SH`）：`rejected`；`unit_ok=false`。

两条候选原始 payload 均只有 `symbol` 与 `reason`，没有当前 Admission 合同要求的 `unit` 与 `definition`。服务端按计划规定拒绝缺少正式验证数据的观察，不从 `reason` 推断字段，也未创建 Evidence、ResearchCase 或 ResearchRun。该临时 API 进程已停止。

因此当前真实 Gate3 阻塞已明确为：需要 WorkBuddy 按当前 Candidate 2.0.0 合同重新产出包含可验证 `unit/definition` 的新候选 run；既有 rejected Observation 不回写、不重置。新 run 通过准入后再继续 Evidence → Research Case → Research Run/Result 手工联调；不是旧报告三件套缺失。
