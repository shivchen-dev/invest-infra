# invest-infra Stage 4A Final Closure Sprint 实施方案

> 文档版本：v1.1  
> 状态：Revised for Implementation  
> 基线：`3ebeedd` (`fix(web): resolve API host for LAN access`)  
> 目标：完成 Stage 4A 收尾验收，并为 Stage 4B 提供稳定输入契约

## 1. 结论与执行边界

Stage 4A 的核心领域能力已经落地：Research Case、Evidence Pack、Factor Observation、Research Run、Research Result、JiuwenSwarm Adapter 以及只读 Research API 均已有实现。

本 Closure Sprint 不重新设计 Stage 4A，不扩展市场智能 UI，不引入 `return_120d`，也不重新设计 Research API。工作重点是：

1. 校准领域契约与验收文档；
2. 验证 Evidence Pack 的幂等、Hash 和历史保留；
3. 修复全量测试收集问题；
4. 完成 Fake Runner 的应用层 E2E 和 API/Web 集成验证；
5. 冻结当前只读 API；
6. 输出 Stage 4A Final Acceptance 报告。

## 2. 当前代码基线

### 2.1 已确认能力

- Research Case 状态机：`draft → ready → running → completed / failed / cancelled`。
- Research Run 状态机：`queued → running → succeeded / failed / cancelled`，失败运行可 retry。
- Evidence Pack 使用 `pack_hash` 作为确定性业务内容 Hash。
- Evidence Pack 持久化使用 `content_hash` 幂等，历史不同 Hash 的 Pack 共存。
- Factor Observation 自动生成 `item_hash` 和 `evidence_id`。
- Research Result 独立保存，不修改 Evidence Pack。
- Result 发布前校验所有 Evidence ID 必须存在于当前 Evidence Pack。
- JiuwenSwarm SDK 位于 Pipeline Adapter 边界，Domain 不依赖外部 SDK。

### 2.2 当前验证结果

- Research API 聚焦测试：55 passed。
- JiuwenSwarm / Research Orchestration 聚焦测试：80 passed。
- Research Domain 聚焦测试：58 passed。
- Web typecheck/build：通过。
- Domain 全量测试当前存在测试收集错误，见 Task 1。
- Web Playwright 集成测试需要 API 服务同时启动；未启动 API 时会产生 `ERR_CONNECTION_REFUSED`，见 Task 5。

## 3. 冻结的 Evidence Foundation 契约

### 3.1 Factor Set

当前正式版本为 `etf_market_state_daily / 1.0.0`，共 8 个因子：

| Factor Key | Window | Unit |
|---|---:|---|
| `return_20d` | 20 | `ratio` |
| `return_60d` | 60 | `ratio` |
| `distance_ma20` | 20 | `ratio` |
| `distance_ma60` | 60 | `ratio` |
| `realized_volatility_20d` | 20 | `annualized_ratio` |
| `max_drawdown_60d` | 60 | `ratio` |
| `avg_turnover_amount_20d` | 20 | `CNY` |
| `data_completeness_60d` | 60 | `ratio` |

因子只描述确定性事实，禁止写入 buy/sell、stance、confidence、thesis 或其他 AI 结论。

本阶段明确不加入 `return_120d`，也不把代码中的完整因子名称简写成 `volatility`、`turnover` 或 `max_drawdown`。

### 3.2 Hash 与历史语义

- 相同业务输入必须生成相同 `pack_hash`。
- `pack_hash` 参与 Evidence ID 生成。
- 相同 `content_hash` 的重复写入为幂等操作。
- 不同业务内容产生新的 Pack，不覆盖旧 Pack。
- 历史版本通过 Pack ID、Hash、生成时间和 Source Reference 查询。
- 当前系统没有独立的 Evidence Pack `revision` 字段；本阶段不擅自新增该字段。验收文档中将“revision”定义为不同 Pack Hash 的历史版本，不伪造数据库 revision 语义。

## 4. 冻结的 Research API Contract

以下路径以当前实现为准，全部只读，不执行计算、不触发 Pipeline、不暴露 workspace 本地路径：

```http
GET /api/v1/research-cases
GET /api/v1/research-cases/{case_id}
GET /api/v1/research-cases/{case_id}/evidence
GET /api/v1/research-cases/{case_id}/workspace
GET /api/v1/research-runs
GET /api/v1/research-runs/{run_id}
GET /api/v1/research-runs/{run_id}/result
GET /api/v1/research-dashboard
```

