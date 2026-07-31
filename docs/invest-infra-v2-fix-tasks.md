# invest-infra V2 修复任务清单

> 生成时间：2026-07-31 08:30 CST  
> 基于文档：`docs/invest-infra-v2-correction-plan.md`  
> 检查基线：当前仓库状态（2026-07-31）

---

## 任务总览

| 优先级 | 任务数 | 预估工作量 | 状态 |
|--------|--------|-----------|------|
| P0-紧急 | 3 | 2-3 天 | 待开始 |
| P1-高 | 5 | 3-5 天 | 待开始 |
| P2-中 | 4 | 2-3 天 | 待开始 |

---

## P0-1：修复 Dagster definitions 导入失败（阻断）

**问题**：`assets.py` 中 `context` 参数注解错误，导致 `definitions.py` 无法导入。

**错误信息**：
```
DagsterInvalidDefinitionError: Cannot annotate `context` parameter with type dg.AssetExecutionContext
```

**修复方案**：
- [ ] 移除 `seed_instruments` 函数的 `context` 参数注解，或改为 `dg.AssetExecutionContext` 的正确导入方式
- [ ] 验证 `definitions.py` 可正常导入

**验收命令**：
```bash
cd apps/pipeline
.venv/bin/python -c "from invest_pipeline.definitions import defs; print(defs)"
```

**涉及文件**：
- `apps/pipeline/src/invest_pipeline/assets.py`

---

## P0-2：删除/修复损坏的测试文件（阻断）

**问题**：9 个测试文件 import 已删除的 `invest_pipeline.providers`，全部无法运行。

**损坏文件清单**：
```
apps/pipeline/tests/unit/test_akshare_adapter_contract.py
apps/pipeline/tests/unit/test_cifang_adapter_contract.py
apps/pipeline/tests/unit/test_fixture_dev_provider.py
apps/pipeline/tests/unit/test_provider_capabilities.py
apps/pipeline/tests/unit/test_provider_factory_defaults.py
apps/pipeline/tests/unit/test_provider_registry.py
apps/pipeline/tests/unit/test_quicktiny_mcp_capabilities.py
apps/pipeline/tests/unit/test_rsscast_capabilities.py
apps/pipeline/tests/unit/test_settings_redaction.py
```

**修复方案**（二选一）：

**方案 A：删除过时测试**（推荐，符合纠偏文档 P1-2）
- [ ] 删除上述 9 个测试文件
- [ ] 保留 `tests/test_definitions_import.py`（修复后）
- [ ] 新增 `tests/unit/test_fixture_dev_adapter.py` 测试当前唯一的 Adapter

**方案 B：修复测试以匹配新结构**
- [ ] 重写所有测试，将 `invest_pipeline.providers` 改为 `invest_pipeline.adapters`
- [ ] 移除对 AkShare/Cifang/RSSCast/Quicktiny 的引用（这些 Provider 不应在运行时存在）

**验收命令**：
```bash
cd apps/pipeline
.venv/bin/python -m pytest tests/ -q
```

---

## P0-3：修复 `app.pipeline_runs` → `ops.pipeline_runs`

**问题**：`PipelineRunRow` 使用 `schema="app"`，应为 `schema="ops"`。

**修复方案**：
- [ ] 修改 `packages/storage/src/invest_storage/models.py`：`PipelineRunRow.__table_args__` 中 `schema="app"` → `schema="ops"`
- [ ] 修改 `packages/domain/src/invest_domain/pipeline/models.py`：更新注释中的 `app.pipeline_runs` 引用
- [ ] 创建新迁移或修改现有迁移（见 P1-3）
- [ ] 更新所有引用 `app.pipeline_runs` 的代码和测试

**验收命令**：
```bash
cd apps/api
uv run python -c "from invest_storage.models import PipelineRunRow; print(PipelineRunRow.__table_args__)"
# 应输出: {'schema': 'ops'}
```

**涉及文件**：
- `packages/storage/src/invest_storage/models.py`
- `packages/domain/src/invest_domain/pipeline/models.py`
- `apps/api/migrations/versions/20260730_0001_initial.py`
- `apps/api/migrations/versions/20260730_0004_pipeline_runs_updated_at.py`

---

## P1-1：统一 Provider 契约到 Domain `ProviderBatch[T]`

**问题**：`FixtureDevInstrumentProvider.list_instruments()` 返回 `Sequence[Instrument]`，而非 `ProviderBatch[Instrument]`。

**修复方案**：
- [ ] 修改 `FixtureDevInstrumentProvider` 实现 `EtfMarketDataProvider` Protocol
- [ ] 添加 `fetch_instruments(as_of: date) -> ProviderBatch[Instrument]` 方法
- [ ] 添加 `fetch_daily_bars(...)` 方法（可暂时返回空或 raise NotImplementedError）
- [ ] 更新 `assets.py` 使用新的 `fetch_instruments` 方法
- [ ] 删除旧的 `list_instruments` 方法

