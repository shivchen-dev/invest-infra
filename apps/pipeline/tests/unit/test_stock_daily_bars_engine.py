"""Unit tests for stock_daily_bars_engine dataclasses."""

from __future__ import annotations

import dataclasses
from datetime import date
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from invest_domain.pipeline import PipelineRunStatus
from invest_pipeline.stock_daily_bars_engine import (
    StockDailyBarsCommand,
    StockDailyBarsOutcome,
)

# ---------------------------------------------------------------------------
# StockDailyBarsCommand
# ---------------------------------------------------------------------------


def test_command_defaults_are_sensible() -> None:
    cmd = StockDailyBarsCommand(trade_date=date(2024, 1, 15))

    assert cmd.trade_date == date(2024, 1, 15)
    assert cmd.trigger_type == "dagster"
    assert cmd.run_id is None
    assert cmd.config_snapshot is None


def test_command_full_construction() -> None:
    rid = uuid4()
    cfg = {"lookback_days": 30, "max_retries": 3}
    cmd = StockDailyBarsCommand(
        trade_date=date(2024, 5, 1),
        trigger_type="manual",
        run_id=rid,
        config_snapshot=cfg,
    )

    assert cmd.trigger_type == "manual"
    assert cmd.run_id == rid
    assert isinstance(cmd.run_id, UUID)
    assert cmd.config_snapshot["lookback_days"] == 30
    assert cmd.config_snapshot["max_retries"] == 3


def test_command_is_frozen() -> None:
    cmd = StockDailyBarsCommand(trade_date=date(2024, 1, 1))

    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.trade_date = date(2024, 2, 1)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.trigger_type = "manual"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        cmd.run_id = uuid4()  # type: ignore[misc]


def test_command_config_snapshot_is_isolated_from_source_mapping() -> None:
    cfg = {"lookback_days": 30}
    cmd = StockDailyBarsCommand(
        trade_date=date(2024, 1, 1), config_snapshot=cfg
    )

    cfg["lookback_days"] = 999
    cfg["new_key"] = "leak"
    del cfg["lookback_days"]

    assert cmd.config_snapshot["lookback_days"] == 30
    assert "new_key" not in cmd.config_snapshot


def test_command_config_snapshot_is_read_only_mapping() -> None:
    cmd = StockDailyBarsCommand(
        trade_date=date(2024, 1, 1), config_snapshot={"x": 1}
    )

    assert isinstance(cmd.config_snapshot, MappingProxyType)
    with pytest.raises(TypeError):
        cmd.config_snapshot["y"] = 2  # type: ignore[index]


def test_command_invalid_trade_date_type_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsCommand(trade_date="2024-01-01")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        StockDailyBarsCommand(trade_date=20240101)  # type: ignore[arg-type]


def test_command_blank_trigger_type_rejected() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsCommand(trade_date=date(2024, 1, 1), trigger_type="")
    with pytest.raises(ValueError):
        StockDailyBarsCommand(
            trade_date=date(2024, 1, 1), trigger_type="   "
        )


def test_command_non_string_trigger_type_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsCommand(
            trade_date=date(2024, 1, 1), trigger_type=123  # type: ignore[arg-type]
        )


def test_command_config_keys_are_not_confused_with_error_summary_validation() -> None:
    cmd = StockDailyBarsCommand(
        trade_date=date(2024, 1, 1),
        config_snapshot={"api_key": "redacted", "mode": "fast"},
    )
    assert cmd.config_snapshot["mode"] == "fast"