契约约束：

- 列表接口使用 `limit` / `offset`，并返回 `total`。
- 资源不存在返回 404。
- 非法 UUID 返回 422。
- 查询异常对外只返回去敏后的 `Research query failed`。
- Evidence API 只返回公共 Evidence 字段，不返回 provider secret、数据库连接信息或本地路径。
- `/research-runs/latest`、`/evidence-pack`、`/items`、`/factors` 不作为本阶段新增路径。

## 5. Closure Sprint 任务

### Task 1：修复 Domain 全量测试收集

**目标：** 使仓库标准 Domain 测试命令可以完整收集并执行。

**验收标准：**

- [ ] `packages/domain/tests/test_research_run.py` 和 `test_research_runner.py` 不再依赖不稳定的顶层模块导入。
- [ ] `PYTHONPATH=packages/domain/src python3 -m pytest packages/domain/tests -q` 完整通过。
- [ ] 不改变 Research Domain 业务行为。

**依赖：** 无。  
**预计范围：** Small，仅测试文件。

### Task 2：Evidence Pack Hash、幂等与历史验证

**目标：** 证明相同输入不重复写入，不同业务内容保留历史 Pack。

**验收标准：**

- [ ] 相同输入的 `pack_hash`、Factor `item_hash`、Evidence ID 完全一致。
- [ ] 重复写入相同 `content_hash` 返回同一持久化 Pack。
- [ ] 修改业务事实后产生新的 Pack Hash 和 Pack ID。
- [ ] 旧 Pack 仍可通过 `list_by_case` 查询。
- [ ] Provider request/session/path 等运行元数据不参与业务 Hash，除非契约明确要求。

**验证：** Domain Hash 测试、Storage mock 测试、PostgreSQL integration 测试。  
**依赖：** Task 1。  
**预计范围：** Medium，Domain/Storage 测试及必要的缺陷修复。

### Task 3：Factor Snapshot 与确定性/AI 分离验收

**目标：** 固化 8 个实际因子，并证明 AI 结果不能改变 Evidence。

**验收标准：**

- [ ] Evidence Pack 恰好包含上述 8 个 Factor Key，每个因子带 unit、window、observed_date、quality_status、source_ref、evidence_id。
- [ ] 因子计算不产生投资结论字段。
- [ ] Research Result 仅保存 conclusion、risks、evidence_ids、report_markdown 及模型/Playbook/Adapter 版本。
- [ ] 修改 Research Result 不会改变原 Evidence Pack Hash 或 Evidence ID。
- [ ] 不引入 `return_120d` 或因子别名。

**依赖：** Task 2。  
**预计范围：** Small/Medium，Domain/API 测试。

### Task 4：Fake Runner 应用层 E2E

**目标：** 验证不依赖真实 Provider 和真实 JiuwenSwarm 的完整研究生命周期。

**固定链路：**

```text
Fixture ETF
  → Evidence Builder
  → ResearchCase
  → EvidencePack persistence
  → Fake ResearchRunner
  → ResearchRun
  → Evidence ID validation
  → ResearchResult persistence
  → Markdown report
```

**验收标准：**

- [ ] 正常完成链路生成 Case、Pack、Run、Result 和 Markdown。
- [ ] 非法 Evidence ID 不得生成 succeeded Result。
- [ ] Runner failure 会保留失败状态和去敏错误摘要。
- [ ] timeout/failure 不删除或覆盖 Evidence Pack。
- [ ] 重试产生新 attempt，不产生两个成功 Result。

**说明：** 本任务验证 Domain/Application/Storage 生命周期，不把真实 JiuwenSwarm 网络调用混入 Fake E2E。

**依赖：** Task 2、Task 3。  
**预计范围：** Medium。

### Task 5：API + Web 集成验收

**目标：** 在 API、PostgreSQL、Web 同时运行的条件下验证只读展示链路。

**验收标准：**

