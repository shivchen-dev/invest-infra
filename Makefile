SHELL := /bin/bash

.PHONY: help up down logs api-dev pipeline-dev web-dev migrate test lint arch-check lock test-domain test-storage test-storage-integration test-migrations test-pipeline test-api test-web provider-smoke personal-daily-run reprocess-date personal-backfill

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
	@echo "make personal-daily-run  手动运行 personal_etf_daily_job（PR-4）"

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

# 手动执行 personal_etf_daily_job（Stage 1 PR-4）。
#
# 真实网络运行需要三重 opt-in：INVEST_PIPELINE_PROVIDER_KEY=cifangquant +
# INVEST_PIPELINE_CIFANG_ENABLED=true + CONFIRM_NETWORK=1。Fixture/开发
# 模式（INVEST_PIPELINE_PROVIDER_KEY=fixture_dev）不需要 confirm-network。
#
# 可选参数 UNIVERSE / POLICY 映射到
# INVEST_PIPELINE_PERSONAL_UNIVERSE_PATH /
# INVEST_PIPELINE_CANDIDATE_POOL_POLICY_PATH，并在 Dagster definitions
# 导入之前注入，因此单条命令就能切换个人池 / 策略文件。
#
# 用法示例（fixture 个人日常运行）：
#   make personal-daily-run TRADE_DATE=2026-07-30
#
# 用法示例（CifangQuant 真实 API 验收）：
#   export INVEST_PIPELINE_PROVIDER_KEY=cifangquant
#   export INVEST_PIPELINE_CIFANG_ENABLED=true
#   export INVEST_PIPELINE_CIFANG_API_KEY=***           # 不会回显
#   make personal-daily-run \
#       TRADE_DATE=2026-07-31 \
#       CONFIRM_NETWORK=1
personal-daily-run:
	cd apps/pipeline && uv run python -m invest_pipeline.personal_daily_cli \
		--trade-date '$(TRADE_DATE)' \
		$(if $(UNIVERSE),--universe '$(UNIVERSE)') \
		$(if $(POLICY),--policy '$(POLICY)') \
		$(if $(CONFIRM_NETWORK),--confirm-network)

# 重新处理单个交易日：复用 personal-daily-run。
# 用法：make reprocess-date TRADE_DATE=2026-07-30
reprocess-date:
	@if [ -z "$(TRADE_DATE)" ]; then \
		echo "ERROR: TRADE_DATE is required (YYYY-MM-DD)" >&2; exit 2; \
	fi
	+@$(MAKE) -s personal-daily-run TRADE_DATE='$(TRADE_DATE)' \
		$(if $(UNIVERSE),UNIVERSE='$(UNIVERSE)') \
		$(if $(POLICY),POLICY='$(POLICY)') \
		$(if $(CONFIRM_NETWORK),CONFIRM_NETWORK=$(CONFIRM_NETWORK))

# 个人回填：按交易日顺序在 [START_DATE, END_DATE] 区间内执行 personal-daily-run。
#
# 校验：
#   - START_DATE / END_DATE 必须为 ISO 日期 YYYY-MM-DD 且为合法日历日
#   - START_DATE <= END_DATE
#   - END_DATE 不能为未来日期（相对今天）
#   - 跨度（含两端）<= 90 自然日
#   - 周六 / 周日自动跳过，仅周一至周五逐日执行
#   - 任一工作日运行失败立即停止，首条非零退出码即中止回填
#   - 输出仅包含日期与状态摘要，不回显密钥 / 路径等敏感参数
#
# 用法示例：
#   make personal-backfill START_DATE=2026-07-01 END_DATE=2026-07-31
personal-backfill:
	@case '$(START_DATE)' in \
		'') echo "ERROR: START_DATE is required (YYYY-MM-DD)" >&2; exit 2 ;; \
	esac
	@case '$(END_DATE)' in \
		'') echo "ERROR: END_DATE is required (YYYY-MM-DD)" >&2; exit 2 ;; \
	esac
	@START_DATE_VAL='$(START_DATE)'; END_DATE_VAL='$(END_DATE)'; \
	for d in "$$START_DATE_VAL" "$$END_DATE_VAL"; do \
		case "$$d" in \
			[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;; \
			*) echo "ERROR: $$d is not ISO YYYY-MM-DD" >&2; exit 2 ;; \
		esac; \
		got=$$(date -d "$$d" +%Y-%m-%d 2>/dev/null) || { echo "ERROR: $$d is not a valid date" >&2; exit 2; }; \
		if [ "$$got" != "$$d" ]; then \
			echo "ERROR: $$d is not a valid calendar date (parsed as $$got)" >&2; exit 2; \
		fi; \
	done
	@START_DATE_VAL='$(START_DATE)'; END_DATE_VAL='$(END_DATE)'; \
	start_epoch=$$(date -d "$$START_DATE_VAL" +%s); \
	end_epoch=$$(date -d "$$END_DATE_VAL" +%s); \
	if [ $$start_epoch -gt $$end_epoch ]; then \
		echo "ERROR: START_DATE ($$START_DATE_VAL) is after END_DATE ($$END_DATE_VAL)" >&2; exit 2; \
	fi; \
	today_epoch=$$(date +%s); \
	if [ $$end_epoch -gt $$today_epoch ]; then \
		echo "ERROR: END_DATE ($$END_DATE_VAL) is in the future" >&2; exit 2; \
	fi; \
	span_days=$$(( (end_epoch - start_epoch) / 86400 + 1 )); \
	if [ $$span_days -gt 90 ]; then \
		echo "ERROR: range is $$span_days calendar days, exceeds 90-day limit" >&2; exit 2; \
	fi
	+@START_DATE_VAL='$(START_DATE)'; END_DATE_VAL='$(END_DATE)'; \
	span=$$(( ( $$(date -d "$$END_DATE_VAL" +%s) - $$(date -d "$$START_DATE_VAL" +%s) ) / 86400 + 1 )); \
	echo "personal-backfill: $$START_DATE_VAL -> $$END_DATE_VAL (span=$$span days)"; \
	cur=$$START_DATE_VAL; end=$$END_DATE_VAL; \
	while [ "$$cur" \< "$$end" ] || [ "$$cur" = "$$end" ]; do \
		dow=$$(date -d "$$cur" +%u); \
		if [ $$dow -ge 1 ] && [ $$dow -le 5 ]; then \
			echo "[backfill] $$cur: running personal-daily-run"; \
			if $(MAKE) -s personal-daily-run TRADE_DATE="$$cur" \
				$(if $(UNIVERSE),UNIVERSE='$(UNIVERSE)') \
				$(if $(POLICY),POLICY='$(POLICY)') \
				$(if $(CONFIRM_NETWORK),CONFIRM_NETWORK=$(CONFIRM_NETWORK)); then \
				echo "[backfill] $$cur: ok"; \
			else \
				rc=$$?; echo "[backfill] $$cur: FAILED (exit $$rc)" >&2; exit $$rc; \
			fi; \
		else \
			echo "[backfill] $$cur: skip (weekend)"; \
		fi; \
		if [ "$$cur" = "$$end" ]; then break; fi; \
		cur=$$(date -d "$$cur + 1 day" +%Y-%m-%d); \
	done
	@echo "personal-backfill: completed"
