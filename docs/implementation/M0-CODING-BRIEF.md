# M0-CODING-BRIEF

> 给后续编码代理的任务书。本文件约束第一阶段（Phase 1）的初始编码，禁止越界、不引入未冻结能力、必须按顺序提交。

## 0. 任务范围与边界

- 阶段：Phase 1（依据 M0 已冻结 ADR）。
- 不做：不实现真实 Provider SDK 接入、不引入 Redis/Kafka/K8s、不部署、不申请生产权限、不动 `docs/plan/invest-infra-v2-etf-vertical-slice-plan.md`、不动业务代码直到 M1 启动。
- 任务目标：把 M0 文档固化为可执行代码、迁移、CI 门禁与运行说明，使 M1 起步即可迁移、M2 起步即可接 Provider。
- 唯一允许修改的目录/文件（与现有 ADR 一致）：
  - 新建：`packages/domain/src/invest_domain/...`（新子包与对象）
  - 新建：`packages/storage/src/invest_storage/...`（新 Repository、Unit of Work、模型视图）
  - 新建：`apps/api/src/invest_api/...` 新模块（不动现有 routes/main 业务路径中的逻辑，只追加）
  - 新建：`apps/migrations/migrations/versions/...` 新迁移文件（2026-07-31 起，迁移已独立为 `apps/migrations`）
  - 新建：`apps/pipeline/src/invest_pipeline/adapters/...`（占位，但不得引用未声明依赖）
  - 新建：`apps/pipeline/src/invest_pipeline/jobs/...`、`apps/pipeline/src/invest_pipeline/quality/...`、`apps/pipeline/src/invest_pipeline/candidate_pool/...`
  - 新建：`contracts/provider-fixtures/`、`contracts/golden-cases/`
  - 新建：`docs/runbooks/...`
  - 修改（仅配置级）：`apps/pipeline/pyproject.toml`（收紧 `requires-python` 至 `<3.13`、在 Provider 选型确认后追加 `httpx/tenacity/structlog` 与供应商 SDK）、`apps/api/pyproject.toml`（同样收紧 python 版本），以及各 Python 项目的 `uv.lock`
  - 修改：`scripts/check_architecture.py`（追加 domain/storage/pipeline 边界规则）
  - 修改：`.github/workflows/ci.yml`（追加 PostgreSQL 集成测试 job、Alembic single-head 检查、迁移 dry-run）
  - 修改：`README.md`（仅在“已执行/骨架验证状态”段落补充 M0 已落地的 ADR 与验证，不宣称 Provider 已接入）
  - 修改：`docs/adr/0003-0010`（如需 `Accepted`，按 M1 完成时升级；不得回退到 `Proposed` 之前）
  - 修改：`docs/implementation/M1-*`（M1 起新建）
- 禁止：
  - 修改 `docs/plan/invest-infra-v2-etf-vertical-slice-plan.md`；
  - 修改现有 `tests/test_domain.py`、`packages/storage/src/invest_storage/models.py` 中已有 `InstrumentRow`/`PipelineRunRow` 的字段（必要时通过新迁移迁移数据并加 `__table_args__` 扩展，不要直接 drop/create）；
  - 修改 `compose.yaml` 中默认账号；
  - 添加 Redis/Kafka/K8s 任何引用；
  - 在 `packages/domain` 引入 SQLAlchemy、Alembic、httpx、FastAPI、Dagster、AkShare 或任何 Provider SDK；
  - 在 `packages/storage` 引入 FastAPI、Dagster、Provider SDK；
  - 在 `apps/api` 引入 Provider SDK、回测、Notebook 类依赖；
  - 在生产路径启用 `MockInstrumentProvider`；
  - 把示例候选池阈值当作生产参数；
  - 提交 `.env`、fixture 中的真实凭据或用户/机构标识。

## 1. 交付分阶段

> 下列顺序与 ADR/plan 一致；每个阶段都必须能独立 merge 与 rollback。

### Phase 1-A：CI 与配置基线（与 M0 文档同步）

