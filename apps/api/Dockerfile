FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /workspace

COPY packages/domain /workspace/packages/domain
COPY packages/storage /workspace/packages/storage
COPY apps/api /workspace/apps/api

WORKDIR /workspace/apps/api
RUN uv sync --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "invest_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
