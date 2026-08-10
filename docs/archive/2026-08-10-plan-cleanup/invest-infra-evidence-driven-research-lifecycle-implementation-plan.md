# invest-infra Evidence-driven Research 生命周期修正实施方案

## 1. 状态与目标

状态：Approved / Phase 0 implemented。本文已在 DC-3 完成后的 `57ff5af` 基线上重新核实；后续各 Phase 仍按原子切片分别实现和验收。

本计划不重建已有 Evidence Foundation，而是在现有 ETF 数据、Analytics、Candidate Pool 和 EvidencePack 基础上补齐：

```text
Instrument / Candidate Pool
          ↓
     ResearchCase
          ↓
 Existing EvidencePack
          ↓
      ResearchRun
          ↓
     ResearchResult
```

Research 与 AI 只消费 Core/Analytics 事实，不生成或修改行情、因子及候选池结果。

### 当前实现基线（2026-08-08）

| 能力 | 状态 | 处置 |
|---|---|---|
| EvidencePack、FactorObservation、Quality Gate、canonical hash | 已有 | 复用，不重建 |
| ResearchContextPack Domain、Repository、UoW、ETF Profile builder | 已有 | 保持为可重建只读 projection |
| EvidencePack 数据库表 + Repository/UoW 闭环 | 已完成 | PR-3 落库 |
| DC-3 Index/Exposure/Holdings | 已完成 | 作为后续 Research Evidence/Context 上游 |
| ResearchCase 领域 + 持久化 | 已完成 | PR-1 / PR-2 |
| ResearchRun、ResearchResult 领域 + Fake Runner | 已完成 | PR-4 / PR-5 |
| ResearchRun、ResearchResult PostgreSQL 持久化 + Repositories + UoW | 已完成 | PR-5.5（本次提交） |
| JiuwenSwarm Adapter | 已完成（推送） | PR-6（commit `7cc8da8`） |
| 只读 Research API | 本地已实现 / 未提交 | PR-7（仅本地 working tree） |

## 2. 架构决策

- `PipelineRun` 负责数据采集和确定性计算；`ResearchRun` 负责研究执行、Agent 调度、失败恢复和报告生成。
- Candidate Pool 是可选研究上下文，不是唯一入口。
- 复用现有 `EvidencePack`、`FactorObservation`、Quality Gate 和 canonical hash。
- 暂不新增独立 `factor_observations` 或通用 `evidence_items` 表；只有独立生命周期和稳定查询需求成立后再评估。
- JiuwenSwarm 通过 Adapter 接入，不进入领域模型。
- Agent 角色和 Playbook 使用版本化配置表达，不写死在领域层。
- 第一阶段 API 只读；不建设自动交易、仓位或买卖入口。

## 3. 实施阶段

### Phase 0：文档与契约基线

#### Task 0.1：修正文档漂移

更新 `README.md`、`docs/ARCHITECTURE.md` 及必要的 OpenWiki 源文档；保留 `docs/ARCHITECTURE-GOVERNANCE.md` 作为领域所有权权威来源，不批量改写历史 ADR。

验收：

- README 不再将系统仅描述为 ETF 数据工作台。
- ARCHITECTURE 不再把 Factor 等同于交易信号。
- Pipeline、Analytics、Research、AI 的职责与治理基线一致。

#### Task 0.2：冻结 Research Lifecycle ADR

新增 ADR，明确 ResearchCase、ResearchRun、ResearchResult 的职责、状态机、幂等原则、Evidence 引用规则及 JiuwenSwarm Adapter 边界。

Checkpoint：仅文档变化；链接与架构检查通过；Phase 0 完成后进入独立的 ResearchCase 领域切片。

### Phase 1：ResearchCase 领域闭环

#### Task 1.1：新增 ResearchCase 聚合

最小字段：`case_id`、`instrument_id`、`as_of_date`、`question`、`horizon`、`status`、`created_at`、`closed_at`。

建议状态机：

```text
draft → ready → running → completed
                    └──→ failed
draft/ready ───────────→ cancelled
```

约束：Candidate Pool 引用可选；状态转换由领域方法控制；ResearchCase 不保存 AI 报告正文。

#### Task 1.2：兼容现有 CaseContext 与 ResearchContextPack

`CaseContext` 保持为 EvidencePack 内不可变快照；现有 `ResearchContextPack` 保持为可由 Core/Analytics 重建的只读 projection。ResearchCase 负责生命周期，构建 Pack 时投影为 CaseContext，不直接删除、重命名或重复建设现有类型。

验收：合法和非法状态转换测试齐全；领域模型不依赖数据库、Dagster 或 JiuwenSwarm；现有 EvidencePack 测试保持通过。

### Phase 2：Research 持久化闭环

#### Task 2.1：持久化 ResearchCase

通过 ADR 确定物理 schema 后新增表、Repository、Unit of Work 端口及实现和 Alembic migration。状态转换采用事务 compare-and-set；已完成研究的历史内容不可覆盖。