- 收紧 `apps/api/pyproject.toml` `apps/pipeline/pyproject.toml` `packages/domain/pyproject.toml` `packages/storage/pyproject.toml` 的 `requires-python` 为 `>=3.12,<3.13`，并 `uv lock`。
- 修复 `apps/api` 之外缺失的 `uv.lock`（如不存在则 `uv lock` 生成，提交）。
- 扩展 `scripts/check_architecture.py`：
  - domain：禁止 import `sqlalchemy`, `sqlalchemy.orm`, `alembic`, `httpx`, `fastapi`, `dagster`, `invest_api`, `invest_pipeline`, `invest_storage.repositories`（Repository 实现属于 storage），也禁止引用 `Adapter`/`Session`/`Provider*` 具体类；
  - storage：禁止 import `fastapi`, `dagster`, `invest_api.routes`, `invest_pipeline.assets`, 任何 Provider SDK；允许 import `sqlalchemy`/`alembic`；
  - api：禁止 import 任何 Provider SDK 与 `invest_pipeline.adapters.*`；允许 import `invest_domain`, `invest_storage`；
  - pipeline：允许 import `invest_domain`, `invest_storage`, `invest_pipeline.adapters.*`；禁止 import `invest_api.*`。
- 扩展 `.github/workflows/ci.yml`：
  - 新增 `pg-integration` job，使用 `services: postgres:16-alpine`，执行 `alembic upgrade head` 与 `pytest -m integration`；
  - 新增 `alembic single-head` 检查（多个 head 即 fail）；
  - 新增 `ruff format --check`、`pyright`（沿用 `pyrightconfig.json` 严格模式）；
  - 现有 `architecture-and-domain` job 仍只允许 domain/storage import 检查。
- 任务前置：CI 不变绿不得进入 1-B。

### Phase 1-B：领域对象与端口扩展（纯领域，不入库）

- 在 `packages/domain/src/invest_domain`：
  - 新建 `market_data/values.py`：`Adjust`（StrEnum，仅 `NONE`）、`TradingStatus`（`normal | suspended`）、`Currency`（仅 `CNY`）；
  - 新建 `market_data/models.py`：`ProviderBatch[T]`、`DailyBar`（含 ADR-0005 全部字段与 `row_hash` 算法版本字段 `hash_schema_version`）；
  - 新建 `candidate_pool/models.py`：`CandidatePoolPolicy`、`CalculationContext`、`CandidatePoolResult`、`RuleOutcome`、`ExclusionReason`；
  - 新建 `instruments/models.py` 扩展：`InstrumentId`（UUID 新建/解析）、`Instrument` 增加 `instrument_id`、`list_date`、`delist_date`、`status`、`underlying_index`、`category`、`provider_symbol_map`、`valid_from`、`valid_to`（仅做类型和工厂；不做持久化）；
  - 新建 `market_data/ports.py`：`EtfMarketDataProvider`（与 ADR-0003 一致）、`InstrumentProvider`（沿用既有 `list_instruments`）；
  - 新建 `candidate_pool/ports.py`：`CandidatePoolCalculator` Protocol，签名 `build_candidate_pool(instruments, histories, policy, context) -> CandidatePoolResult`，显式不读 IO/时间/env；
  - `__init__.py` 只 re-export 公共对象。
- 单元测试：`packages/domain/tests/test_instrument_id.py`、`test_daily_bar.py`、`test_candidate_pool_protocol.py`，覆盖：
  - 非法 symbol/exchange/币种/上市退市关系；
  - `DailyBar` Decimal 序列化和 `row_hash` 稳定性（同一数据多次生成相同 hash；不同 `hash_schema_version` 显式不同）；
  - `CandidatePoolPolicy` 字段排序与去重；
  - 协议抽象不允许 import storage/api。
- 不允许出现：Repository 引用、SQLAlchemy 类型、Alembic op、Provider SDK、HTTP。
- 任务前置：domain 单元测试全绿、`scripts/check_architecture.py` 通过；进入 1-C。

### Phase 1-C：存储模型、Repository、Unit of Work

