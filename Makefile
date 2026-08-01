SHELL := /bin/bash

.PHONY: help up down logs api-dev pipeline-dev web-dev migrate test lint arch-check lock test-domain test-storage test-storage-integration test-migrations test-pipeline test-api test-web provider-smoke

help:
	@echo "make up              启动 PostgreSQL、API、Web、Dagster"
	@echo "make migrate         执行数据库迁移"
	@echo "make test            运行全部测试（与 CI 一致）"
	@echo "make test-domain     运行 Domain 层测试"
	@echo "make test-storage    运行 Storage 层单元测试"
	@echo "make test-storage-integration 运行 Storage 层集成测试"
	@echo "make test-migrations 运行数据库迁移往返测试"
	@echo "make test-pipeline   运行 Pipeline 应用测试"
	@echo "make test-api        运行 API 应用测试"
	@echo "make test-web        运行 Web 类型检查、测试和构建"
	@echo "make arch-check      检查依赖边界"
	@echo "make lock            为各 Python 应用生成锁文件"
	@echo "make provider-smoke  对 CifangQuant 真实 API 做受限 smoke（opt-in）"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	cd apps/migrations && uv run alembic upgrade head

api-dev:
	cd apps/api && uv run fastapi dev src/invest_api/main.py --host 0.0.0.0 --port 8000

pipeline-dev:
	cd apps/pipeline && uv run dagster dev -m invest_pipeline.definitions -h 0.0.0.0 -p 3000

web-dev:
	cd apps/web && pnpm dev

lock:
	cd packages/domain && uv lock
	cd packages/storage && uv lock
	cd apps/api && uv lock
	cd apps/pipeline && uv lock

# 与 CI 一致的完整测试套件
test: arch-check test-domain test-storage test-storage-integration test-migrations test-pipeline test-api test-web
	@echo "All tests passed"

test-domain:
	PYTHONPATH=packages/domain/src python -m pytest packages/domain/tests -q

test-storage:
	cd packages/storage && uv sync
	PYTHONPATH=packages/domain/src:packages/storage/src:tests packages/storage/.venv/bin/python -m pytest tests/storage --ignore=tests/storage/integration -q

test-storage-integration:
	pip install sqlalchemy psycopg2-binary pytest testcontainers
	DATABASE_URL=postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest PYTHONPATH=packages/domain/src:packages/storage/src:tests python -m pytest tests/storage/integration -q

test-migrations:
	cd apps/migrations && uv sync
	cd apps/migrations && DATABASE_URL=postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest uv run alembic upgrade head
	cd apps/migrations && DATABASE_URL=postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest uv run alembic downgrade base
	cd apps/migrations && DATABASE_URL=postgresql+psycopg://invest:invest_dev_password@localhost:5432/invest uv run alembic upgrade head

test-pipeline:
	cd apps/pipeline && uv sync
	cd apps/pipeline && uv run ruff check src tests
	cd apps/pipeline && uv run pytest -q
	cd apps/pipeline && uv run python -c "from invest_pipeline.definitions import defs"

test-api:
	cd apps/api && uv sync
	cd apps/api && uv run ruff check src tests
	cd apps/api && uv run pytest -q
	cd apps/api && uv run python -c "from invest_api.main import app; print('API import OK')"

test-web:
	cd apps/web && pnpm install --frozen-lockfile
	cd apps/web && pnpm typecheck
	cd apps/web && pnpm test --run
	cd apps/web && pnpm build

lint:
	cd apps/api && uv run ruff check src tests
	cd apps/pipeline && uv run ruff check src tests

arch-check:
	python scripts/check_architecture.py

# 受限的 CifangQuant smoke（ADR-0011 Phase 1）。
#
# 三重 opt-in：INVEST_PIPELINE_CIFANG_ENABLED=true + --confirm-network 标志 +
# INVEST_PIPELINE_CIFANG_API_KEY 环境变量。目标不会在命令行回显 API key，
# 调用者必须通过环境变量注入令牌。
#
# 用法示例：
#   export INVEST_PIPELINE_CIFANG_ENABLED=true
#   export INVEST_PIPELINE_CIFANG_API_KEY=...            # 不会回显
#   make provider-smoke \
#       SMOKE_SYMBOLS=510300,510500 \
#       SMOKE_TRADE_DATE=2026-07-30 \
#       SMOKE_CONFIRM_NETWORK=1
provider-smoke:
	cd apps/pipeline && uv run python -m invest_pipeline.cifang_smoke \
		--symbols '$(SMOKE_SYMBOLS)' \
		--trade-date '$(SMOKE_TRADE_DATE)' \
		$(if $(SMOKE_CONFIRM_NETWORK),--confirm-network)