def test_command_invalid_run_id_type_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsCommand(
            trade_date=date(2024, 1, 1),
            run_id="not-a-uuid",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# StockDailyBarsOutcome
# ---------------------------------------------------------------------------


def test_outcome_success_defaults() -> None:
    out = StockDailyBarsOutcome(
        status=PipelineRunStatus.SUCCEEDED, inserted=10, skipped=2
    )

    assert out.status == PipelineRunStatus.SUCCEEDED
    assert out.inserted == 10
    assert out.skipped == 2
    assert out.record_count == 0
    assert out.fallback_used is False
    assert out.error_summary is None
    assert out.provider_key is None
    assert out.request_id is None
    assert out.attempt_id is None
    assert out.batch_id is None


def test_outcome_partial_with_error_summary() -> None:
    out = StockDailyBarsOutcome(
        status=PipelineRunStatus.PARTIAL,
        provider_key="polygon",
        inserted=5,
        skipped=3,
        error_summary="3 rows failed validation",
    )

    assert out.status == PipelineRunStatus.PARTIAL
    assert out.provider_key == "polygon"
    assert out.error_summary == "3 rows failed validation"


def test_outcome_failed_with_error_summary() -> None:
    out = StockDailyBarsOutcome(
        status=PipelineRunStatus.FAILED,
        error_summary="provider timeout",
    )

    assert out.status == PipelineRunStatus.FAILED
    assert out.error_summary == "provider timeout"


def test_outcome_string_status_is_canonicalized() -> None:
    lower = StockDailyBarsOutcome(status="succeeded", inserted=1)
    upper = StockDailyBarsOutcome(status="FAILED", error_summary="x")
    partial = StockDailyBarsOutcome(
        status="partial", error_summary="y"
    )

    assert lower.status == PipelineRunStatus.SUCCEEDED
    assert upper.status == PipelineRunStatus.FAILED
    assert partial.status == PipelineRunStatus.PARTIAL
    assert isinstance(lower.status, PipelineRunStatus)


def test_outcome_invalid_status_rejected() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(status="not_a_status")
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(status="bogus")


def test_outcome_error_summary_rejected_on_success() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED,
            error_summary="boom",
        )


def test_outcome_error_summary_rejected_on_running() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.RUNNING,
            error_summary="oops",
        )


def test_outcome_error_summary_rejected_on_pending() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.QUEUED,
            error_summary="still waiting",
        )


def test_outcome_negative_counts_rejected() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED, record_count=-1
        )
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED, inserted=-5
        )
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED, skipped=-2
        )


def test_outcome_non_int_count_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED, inserted="5"  # type: ignore[arg-type]
        )


def test_outcome_is_frozen() -> None:
    out = StockDailyBarsOutcome(status=PipelineRunStatus.SUCCEEDED)

    with pytest.raises(dataclasses.FrozenInstanceError):
        out.status = PipelineRunStatus.FAILED  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.inserted = 999  # type: ignore[misc]


def test_outcome_full_field_assignment() -> None:
    rid = uuid4()
    aid = uuid4()
    bid = uuid4()
    out = StockDailyBarsOutcome(
        status="partial",
        provider_key="polygon",
        request_id=rid,
        attempt_id=aid,
        batch_id=bid,
        record_count=10,
        inserted=7,
        skipped=3,
        fallback_used=True,
        error_summary="partial failure",
    )

    assert out.provider_key == "polygon"
    assert out.request_id == rid
    assert out.attempt_id == aid
    assert out.batch_id == bid
    assert out.record_count == 10
    assert out.inserted == 7
    assert out.skipped == 3
    assert out.fallback_used is True
    assert out.error_summary == "partial failure"
    assert out.status == PipelineRunStatus.PARTIAL


def test_outcome_blank_provider_key_rejected() -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(
        status=PipelineRunStatus.SUCCEEDED, provider_key="   "
        )


def test_outcome_invalid_uuid_fields_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED,
            request_id="not-a-uuid",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED,
            attempt_id="not-a-uuid",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED,
            batch_id="not-a-uuid",  # type: ignore[arg-type]
        )


def test_outcome_non_bool_fallback_rejected() -> None:
    with pytest.raises(TypeError):
        StockDailyBarsOutcome(
            status=PipelineRunStatus.SUCCEEDED,
            fallback_used=1,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("summary", [
    "api_key leaked",
    "ACCESS_TOKEN leaked",
    "token=abc",
    "password leaked",
    "client secret leaked",
])
def test_outcome_sensitive_error_summary_rejected(summary: str) -> None:
    with pytest.raises(ValueError):
        StockDailyBarsOutcome(status=PipelineRunStatus.FAILED, error_summary=summary)