- `packages/storage`：
  - 新建 `models/`，把 `models.py` 拆为 `core.py`、`raw.py`、`analytics.py`、`ops.py`，但保留 `models.py` 仅 re-export 兼容现有 import。
  - 新建 `uow.py`：`UnitOfWork` 协议与 SQLAlchemy 实现；提供 `commit/rollback/flush` 钩子；
  - `repositories/` 新增 `instruments.py`、`provider_batches.py`、`daily_bars.py`、`input_snapshots.py`、`candidate_pool.py`、`quality.py`、`pipeline_runs.py`。
  - `daily_bars.py` 实现：
    - `get_latest(instrument_id, trade_date, adjustment)` 仅供快照构建；
    - `get_exact(..., revision)` 用于重放；
    - `upsert_with_revision(bar)` 内部用 transaction-scoped `pg_advisory_xact_lock(lock_key)` 读取 `MAX(revision)`，按 ADR-0006 决策分配新 revision 或 no-op；
    - 使用 SQLAlchemy `insert(...).on_conflict_do_nothing` 仅作最后兜底，**不替代锁与 hash 比较**。
  - `input_snapshots.py` 实现：
    - `create_snapshot(...)` 在 `REPEATABLE READ` 事务内插入 rows 与 header，按 ADR-0007 规范计算 `query_hash` 与 `content_sha256`，回填；
    - `get_snapshot(snapshot_id)` 返回 header + rows；
    - `verify_snapshot(snapshot_id)` 重新计算并对比；不一致抛 `SnapshotIntegrityError`。
  - `candidate_pool.py` 实现：
    - `create_run(..., snapshot_id, ...)`，在事务内插入 run + 全部 items；缺 item 必须抛错而非 commit；
    - `transition(run_id, expected, new, actor, reason, evidence)` 走 `UPDATE ... WHERE id=? AND status=?` 0 行则抛 `ConcurrentTransitionError`；
    - `publish(run_id, evidence)` 在事务内 `validated -> published` 并 upsert publication pointer，旧 `published` 写 `superseded_at`；
    - `current_publication(trade_date, algorithm_key, parameter_set_key)`。
  - `quality.py`、`pipeline_runs.py` 实现：写入 helper、查询 helper；与 Dagster 集成留给 1-D。
- 新增 Alembic 迁移（按 schema 分组，可一次升级 head；破坏性变更分两个 release）：
  - `2026MMDD_0002_schemas_raw_analytics_ops.py`：建 `raw/analytics/ops` schema（`raw.provider_batches` 仅含必要列，完整字段见 ADR）；
  - `2026MMDD_0003_instruments_evolution.py`：把 `core.instruments` 升级为 UUID 主键、增字段、加 `UNIQUE(symbol, exchange, valid_from)`、`CHECK(valid_to IS NULL OR valid_to >= valid_from)`、迁移现有 symbol → 新表（FK 切换在 M1 后由外键 migration 完成）；
  - `2026MMDD_0004_daily_bars_and_view.py`：建 `core.daily_bars` 复合主键、约束、外键、`core.latest_daily_bars` view；
  - `2026MMDD_0005_input_snapshots.py`：建 `analytics.input_snapshots` + `analytics.input_snapshot_rows`、唯一约束；
  - `2026MMDD_0006_candidate_pool.py`：建 `analytics.candidate_pool_runs`、`candidate_pool_items`、`candidate_pool_publications`、状态事件表；
  - `2026MMDD_0007_ops_pipeline_runs.py`：建 `ops.pipeline_runs`（Dagster run ID/partition/trigger/algorithm_version/config_snapshot/finished_at 等）、`ops.data_quality_results`，并保留 `app.pipeline_runs` 的迁移策略注释（不删除，向前数据复制到 `ops.pipeline_runs`）。
  - 每个迁移含 `downgrade()`、前向/回滚说明注释。
- 测试：
  - 集成测试 `packages/storage/tests/integration/test_migrations.py`：从空库 `alembic upgrade head`、无破坏；
  - Repository 单元 + 集成：`test_instrument_upsert.py`、`test_daily_bars_revision.py`（含并发 advisory lock 与 hash 同/不同分支）、`test_input_snapshot.py`（同输入同 hash、不同 revision 不同 hash、缺行/坏 hash 抛 `SnapshotIntegrityError`）、`test_candidate_pool_state.py`（仅合法转换、并发 winner 唯一、pointer 替换历史保留）、`test_pipeline_runs.py`。
  - 任何 integration 测试必须用 Testcontainers 启动真实 PostgreSQL 16。
- 任务前置：所有迁移可在空库完整应用；`alembic check` 单一 head；CI 集成测试全绿。进入 1-D。

### Phase 1-D：Dagster 编排骨架（无真实 Provider）

