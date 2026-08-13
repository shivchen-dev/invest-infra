from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from invest_domain.pipeline import PipelineRunStatus
from invest_pipeline.provider_health import (
    ProviderHealthSnapshot,
    ProviderHealthStatus,
)
from invest_pipeline.provider_routing.datasets import Dataset
from invest_pipeline.stock_daily_bars_application import StockDailyBarsEngine
from invest_pipeline.stock_daily_bars_engine import StockDailyBarsCommand


def make_command():
    return StockDailyBarsCommand(trade_date=date(2026, 8, 13))


def make_raw(request_status="succeeded"):
    return SimpleNamespace(
        request_status=request_status,
        request_id=uuid4(),
        attempt_id=uuid4(),
        batch_id=uuid4(),
        record_count=2,
        provider_key="provider-key",
        fallback_used=False,
    )


def make_published():
    return SimpleNamespace(inserted=2, skipped=0)


def execute_engine(
    raw,
    published=None,
    *,
    resolver_error=None,
    ingest_error=None,
    publisher_error=None,
):
    calls = []
    provider = SimpleNamespace(name="resolved-provider")

    def resolver(command):
        calls.append(("resolver", command))
        if resolver_error is not None:
            raise resolver_error
        return provider

    def raw_ingestor(provider_arg, command):
        calls.append(("raw_ingestor", provider_arg, command))
        if ingest_error is not None:
            raise ingest_error
        return raw

    def core_publisher(raw_arg, command):
        calls.append(("core_publisher", raw_arg, command))
        if publisher_error is not None:
            raise publisher_error
        return published

    engine = StockDailyBarsEngine(resolver, raw_ingestor, core_publisher)
    return engine.execute(make_command()), calls


def test_success_preserves_order_and_outcome_fields():
    raw = make_raw()
    published = make_published()

    outcome, calls = execute_engine(raw, published)

    assert [call[0] for call in calls] == [
        "resolver",
        "raw_ingestor",
        "core_publisher",
    ]
    assert outcome.status is PipelineRunStatus.SUCCEEDED
    assert outcome.request_id == raw.request_id
    assert outcome.attempt_id == raw.attempt_id
    assert outcome.batch_id == raw.batch_id
    assert outcome.record_count == raw.record_count
    assert outcome.provider_key == raw.provider_key
    assert outcome.fallback_used is raw.fallback_used
    assert outcome.inserted == published.inserted
    assert outcome.skipped == published.skipped
    assert outcome.error_summary is None


@pytest.mark.parametrize(
    ("request_status", "pipeline_status"),
    [
        ("failed", PipelineRunStatus.FAILED),
        ("partial", PipelineRunStatus.PARTIAL),
    ],
)
def test_failed_or_partial_raw_short_circuits_publisher(
    request_status, pipeline_status
):
    outcome, calls = execute_engine(make_raw(request_status), make_published())

    assert [call[0] for call in calls] == ["resolver", "raw_ingestor"]
    assert outcome.status is pipeline_status


@pytest.mark.parametrize("stage", ["resolver", "ingest", "publisher"])
def test_stage_exception_returns_failed(stage):
    error = RuntimeError(f"{stage} exploded")
    outcome, _ = execute_engine(
        make_raw(),
        make_published(),
        resolver_error=error if stage == "resolver" else None,
        ingest_error=error if stage == "ingest" else None,
        publisher_error=error if stage == "publisher" else None,
    )

    assert outcome.status is PipelineRunStatus.FAILED


def test_sensitive_exception_summary_is_redacted():
    error = RuntimeError(
        "api_key=key access_token=access token=token password=p secret=secret"
    )

    outcome, _ = execute_engine(make_raw(), make_published(), ingest_error=error)

    summary = str(outcome.error_summary).lower()
    assert outcome.status is PipelineRunStatus.FAILED
    for sensitive in ("api_key", "access_token", "token=", "password", "secret"):
        assert sensitive not in summary


def make_health_snapshot(
    status: ProviderHealthStatus,
    *,
    provider_key: str = "provider-key",
) -> ProviderHealthSnapshot:
    return ProviderHealthSnapshot(
        provider_key=provider_key,
        dataset=Dataset.STOCK_MINUTE_BARS,
        status=status,
        as_of=date(2026, 8, 13),
        freshness_days=0,
        quality_score=Decimal("1"),
        coverage_ratio=Decimal("1"),
        completeness_ratio=Decimal("1"),
        failed_symbols=(),
    )