- [ ] API 端点返回与 OpenAPI 契约一致的 Case、Evidence、Run、Result。
- [ ] Web Research History 和 Research Case Workspace 能读取实际 API 响应。
- [ ] API 未启动时，Web 明确显示错误状态，不把网络错误误判为空数据。
- [ ] Playwright 不再因未启动 API 而产生 `ERR_CONNECTION_REFUSED` 失败。
- [ ] 页面不显示 provider key、workspace 绝对路径或内部异常。

**验证方式：** 使用固定 Fixture/测试数据库启动 API，再执行 `pnpm --dir apps/web test:e2e`。  
**依赖：** Task 4。  
**预计范围：** Medium。

### Task 6：Research API Contract 冻结

**目标：** 将实际 API 路径、Schema、错误语义和安全边界写入 OpenAPI 与验证记录。

**验收标准：**

- [ ] OpenAPI 与 Router 实际路径一致。
- [ ] API 只读，不执行计算或触发外部 Agent。
- [ ] 列表分页边界有测试。
- [ ] 404、422、查询异常均有测试。
- [ ] Evidence 与 Result 的公开字段完成去敏检查。
- [ ] 不增加与当前实现冲突的 alias endpoint。

**依赖：** Task 5。  
**预计范围：** Small/Medium。

### Task 7：Stage 4A Final Acceptance 报告

新增：`docs/validation/stage4a-final-acceptance.md`

报告必须记录：

- 基线 commit；
- 测试命令及实际结果；
- Research Case ID；
- Evidence Pack ID、Pack Hash、Factor Set Key/Version；
- 8 个因子数量和完整 Key 列表；
- Research Run ID、attempt、最终状态；
- Fake Runner E2E 结果；
- API 路径和响应验证结果；
- Web Playwright 结果及截图；
- Provider Key、workspace 路径、任意文件访问安全检查；
- 未完成项和明确阻塞项。

**依赖：** Task 1–6。  
**预计范围：** Small，文档。

## 6. Checkpoints

### Checkpoint A：Evidence Foundation

完成 Task 1–3 后必须满足：

- Domain 全量测试通过；
- Evidence Hash/幂等/历史测试通过；
- 8 个因子契约与代码一致；
- AI Result 与 Evidence 完全分离。

### Checkpoint B：Research Lifecycle

完成 Task 4 后必须满足：

- Fake Runner 完成正常、失败、非法引用、重试四类路径；
- 不依赖真实外部 Provider；
- Research Result 可持久化和读取。

### Checkpoint C：Final Acceptance

完成 Task 5–7 后必须满足：

- API、Web 集成测试通过；
- OpenAPI、Router、前端客户端一致；
- 验收报告证据完整；
- 没有未解释的测试失败。

## 7. Stage 4A 关闭条件

以下条件全部满足，才将 Stage 4A 标记为完成：

- [ ] Research Case 持久化和状态机验证通过。
- [ ] Evidence Pack 持久化、Hash、幂等和历史保留验证通过。
- [ ] 8 个 Factor Observation 均带有效 Evidence ID。
- [ ] Research Result 与 Evidence 独立保存。
- [ ] Fake Runner E2E 通过。
- [ ] API 契约、OpenAPI 和 Web 客户端一致。
- [ ] API + Web 集成测试通过。
- [ ] 无 Provider Key 泄漏。
- [ ] 不暴露 workspace 绝对路径，不允许任意 workspace 文件访问。
- [ ] Domain、Storage、Pipeline、API、Web 相关测试通过。
- [ ] Stage 4A 验收报告完成并可复核。

## 8. Stage 4B 启动边界

只有 Stage 4A Final Acceptance 完成后，才进入 Stage 4B Market Intelligence Foundation。

Stage 4B 的输入边界为：

```text
Market Evidence + ETF Evidence
  → Research Case / Evidence Pack
  → AI Research
```

Stage 4B 可另行设计 Market Temperature、Market Breadth、Theme Intelligence、ETF Rotation 等数据 Pack；这些内容不纳入本 Closure Sprint。

## 9. 暂不实施

- `return_120d` 及因子集 `1.0.0` 升级。
- Evidence Pack 独立 revision 字段。
- 新增 `/research-runs/latest` 或 evidence-pack/items/factors alias API。
- 真实 Provider 驱动的验收 E2E。
- 新增 UI 页面和市场智能 Dashboard。
- 向量数据库、新闻 RAG、通用 Agent 平台。
- 自动交易、仓位管理和买卖入口。