- `apps/pipeline/src/invest_pipeline`：
  - `adapters/` 新建占位子包 `dev/`：仅暴露基于 fixture 的 `FixtureInstrumentProvider` 与 `FixtureEtfMarketDataProvider`，严格遵守 ADR-0003 边界，**不允许在 production job 中被引用**；通过 `Settings.provider_key=fixture_dev` 显式选择。
  - `assets/`：
    - `instruments.py`：`etf_instruments_raw`、`etf_instruments`（调用 adapter → `ProviderApplicationService` 写 raw batch → upsert `core.instruments`）；
    - `daily_bars.py`：`etf_daily_bars_raw`（按分区日期 + 按 symbol 批次）、`etf_daily_bars`（标准化 + revision）、`etf_daily_bars_quality`；
    - `input_snapshot.py`、`candidate_pool.py`、`candidate_pool_quality.py`、`candidate_pool_publish.py`；
    - 每个 asset 的 op 通过 `context.log` 写入 ADR-0010 列出的字段子集；不打印凭据/响应原文。
  - `jobs/`：`daily_close_job`、`backfill_daily_bars_job`、`recompute_candidate_pool_job`。
  - `resources/`：`ProviderRateLimiter`（Provider 选型确认后再启用配置项）、`PostgresResource`（注入 engine、UnitOfWork factory）。
  - `quality/`：规则注册器与阈值加载（仅读取版本化 YAML；阈值未确认时不内置任何业务数值）。
  - `candidate_pool/`：纯函数 `build_candidate_pool(...)` 内部 import `invest_domain.candidate_pool.ports`，不访问 IO/时间/env；不读 SQL。
  - `definitions.py` 注册 asset/job/resource，并按 `Settings.environment` 决定启用 fixture 或真实 Provider。
  - 现有 `assets.py` 中的 `seed_instruments` 改为 thin wrapper，**生产路径禁用**；保留仅供开发验证。
- `contracts/`：
  - `provider-fixtures/` 至少包含 `etf_instruments_success.json`、`etf_daily_bars_success.json`、`etf_daily_bars_partial.json`、`rate_limit.json`、`malformed_response.json`（脱敏，不含真实价格档）；
  - `golden-cases/etf-candidate-pool/case_001/`：仅在候选算法纯函数完成后写 `expected.json`。
- 测试：
  - `apps/pipeline/tests/contract/test_provider_fixtures.py`：响应字段变化 fail；缺字段抛 `ProviderDataContractError`；日志脱敏检查；
  - `apps/pipeline/tests/integration/test_dagster_jobs.py`：以 fixture 跑 `daily_close_job` 一次，结果可重放；并发跑两次，仅一个 run 留下业务结果；候选池 release 不会发布 calculated 状态。
  - `apps/pipeline/tests/unit/test_candidate_pool_pure.py`：黄金样例同输入→同输出；阈值来源于 fixture，不引用计划文档示例数字。
- 任务前置：上述 job 在 fixture 下端到端 green；CI 集成测试只跑 fixture；`scripts/check_architecture.py` 仍全绿。进入 1-E。

### Phase 1-E：API 与前端只读层

- `apps/api`：
  - 新增只读路由 `/v1/candidate-pools/{run_id}`、`/v1/candidate-pools/latest`（仅返回 publication pointer 指向且 `status=published` 的 run）、`/v1/candidate-pools/{run_id}/items/{symbol}`、`/v1/data-freshness`、`/v1/pipeline-runs` 与详情；
  - 现有 `routes.py` 不直接改写，新路由在 `routes/` 子包中以 `APIRouter` 形式挂载，避免破坏既有 `/v1/instruments` 行为；
  - 运维触发端点 M1 阶段先以 `404` 或仅在 `Settings.environment=dev` 注册；不允许生产默认开启；
  - 引入 `pydantic-settings` 中 `environment` 字段；密钥不出现；
  - 编译命令 `uv run ruff check`、`uv run pyright`、集成测试（`/v1/candidate-pools/latest` 在 pointer 为空时返回 200 + 空集）。
- `apps/web`：
  - 不改 `App.tsx` 现有仪表盘逻辑；新增 `pages/CandidatePoolPage.tsx`、`DataFreshnessPage.tsx`、`PipelineRunsPage.tsx`；
  - 仅消费 API；前端禁止任何候选池计算。
- 任务前置：API + Web 在 fixture pipeline 完成后能看到 published 状态；失败/未发布状态在前端显示明确原因。

### Phase 1-F：部署、备份与 Runbook（边界文件，非真实部署）

