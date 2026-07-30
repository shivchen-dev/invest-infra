# ADR-0009：Python 与核心依赖版本基线

- Status：Accepted
- Date：2026-07-30
- Owners：M0 架构基线

## Context

所有 Python `pyproject.toml` 当前声明 `requires-python = ">=3.12,<3.15"`；`pyrightconfig.json` 和 `ruff.toml` 指向 3.12，CI 在 `.github/workflows/ci.yml` 使用 Python 3.12。仓库只有 `apps/api/uv.lock`，Pipeline 和 packages 尚无已提交锁文件。计划文档建议若干库，但不能把未声明依赖视为已安装。

## Decision

1. Phase 1 开发、CI 和生产运行时基线固定为 **CPython 3.12.x**。代码语法目标是 Python 3.12，不得使用 3.13/3.14 专属语法或标准库 API。
2. 后续编码应把各 Python project 的兼容声明收紧为 `>=3.12,<3.13`，与 CI/镜像一致；这是编码阶段的受控配置修改，不在 M0 文档任务中执行。
3. 现有核心依赖系列基线沿用仓库声明：

   | 范围 | 基线 |
   |---|---|
   | API | FastAPI `>=0.140.4,<1`，Uvicorn `>=0.35,<1`，Pydantic Settings `>=2.10,<3` |
   | Pipeline | Dagster/Webserver `>=1.13.14,<2`，Pydantic Settings `>=2.10,<3` |
   | Storage/Migration | SQLAlchemy `>=2.0.51,<2.1`，psycopg `>=3.3.4,<4`，Alembic `>=1.18.5,<2` |
   | Quality | Ruff `>=0.12,<1`，pytest `>=8.4,<9`（目前根测试实际用 unittest），Pyright strict/Python 3.12 |
   | Database | PostgreSQL 16（`compose.yaml` 当前为 `postgres:16-alpine`） |

4. `httpx`、`tenacity`、`structlog` 仅是计划候选；Pipeline 当前未声明这些依赖。实现 Provider 前须用最小依赖变更 ADR/PR 明确加入并锁定，不能假定可用。供应商 SDK仅在确认 Provider 后加入 Pipeline，禁止加入 domain、storage 或 API。
5. 每个可部署应用维护自己的 `uv.lock`，使用 `uv sync --frozen` 验证；共享 package 不单独决定生产解析结果。锁文件必须由 Python 3.12 环境生成并提交。不得手改 lock。
6. 依赖升级与业务改动分离；升级需通过 lint、strict typecheck、单元/契约/PostgreSQL 集成测试和镜像构建。版本上限不能在无验证时放宽。
7. 前端版本不在本 ADR 冻结；`apps/web/package.json` 和其 lock 状态由对应前端任务单独处理。

## Consequences

- 当前 `<3.15` 元数据与 M0 运行基线不完全一致，Phase 1 首批配置任务必须收紧。
- Pipeline lock 和 typecheck 门禁需要补齐后，才能宣称构建可重复。
- Provider 依赖只能在选型确认后引入，避免无用 SDK 污染镜像。

## Alternatives

- **把 `>=3.12,<3.15` 当作生产支持矩阵：Rejected。** CI 只验证 3.12。
- **升级到 Python 3.13/3.14：Rejected。** 与当前 lint、typecheck、CI 和已有环境基线不一致。
- **全仓库共用一个依赖环境：Rejected。** 违反 API/Pipeline 独立依赖和镜像边界。
- **不提交 lock：Rejected。** 无法重现生产构建。