#### Task 2.2：补齐 EvidencePack Repository

复用现有 `ResearchEvidencePackRow` 和 `analytics.research_evidence_packs`，补充 Repository、UoW 属性、领域对象映射、按 Pack/Case/Instrument 查询及 content-hash 幂等写入。不重建表，不建立第二套 EvidencePack。

Checkpoint A：migration chain 单链；Repository mock/integration tests 通过；相同 Pack 不重复落库；ResearchCase 与 EvidencePack 可在同一事务中关联。

### Phase 3：最小 ResearchRun

#### Task 3.1：定义 ResearchRun

最小字段：`run_id`、`case_id`、`evidence_pack_id`、`runner_key`、`playbook_key`、`status`、`attempt`、`started_at`、`finished_at`、`error_summary`。

建议状态机：

```text
queued → running → succeeded
                 ├→ failed
                 └→ cancelled
failed → queued（新 attempt）
```

ResearchRun 不复用 `PipelineRun` 表或状态机。

#### Task 3.2：定义 ResearchResult

保存 run、EvidencePack、结构化结论、风险、Evidence ID 引用、报告正文或引用，以及模型、Playbook、Adapter 版本。Result 与 Evidence 分离；引用不存在的 Evidence ID 时拒绝发布。

#### Task 3.3：实现 Fake Research Runner

冻结端口：

```text
ResearchRunner.run(case, evidence_pack, playbook) -> ResearchResult
```

覆盖正常完成、失败、重试、Evidence 引用校验、幂等和状态恢复。

Checkpoint B：`Create Case → Attach EvidencePack → Start ResearchRun → Produce Result → Validate Evidence IDs → Mark Succeeded` 全自动 E2E 通过。

### Phase 4：JiuwenSwarm Adapter

#### Task 4.1：建立适配器边界

Adapter 负责请求映射、事件接收、结果映射、外部 request/session ID 和错误分类；领域包不得导入 JiuwenSwarm SDK。

#### Task 4.2：最小 Playbook

可提供版本化 `etf_medium_term_assessment`，但 Agent 编排属于配置；输出 schema 必须冻结，所有观点必须引用 Evidence ID。

#### Task 4.3：失败恢复

覆盖请求前失败、已受理但本地超时、事件处理中断、报告失败和重复回调。相同外部 session 不得产生两个成功 Result。

### Phase 5：只读 Research API

最小 API：

```http
GET /api/v1/research-cases
GET /api/v1/research-cases/{case_id}
GET /api/v1/research-cases/{case_id}/evidence
GET /api/v1/research-runs
GET /api/v1/research-runs/{run_id}
GET /api/v1/research-runs/{run_id}/result
```

第一阶段不开放浏览器创建、重跑或取消操作。Router 只做校验和响应转换，查询逻辑进入 Application Query Service；不得泄露 workspace 本地路径、内部异常或凭证。Web 延后至 API 契约稳定后单独评估。

## 4. PR 顺序

1. PR-0：文档一致性与 Research Lifecycle ADR。
2. PR-1：ResearchCase 与 CaseContext 投影。
3. PR-2：ResearchCase persistence。
4. PR-3：EvidencePack Repository/UoW 闭环。
5. PR-4：ResearchRun 与 ResearchResult。
6. PR-5：Fake Runner E2E。
7. PR-5.5：ResearchRun / ResearchResult PostgreSQL 持久化 + Repositories + UoW 端口（衔接 Fake Runner 与 Swarm Adapter）。
8. PR-6：JiuwenSwarm Adapter。
9. PR-7：只读 Research API。

每个 PR 必须独立可测试、可回滚；不得把 Storage、Swarm 和 API 合并为一个大提交。

## 5. 暂不实施

- `return_120d` 及现有 v1.0.0 因子集升级。
- 独立 Factor Store 或通用 EvidenceItem 仓库。
- 向量数据库、新闻 RAG 和通用 Agent 平台。
- 自动交易、仓位管理和买卖入口。
- 微服务拆分和 Research Web 页面。

## 6. 总体验收标准

- ResearchCase 可从 Instrument 直接创建，不依赖 Candidate Pool。
- PipelineRun 与 ResearchRun 完全独立。
- Existing EvidencePack 可幂等持久化和读取。
- ResearchResult 不能修改 Evidence，所有 AI 结论均引用有效 Evidence ID。
- Fake Runner E2E 全自动通过。
- JiuwenSwarm 重试不会生成重复成功结果。
- API 只读且不暴露内部运行信息。
- 全量测试、架构检查和 migration-chain 检查通过。

## 7. 与 DC-3 的关系

DC-3 Exposure/Investment Context 建设属于 Core 与 Analytics 的上游证据供给；本计划属于下游 Research 生命周期。二者不是替代关系。