def execute_engine_with_preflight(
    raw,
    published,
    *,
    preflight,
    preflight_error=None,
):
    calls: list[tuple[str, ...]] = []
    provider = SimpleNamespace(name="resolved-provider")

    def resolver(command):
        calls.append(("resolver", command))
        return provider

    def raw_ingestor(provider_arg, command):
        calls.append(("raw_ingestor", provider_arg, command))
        return raw

    def core_publisher(raw_arg, command):
        calls.append(("core_publisher", raw_arg, command))
        return published

    def health_preflight(command):
        calls.append(("preflight", command))
        if preflight_error is not None:
            raise preflight_error
        return preflight

    engine = StockDailyBarsEngine(
        resolver,
        raw_ingestor,
        core_publisher,
        health_preflight=health_preflight,
    )
    return engine.execute(make_command()), calls


def test_preflight_default_is_none_and_preserves_flow():
    raw = make_raw()
    published = make_published()

    outcome, calls = execute_engine(raw, published)

    assert [call[0] for call in calls] == [
        "resolver",
        "raw_ingestor",
        "core_publisher",
    ]
    assert outcome.status is PipelineRunStatus.SUCCEEDED


def test_preflight_healthy_continues_existing_flow():
    raw = make_raw()
    published = make_published()
    snapshot = make_health_snapshot(ProviderHealthStatus.HEALTHY)

    outcome, calls = execute_engine_with_preflight(
        raw,
        published,
        preflight=snapshot,
    )

    assert [call[0] for call in calls] == [
        "preflight",
        "resolver",
        "raw_ingestor",
        "core_publisher",
    ]
    assert outcome.status is PipelineRunStatus.SUCCEEDED
    assert outcome.inserted == published.inserted
    assert outcome.error_summary is None


def test_preflight_none_return_value_continues_existing_flow():
    raw = make_raw()
    published = make_published()

    outcome, calls = execute_engine_with_preflight(
        raw,
        published,
        preflight=None,
    )

    assert [call[0] for call in calls] == [
        "preflight",
        "resolver",
        "raw_ingestor",
        "core_publisher",
    ]
    assert outcome.status is PipelineRunStatus.SUCCEEDED


@pytest.mark.parametrize(
    "status",
    [
        ProviderHealthStatus.UNKNOWN,
        ProviderHealthStatus.DISABLED,
        ProviderHealthStatus.STALE,
        ProviderHealthStatus.DEGRADED,
    ],
)
def test_preflight_non_healthy_fails_closed(status):
    snapshot = make_health_snapshot(status)

    outcome, calls = execute_engine_with_preflight(
        make_raw(),
        make_published(),
        preflight=snapshot,
    )

    assert [call[0] for call in calls] == ["preflight"]
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.error_summary == "provider health preflight not healthy"
    assert outcome.inserted == 0
    assert outcome.skipped == 0
    assert outcome.provider_key is None
    assert outcome.request_id is None
    assert outcome.attempt_id is None
    assert outcome.batch_id is None
    assert outcome.record_count == 0


def test_preflight_non_healthy_blocks_resolver_and_ingestor_and_publisher():
    snapshot = make_health_snapshot(ProviderHealthStatus.DEGRADED)

    outcome, calls = execute_engine_with_preflight(
        make_raw(),
        make_published(),
        preflight=snapshot,
    )

    assert outcome.status is PipelineRunStatus.FAILED
    assert "resolver" not in {call[0] for call in calls}
    assert "raw_ingestor" not in {call[0] for call in calls}
    assert "core_publisher" not in {call[0] for call in calls}


def test_preflight_exception_is_caught_and_redacted():
    error = RuntimeError(
        "api_key=key access_token=access token=token password=p secret=secret"
    )

    outcome, calls = execute_engine_with_preflight(
        make_raw(),
        make_published(),
        preflight=None,
        preflight_error=error,
    )

    summary = str(outcome.error_summary).lower()
    assert outcome.status is PipelineRunStatus.FAILED
    assert [call[0] for call in calls] == ["preflight"]
    assert summary.startswith("runtimeerror:")
    for sensitive in ("api_key", "access_token", "token=", "password", "secret"):
        assert sensitive not in summary


def test_health_preflight_is_keyword_only():
    snapshot = make_health_snapshot(ProviderHealthStatus.HEALTHY)

    def resolver(command):
        return SimpleNamespace(provider_key="p")

    def raw_ingestor(provider, command):
        return make_raw()

    def core_publisher(raw, command):
        return make_published()

    with pytest.raises(TypeError):
        StockDailyBarsEngine(
            resolver,
            raw_ingestor,
            core_publisher,
            lambda command: snapshot,
        )