- `docs/runbooks/` 新建 `provider-auth-failure.md`、`daily-bars-missing.md`、`reprocess-partition.md`、`reject-candidate-pool.md`、`database-restore.md`：
  - 每份包含症状、判断命令/页面、安全恢复步骤、是否重新采集、是否生成新 revision、验证步骤、是否回滚发布；
  - `database-restore.md` 引用 O-7 待确认项；标注首次演练时间窗。
- `compose.yaml`：
  - 保持开发用，不暴露生产密钥；新增注释段说明生产部署需独立 compose/profiles；
  - 新增 migration job 服务（仅 dev profile），镜像构建与 API 复用。
- `Makefile`：新增 `migrate-check`、`arch-check-strict`、`integration` 目标；不修改既有 `up/down/migrate/test/lint`。
- `README.md`：
  - 现有段落保留；新增 M0 段落列出 `docs/adr/0003-0010` 与 `docs/implementation/M0-*`；不宣称 Provider 已接入。
- 任务前置：上述 runbook 模板与脚本均存在；CI 与本地 `make` 目标可执行。

## 2. 迁移顺序与回滚

- 所有迁移可单独 `alembic upgrade <rev>` 与 `alembic downgrade -1`；破坏性变更（`instruments` 主键变更、删除 `app.pipeline_runs`）在生产环境必须分两发布：
  - 第一次：建新表/新列、双写、视图与触发器（如需要）；
  - 第二次：切读路径、移除旧列/旧表。
- 回滚策略：先按迁移逆序 `downgrade`；若不可降级，按 `database-restore.md` 用最近一次备份 + WAL 恢复到隔离实例验证后再切换。

## 3. 测试门禁

- `make test`：根 unittest 套件必须全绿。
- `make arch-check`：`scripts/check_architecture.py` 必须全绿；新增规则不得降低门槛。
- `make lint`：`ruff check` 全绿；`ruff format --check` 干净。
- Typecheck：`pyright`（strict 模式）零错误。
- 数据库：`alembic check` 单一 head；空库 `alembic upgrade head` 无错；集成测试全绿。
- Provider 契约：fixture 响应变化必须 fail；缺字段必须 fail；脱敏检查必须通过。
- 候选池：黄金样例同输入→同输出；不同 `parameter_hash` 不同 run。
- CI：所有 job 绿后才可合入。

## 4. 完成条件（Definition of Done for Phase 1）

- ADR-0003 ~ ADR-0010 状态由 M1 起逐步置为 `Accepted`；任何 ADR 仍为 `Proposed` 即视为未完成。
- M0 文档（M0-DECISIONS/M0-ACCEPTANCE/M0-CODING-BRIEF）未变。
- 现有业务代码（`apps/api/src/invest_api/{routes,dependencies,schemas,config,main}.py`、`apps/pipeline/src/invest_pipeline/{providers,assets,config,definitions}.py`、`packages/storage/src/invest_storage/{database,repositories,models}.py`）未发生破坏性改动；任何修改都有 ADR 引用和迁移。
- 所有 O-1 至 O-10 仍清晰列入未决清单；任何被关闭的项目必须在 M1 文档中明确。
- CI 至少含：`architecture-and-domain`、`api`、`pipeline`、`pg-integration` 四 job；任一失败即整体失败。
- 本地 `make up`、`make migrate`、`make test`、`make arch-check`、`make lint` 在清洁环境可重现。
- 文档不宣称 Provider 已接入、生产 SLA 已达到或 M0 已具备生产就绪。

## 5. 与现有资产的协调

- `apps/pipeline/src/invest_pipeline/assets.py` 现有 `seed_instruments`：在新代码中标记 `@dg.asset(owners=["code-invest-infra@local"], tags={"phase":"dev-only"})`，并通过 `Settings.environment=dev` 才注册到 `Definitions`；生产 `Definitions` 不得包含此 asset。
- `apps/pipeline/src/invest_pipeline/providers.py`：`MockInstrumentProvider` 标记 deprecated 并迁移到 `adapters/dev/fixture_provider.py`；现有 import 路径保留为 thin re-export，确保 import 站点不变。
- `packages/storage/src/invest_storage/models.py`：`InstrumentRow`/`PipelineRunRow` 字段保留，新功能通过新 schema/新表实现；不得直接 drop 重建。
- `tests/test_domain.py`：保留并随 domain 扩展补充；不删除。
