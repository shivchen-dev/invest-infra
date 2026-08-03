from __future__ import annotations

from datetime import date, datetime

import dagster as dg
import pytest
from invest_pipeline.daily_preflight import evaluate_daily_preflight
from invest_pipeline.schedules import _auto_schedule_enabled, personal_etf_daily_schedule

WEEKDAY = date(2026, 7, 30)


def _evaluate(**overrides: object):
    values = {
        "trade_date": WEEKDAY,
        "provider_key": "fixture_dev",
        "personal_universe_loader": lambda: object(),
        "published_run_exists": lambda _date: False,
        "running_run_exists": lambda _date: False,
    }
    values.update(overrides)
    return evaluate_daily_preflight(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "decision", "reason"),
    [
        (
            {"trade_date": date(2026, 8, 3), "today": date(2026, 7, 30)},
            "fail",
            "future_date",
        ),
        ({"trade_date": date(2026, 8, 1)}, "skip", "skip_non_business_day"),
        ({"provider_key": "unknown"}, "fail", "provider_not_configured"),
        ({"personal_universe_loader": lambda: None}, "fail", "personal_universe_unavailable"),
        ({"published_run_exists": lambda _date: True}, "skip", "skip_already_published"),
        ({"running_run_exists": lambda _date: True}, "skip", "skip_already_running"),
        ({"data_ready_checker": lambda _date: False}, "skip", "skip_data_not_ready"),
        ({"data_ready_checker": lambda _date: 1 / 0}, "fail", "data_check_failed"),
    ],
)
def test_preflight_branches(overrides, decision: str, reason: str) -> None:
    result = _evaluate(**overrides)
    assert (result.decision, result.reason) == (decision, reason)


def test_preflight_ready() -> None:
    assert _evaluate().decision == "run"
    assert _evaluate().reason == "ready"


def test_preflight_catches_universe_loader_error() -> None:
    result = _evaluate(personal_universe_loader=lambda: 1 / 0)
    assert (result.decision, result.reason) == ("fail", "personal_universe_unavailable")


def test_schedule_emits_stable_run_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("invest_pipeline.schedules._load_default_universe", lambda: object())
    monkeypatch.setattr("invest_pipeline.schedules._published_run_exists", lambda _date: False)
    monkeypatch.setattr("invest_pipeline.schedules._running_run_exists", lambda _date: False)
    context = dg.ScheduleEvaluationContext(
        instance_ref=None,
        scheduled_execution_time=datetime(2026, 7, 30, 8, 10),
    )
    result = personal_etf_daily_schedule(context)
    assert isinstance(result, dg.RunRequest)
    assert result.run_key == "personal-etf-daily:2026-07-30"
    assert result.partition_key == "2026-07-30"
    assert result.tags == {"trade_date": "2026-07-30", "trigger_type": "schedule"}


def test_schedule_is_stopped_by_default() -> None:
    assert personal_etf_daily_schedule.default_status == dg.DefaultScheduleStatus.STOPPED


def test_auto_schedule_flag_requires_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED", "TrUe")
    assert _auto_schedule_enabled() is True
    monkeypatch.setenv("INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED", "1")
    assert _auto_schedule_enabled() is False