**验收命令**：
```bash
cd apps/pipeline
.venv/bin/python -c "
from invest_pipeline.adapters import FixtureDevInstrumentProvider
from invest_domain.market_data.models import ProviderBatch
p = FixtureDevInstrumentProvider()
result = p.fetch_instruments(date.today())
assert isinstance(result, ProviderBatch)
print('OK')
"
```

**涉及文件**：
- `apps/pipeline/src/invest_pipeline/adapters/fixture_dev/adapter.py`
- `apps/pipeline/src/invest_pipeline/assets.py`

---

## P1-2：收敛多 Provider 设计

**问题**：`.env.example` 和测试文件中仍包含 AkShare/Cifang/RSSCast/Quicktiny 配置。

**修复方案**：
- [ ] 修改 `.env.example`：删除所有非 `fixture_dev` 的 Provider 配置，只保留：
  ```
  INVEST_PIPELINE_PROVIDER_KEY=fixture_dev
  ```
- [ ] 删除或归档 `apps/pipeline/tests/unit/test_*_adapter_contract.py` 等引用多 Provider 的测试
- [ ] 确认 `adapters/` 目录下只有 `fixture_dev/` 和 `errors.py`
- [ ] 检查并删除任何残留的 `providers/` 目录引用

**验收命令**：
```bash
grep -E "AKSHARE|CIFANG|RSSCAST|QUICKTINY" .env.example
# 应无输出
```

**涉及文件**：
- `.env.example`
- `apps/pipeline/tests/unit/` 下相关测试文件

---

## P1-3：重置 Greenfield 迁移

**问题**：存在 4 个迁移文件，包含 shadow-rename 等兼容逻辑。

**修复方案**：
- [ ] 确认无生产数据库依赖（检查是否有运行中的 PostgreSQL 实例使用这些迁移）
- [ ] 删除现有迁移文件：
  ```
  apps/api/migrations/versions/20260730_0001_initial.py
  apps/api/migrations/versions/20260730_0002_instruments_uuid_identity.py
  apps/api/migrations/versions/20260730_0003_provider_batches_raw_evidence.py
  apps/api/migrations/versions/20260730_0004_pipeline_runs_updated_at.py
  ```
- [ ] 创建单一基线迁移 `20260731_0001_initial_v2.py`：
  - 创建 `raw/core/analytics/ops` 四个 Schema
  - 创建 `core.instruments`
  - 创建 `raw.provider_batches`
  - 创建 `ops.pipeline_runs`（正确字段和约束）
- [ ] 验证空库可升降级

**验收命令**：
```bash
cd apps/api
uv run alembic heads  # 应只有一个 head
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
```

**涉及文件**：
- `apps/api/migrations/versions/*.py`

---

## P1-4：统一 Python 版本为 `>=3.12,<3.13`

**问题**：所有 `pyproject.toml` 均为 `>=3.12,<3.15`。

**修复方案**：
- [ ] 修改 `packages/domain/pyproject.toml`
- [ ] 修改 `packages/storage/pyproject.toml`
- [ ] 修改 `apps/api/pyproject.toml`
- [ ] 修改 `apps/pipeline/pyproject.toml`
- [ ] 检查 CI/Dockerfile 是否一致

**验收命令**：
```bash
grep -r "requires-python" --include="pyproject.toml" .
# 应全部输出: >=3.12,<3.13
```

**涉及文件**：
- `packages/domain/pyproject.toml`
- `packages/storage/pyproject.toml`
- `apps/api/pyproject.toml`
- `apps/pipeline/pyproject.toml`

---

## P1-5：扩展架构检查脚本

**问题**：`check_architecture.py` 只检查 domain/api 的少量导入。

**修复方案**：
- [ ] 添加 storage 层禁止规则：
  ```python
  ROOT / "packages" / "storage" / "src": {
      "fastapi", "dagster", "akshare", "vectorbt", "backtrader",
  }
  ```
- [ ] 添加 pipeline adapters 禁止规则：
  ```python
  ROOT / "apps" / "pipeline" / "src" / "invest_pipeline" / "adapters": {
      "sqlalchemy",  # 禁止 Session/Repository/UoW
  }
  ```
- [ ] 添加 pipeline assets 禁止规则：
  ```python
  ROOT / "apps" / "pipeline" / "src" / "invest_pipeline" / "assets": {
      "subprocess",  # 禁止 subprocess.run
  }
  ```
- [ ] 添加检查：`providers.py` 与 `providers/` 同名冲突
- [ ] 添加检查：不允许新的 `app` Schema
- [ ] 添加检查：不允许 `qfq/hfq` 出现在生产路径