DC-3 已于 `57ff5af` 标记完成并推送。Research 生命周期现在可以独立启动；DC-4 不作为 ResearchCase/Fake Runner 闭环的前置条件，应由首个研究闭环暴露的证据缺口决定其优先级。

## 8. 当前状态（截至 PR-7）

本计划按 §4 PR 顺序逐片落地。PR-6 与 PR-7 的提交边界明确区分如下：PR-6 已推送并合并至 `main`；PR-7 已在本工作树实现但尚未 commit / push。

**已实现（PR-0 → PR-7）**

- **PR-0** 文档一致性 + Research Lifecycle ADR（ADR-0012）。
- **PR-1** `ResearchCase` 领域聚合 + `CaseContext` 投影，状态机 `draft → ready → running → completed / failed` 与 `cancelled`。
- **PR-2** `ResearchCase` 持久化：`analytics.research_cases` migration + Repository + UoW port + CAS 状态转换。
- **PR-3** EvidencePack Repository / UoW 闭环，复用 `research_evidence_packs`，`content_hash` 幂等。
- **PR-4** `ResearchRun` / `ResearchResult` 领域类型与状态机 `queued → running → succeeded / failed / cancelled`，`failed → queued` 允许新 attempt。
- **PR-5** Fake Research Runner 端到端：`Create Case → Attach EvidencePack → Start ResearchRun → Produce Result → Validate Evidence IDs → Mark Succeeded` 全部由领域方法驱动，无外部依赖。
- **PR-5.5（本次提交）** `ResearchRun` / `ResearchResult` PostgreSQL 持久化：
  - 新增 migration `20260807_0014_research_runs`（`analytics.research_runs` + `analytics.research_results`），命名 FK、CHECK 约束、唯一索引（`run_id` 在 results 上，`external_session_id` 在 runs 上），单一 head。
  - 新增 `SqlAlchemyResearchRunRepository` / `SqlAlchemyResearchResultRepository`：`add` / `get` / `list_by_case`、CAS 状态转换、外部请求/会话 ID 绑定与查询、Result 幂等写入与冲突检测。
  - 在 `SqlAlchemyUnitOfWork` 暴露 `uow.research_runs` / `uow.research_results` 端口及缓存属性。
  - 域包不引入 JiuwenSwarm SDK，无新增 API 端点。
- **PR-6（已推送，commit `7cc8da8`）** JiuwenSwarm Adapter：请求映射、事件接收、结果映射、外部 request/session ID 绑定与错误分类；领域包未引入 JiuwenSwarm SDK。已在 commit `7cc8da8` 合并至 `main`，纳入实现基线。
- **PR-7（本地已实现 / 未提交）** 只读 Research API：六个固定 GET 查询端点、Application Query Service、去敏 Evidence 公共契约、分页/计数与 OpenAPI 契约已在本工作树落地，但尚未 commit / push；落地切片见下文"本地已实现 / 未提交"小节。

**测试证据（PR-5.5）**

- migration chain：`tests/test_migration_chain.py` 11 passed。
- storage mocks（`tests/storage/test_*_mock.py` + `test_unit_of_work_mock.py`，不含 integration）：205 passed。
- 聚焦 PostgreSQL（`tests/storage/integration/test_research_run_result_repositories.py`）：9 passed。
- 完整 pipeline 测试套件：1461 passed。

**测试证据（PR-7 实现切片，2026-08-08 复测）**

- API 聚焦服务与端点测试（含 `test_research_detail_serialization.py` 的 4 个 HTTP-seam 真实领域对象序列化用例，覆盖 case / evidence / run / result 四条成功路径）：16 passed。
- 完整 API 测试套件（含 `test_research_detail_serialization.py`）：199 passed。
- Storage Research repository mock tests（`tests/storage/test_*_mock.py`，不含 integration）：217 passed。

**本地已实现 / 未提交（uncommitted）**

- **PR-7** 只读 Research API 已在本工作树实现，但尚未 commit / push；`main` 上最新事实仍是 PR-6（`7cc8da8`）已合并。落地切片对应 `apps/api/src/invest_api/{application,routers,schemas}/research.py`、`apps/api/tests/test_research_endpoints.py`、`apps/api/tests/test_research_service.py`、`apps/api/tests/test_research_detail_serialization.py`、`packages/storage/src/invest_storage/{repositories,unit_of_work}.py`、`tests/storage/test_research_run_repository_mock.py`、`apps/api/openapi.json`、`docs/plan/invest-infra-evidence-driven-research-lifecycle-implementation-plan.md`（本文件）、`tasks/pr7-research-api-{plan,todo}.md`。

声明：以上状态准确区分了"已推送并合并"（PR-6，commit `7cc8da8`）与"本地已实现但未提交"（PR-7）。Research 生命周期在 `main` 上的最新事实是 PR-6 已合并，read-only API 仅在本地 working tree 落地；尚未存在 PR-7 commit / push，不得在文档、ADR 或 review 描述中暗示 PR-7 已交付到 `main`。
