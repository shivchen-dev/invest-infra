FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /workspace
COPY packages/domain /workspace/packages/domain
COPY packages/storage /workspace/packages/storage
COPY apps/pipeline /workspace/apps/pipeline

WORKDIR /workspace/apps/pipeline
RUN uv sync --no-dev

ENV DAGSTER_HOME=/workspace/.dagster
RUN mkdir -p /workspace/.dagster && printf 'telemetry:\n  enabled: false\n' > /workspace/.dagster/dagster.yaml

EXPOSE 3000
CMD ["uv", "run", "dagster", "dev", "-m", "invest_pipeline.definitions", "-h", "0.0.0.0", "-p", "3000"]
