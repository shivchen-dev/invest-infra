# M1 Storage 增量 3 计划：Repository、UoW、PostgreSQL 集成测试

## 目标

完成 M1 Storage 第三步增量，实现：

1. `InstrumentRepository` 的完整 CRUD 与 UUID 标识 upsert
2. `ProviderBatchRepository` 用于保存原始行情拉取批次
3. `UnitOfWork` 协议与 SQLAlchemy 实现，定义事务边界
4. 基于 Testcontainers 的 PostgreSQL 集成测试

不要触碰：候选池、Pipeline、Dagster、API 端点、Provider Adapter、真实凭据、迁移结构调整。迁移结构保持当前已提交状态（initial + 0002 + 0003）。

## 已完成基础

- `packages/storage/src/invest_storage/models.py`：InstrumentRow、ProviderBatchRow、PipelineRunRow
- `apps/api/migrations/versions/20260730_0001_initial.py`、`0002`、`0003`
- `InstrumentRepository`（partial）
- 24 个静态迁移测试通过
- Docker 中存在 `invest-postgres` 与 `synapse-test-postgres`

## 本次增量新增

### 代码

```
packages/storage/src/invest_storage/
├── repositories.py           # InstrumentRepository、ProviderBatchRepository
├── unit_of_work.py           # UnitOfWork protocol + SqlAlchemyUnitOfWork
└── providers.py              # session_factory 抽象
```

### 测试

```
tests/storage/
├── conftest.py               # PostgreSQL fixture（Testcontainers）
├── test_instrument_repository.py
├── test_provider_batch_repository.py
└── test_unit_of_work.py
```

### 依赖

`packages/storage/pyproject.toml`：

- `sqlalchemy >= 2.0`
- `psycopg[binary] >= 3.1`
- `testcontainers[postgres] >= 4.0`（测试可选依赖）

## 关键约束

1. **不要修改现有迁移**。所有新增 schema/索引必须用新迁移 0004。
2. **UUID 主键**：`InstrumentRow.id` 已是 UUID；upsert 以 `(exchange, symbol, instrument_type, source)` 唯一键去重。
3. **Repository 返回 Domain 对象**，不返回 ORM 对象；ORM/Domain 转换放 Repository 内。
4. **UnitOfWork 必须提供**：
   - `commit()` / `rollback()`
   - `__enter__` / `__exit__`
   - repositories 作为 property：`.instruments`、`.provider_batches`
5. **测试隔离**：每个测试用独立 schema 或事务回滚，避免脏数据。
6. **不连接现有 Docker PostgreSQL**。Testcontainers 自动拉起临时容器；如果当前环境拉镜像失败，测试应 `pytest.skip()` 而不是 fail。
7. **CI 友好**：缺 Docker 时跳过，不阻塞无 Docker 环境的开发者。

## 测试要求

### Repository 测试

- `test_upsert_instrument_new`：新增成功，`id` 是 UUID
- `test_upsert_instrument_existing_returns_same_id`：相同 `(exchange, symbol, source)` 返回同一 `id`
- `test_list_active_instruments_pagination`：分页正确，boundary 正确
- `test_provider_batch_save_and_get_by_id`：保存后可读取
- `test_provider_batch_unique_batch_id`：相同 `batch_id` 重复插入失败或返回原 batch

### UnitOfWork 测试

- `test_uow_commit_persists_changes`
- `test_uow_rollback_discards_changes`
- `test_uow_exception_triggers_rollback`
- `test_uow_context_manager_closes_session`

## 验收标准

- `pytest tests/storage/` 全通过（或在无 Docker 环境下被 skip）
- `pytest tests/test_migration_chain.py tests/test_increment2_migrations_ast.py` 仍全通过
- `python scripts/check_architecture.py` 通过
- `git diff --stat` 仅包含本次增量相关文件
- 测试结果文件：`tests/storage/INCREMENT3-RESULTS.md`

## 不在本次范围

- 候选池 Repository
- Pipeline Run Repository 增强
- API 端点
- Dagster asset
- 真实 Provider Adapter
- 任何 Docker compose 改动

## 风险

| 风险 | 缓解 |
|---|---|
| 当前环境无 Docker | 测试 skip 而非 fail |
| Testcontainers 拉镜像超时 | 设置 60s timeout |
| 现有迁移修改 | 本次任务中明令禁止 |
| Domain ↔ ORM 映射偏差 | Repository 强制转换 |
