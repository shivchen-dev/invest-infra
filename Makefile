SHELL := /bin/bash

.PHONY: help up down logs api-dev pipeline-dev web-dev migrate test lint arch-check lock

help:
	@echo "make up            启动 PostgreSQL、API、Web、Dagster"
	@echo "make migrate       执行数据库迁移"
	@echo "make test          运行 Python 测试"
	@echo "make arch-check    检查依赖边界"
	@echo "make lock          为各 Python 应用生成锁文件"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	cd apps/api && uv run alembic upgrade head

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

test:
	PYTHONPATH=packages/domain/src:packages/storage/src python -m unittest discover -s tests -v

lint:
	cd apps/api && uv run ruff check src tests
	cd apps/pipeline && uv run ruff check src tests

arch-check:
	python scripts/check_architecture.py
