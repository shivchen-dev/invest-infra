# M1 Storage 增量 5 计划：Pipeline Run Repository

## 目标

实现 `SqlAlchemyPipelineRunRepository`，把 `app.pipeline_runs` 表接入应用层，完成 M1 Storage 闭环。

## 范围

### 代码

- `packages/storage/src/invest_storage/repositories.py`
  - 新增 `SqlAlchemyPipelineRunRepository`
  - Domain ↔ ORM 转换函数

- `packages/storage/src/invest_storage/unit_of_work.py`
  - 新增 `PipelineRunRepositoryPort` Protocol
  - 新增 `SqlAlchemyUnitOfWork.pipeline_runs` property

- `packages/storage/src/invest_storage/__init__.py`
  - 导出新类和 Protocol

- `packages/storage/src/invest_storage/models.py`
  - 可能需要小调整（仅当现有 `PipelineRunRow` 字段不满足需求时；优先不改）

### 测试

- `tests/storage/test_pipeline_run_repository_mock.py`：≥ 6 个 Mock 测试
- `tests/storage/integration/test_pipeline_run_repository.py`：≥ 4 个 Testcontainers 测试

## Domain ↔ ORM 映射

读取现有 Domain `PipelineRun`（应在 `packages/domain/src/invest_domain/`），理解：
- 必填字段
- 可选字段
- 状态枚举（`pending` / `running` / `succeeded` / `failed`）
- 时间字段（`started_at`、`finished_at`、`updated_at`）

读取现有 `PipelineRunRow`（在 `packages/storage/src/invest_storage/models.py`），理解 schema。

如发现字段不对齐，**优先扩展 ORM 模型**（通过 0004 迁移），不要修改 Domain。

## Repository 接口

```python
class SqlAlchemyPipelineRunRepository:
    def __init__(self, session: Session) -> None: ...

    def start(self, run: PipelineRun) -> PipelineRun:
        """Insert new run with status='running', return persisted run."""

    def mark_succeeded(self, run_id: UUID, *, finished_at: datetime) -> PipelineRun:
        """Update status='succeeded', set finished_at."""

    def mark_failed(self, run_id: UUID, *, error: str, finished_at: datetime) -> PipelineRun:
        """Update status='failed', set error and finished_at."""

    def get_by_id(self, run_id: UUID) -> PipelineRun | None: ...

    def list_recent(self, *, limit: int = 50, offset: int = 0) -> list[PipelineRun]: ...

    def count_by_status(self, status: str) -> int: ...
```

**约束**：
- 不在 Repository 内 commit（UoW 职责）
- 返回 Domain 对象，不返回 ORM
- 所有时间字段使用 `datetime.now(UTC)`，不带 tzinfo 的转换由 Domain 处理

## UoW 接入

```python
@property
def pipeline_runs(self) -> SqlAlchemyPipelineRunRepository:
    if self._pipeline_runs is None:
        self._pipeline_runs = SqlAlchemyPipelineRunRepository(self.session)
    return self._pipeline_runs
```

`__exit__` finally 中也需要 reset `_pipeline_runs = None`。

## 测试要求

### Mock 测试（≥ 6 个）

1. `test_start_inserts_row_with_status_running`
2. `test_start_returns_pipeline_run_with_persisted_id`
3. `test_mark_succeeded_updates_status_and_finished_at`
4. `test_mark_failed_sets_error_and_status`
5. `test_get_by_id_returns_run_when_present`
6. `test_get_by_id_returns_none_when_absent`
7. `test_list_recent_returns_runs_ordered_by_started_at_desc`
8. `test_count_by_status_filters_correctly`

### Integration 测试（≥ 4 个，Testcontainers）

1. `test_start_and_complete_full_lifecycle`
2. `test_mark_failed_records_error_message`
3. `test_concurrent_runs_have_distinct_ids`
4. `test_list_recent_filters_by_status`

## 验证

```bash
cd /home/claw/invest-infra
PATH=packages/storage/.venv/bin:$PATH \
PYTHONPATH=packages/domain/src:packages/storage/src \
  python -m unittest discover -s tests/storage -p "test_*mock*.py" -v
PYTHONPATH=packages/domain/src:packages/storage/src python3 -m unittest discover -s tests -v
python3 scripts/check_architecture.py
```

全部退出码为 0。

## 输出

完成后报告：
- 新增/修改文件
- 测试用例数量
- 是否新增迁移（如果是，附迁移内容摘要）
- unittest 输出尾部
- 剩余风险

## 终止条件

- 不实现 Dagster asset
- 不修改现有 Repository
- 不连接真实 PostgreSQL
- 不触碰 API、Provider Adapter、迁移 0001/0002/0003

不要询问，按计划执行。