**验收命令**：
```bash
python scripts/check_architecture.py
# 应输出: Architecture boundaries OK
```

**涉及文件**：
- `scripts/check_architecture.py`

---

## P2-1：修复 CI 真实性

**问题**：CI 只运行架构检查 + 根目录 unittest + ruff，未运行真正测试。

**修复方案**：
- [ ] 拆分 CI jobs：
  ```yaml
  jobs:
    architecture:
      # 现有架构检查
    domain-tests:
      # PYTHONPATH=packages/domain/src pytest packages/domain/tests -q
    storage-unit:
      # PYTHONPATH=packages/domain/src:packages/storage/src:tests pytest tests/storage --ignore=tests/storage/integration -q
    storage-integration:
      # 需要 PostgreSQL service
    migrations:
      # alembic upgrade head / downgrade base / upgrade head
    pipeline-tests:
      # cd apps/pipeline && uv sync && uv run pytest -q
    pipeline-import-smoke:
      # uv run python -c "from invest_pipeline.definitions import defs"
    api-tests:
      # cd apps/api && uv sync && uv run pytest -q
    api-openapi-smoke:
      # uv run python -c "from invest_api.main import app"
    web-check:
      # cd apps/web && pnpm install && pnpm typecheck && pnpm build
  ```
- [ ] 添加 PostgreSQL service 到 CI
- [ ] 确保集成测试不被 skip

**验收命令**：
```bash
# 推送后检查 GitHub Actions 页面
```

**涉及文件**：
- `.github/workflows/ci.yml`

---

## P2-2：修复存储层测试依赖

**问题**：`tests/storage/` 测试因缺少 `sqlalchemy` 无法运行。

**修复方案**：
- [ ] 确认 `packages/storage/pyproject.toml` 包含 `sqlalchemy` 依赖
- [ ] 在 CI 或本地运行前执行 `uv sync` 安装依赖
- [ ] 或修改测试使用 mock 而非真实数据库

**验收命令**：
```bash
cd /home/claw/invest-infra
PYTHONPATH=packages/domain/src:packages/storage/src:tests \
  python3 -m pytest tests/storage --ignore=tests/storage/integration -q
```

---

## P2-3：更新 Makefile 与 CI 一致

**问题**：`make test` 可能与 CI 运行的测试不一致。

**修复方案**：
- [ ] 检查并更新 `Makefile`，确保 `make test` 运行与 CI 相同的测试集合
- [ ] 添加 `make test-domain`、`make test-storage`、`make test-pipeline` 等细分目标

**涉及文件**：
- `Makefile`

---

## P2-4：更新文档

**问题**：README 和 M0 Decisions 可能与代码不一致。

**修复方案**：
- [ ] 检查 `README.md` 是否描述旧 Mock 导入路径
- [ ] 检查 `docs/implementation/M0-DECISIONS.md` 是否与代码一致
- [ ] 更新 Provider 未决项为明确决定或阻塞项

**涉及文件**：
- `README.md`
- `docs/implementation/M0-DECISIONS.md`

---

## 推荐执行顺序

```
第 1 天：
  P0-1 修复 Dagster definitions 导入
  P0-2 删除/修复损坏的测试文件
  → 提交 PR-1

第 2 天：
  P0-3 修复 app.pipeline_runs → ops.pipeline_runs
  P1-3 重置 Greenfield 迁移
  → 提交 PR-2

第 3 天：
  P1-1 统一 Provider 契约
  P1-2 收敛多 Provider 设计
  → 提交 PR-3

第 4 天：
  P1-4 统一 Python 版本
  P1-5 扩展架构检查
  → 提交 PR-4

第 5 天：
  P2-1 修复 CI 真实性
  P2-2 修复存储层测试依赖
  P2-3 更新 Makefile
  P2-4 更新文档
  → 提交 PR-5
```

---

## 验收检查清单

完成所有任务后，必须满足：

- [ ] `invest_pipeline.definitions` 可以导入
- [ ] `pytest apps/pipeline/tests` 全部通过
- [ ] `pytest packages/domain/tests` 全部通过
- [ ] `pytest tests/storage` 全部通过
- [ ] `alembic upgrade head` / `downgrade base` / `upgrade head` 成功
- [ ] 只有一个 Alembic head
- [ ] 不存在 `app` Schema
- [ ] `ops.pipeline_runs` 字段正确
- [ ] `.env.example` 只包含 `fixture_dev` Provider
- [ ] 所有 `pyproject.toml` 为 `>=3.12,<3.13`
- [ ] `check_architecture.py` 通过
- [ ] CI 运行全部测试且全绿

---

*任务清单生成完毕，等待授权执行。*
