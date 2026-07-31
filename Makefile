SHELL := /bin/bash

.PHONY: help up down logs api-dev pipeline-dev web-dev migrate test lint arch-check lock test-domain test-storage test-pipeline test-api

help:
	@echo "make up              启动 PostgreSQL、API、Web、Dagster"
	@echo "make migrate         执行数据库迁移"
	@echo "make test            运行全部 Python 测试（与 CI 一致）"
	@echo "make test-domain     运行 Domain 层测试"
	@echo "make test-storage    运行 Storage 层单元测试"
	@echo "make test-pipeline   运行 Pipeline 应用测试"
	@echo "make test-api        运行 API 应用测试"
	@echo "make arch-check      检查依赖边界"
	@echo "make lock            为各 Python 应用生成锁文件"

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
test: arch-check test-domain test-storage test-pipeline test-api
	@echo "All tests passed"

test-domain:
	PYTHONPATH=packages/domain/src python -m pytest packages/domain/tests -q

test-storage:
	cd packages/storage && uv sync
	PYTHONPATH=packages/domain/src:packages/storage/src:tests packages/storage/.venv/bin/python -m pytest tests/storage --ignore=tests/storage/integration -q

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

lint:
	cd apps/api && uv run ruff check src tests
	cd apps/pipeline && uv run ruff check src tests

arch-check:
	python scripts/check_architecture.py
