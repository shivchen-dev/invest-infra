from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import dagster as dg
import pytest
from invest_pipeline import workbuddy_dagster as wb
from invest_pipeline.config import Settings


def _context() -> dg.ScheduleEvaluationContext:
    return dg.ScheduleEvaluationContext(
        instance_ref=None,
        scheduled_execution_time=datetime(2026, 8, 14, 16, 10),
    )


def test_auto_schedule_switch_is_independent_and_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(wb._AUTO_SCHEDULE_ENV, raising=False)
    monkeypatch.setenv("INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED", "true")
    assert wb._auto_schedule_enabled() is False

    monkeypatch.setenv(wb._AUTO_SCHEDULE_ENV, "true")
    assert wb._auto_schedule_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "1", "yes"])
def test_auto_schedule_switch_requires_true(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(wb._AUTO_SCHEDULE_ENV, value)
    assert wb._auto_schedule_enabled() is False


def test_candidate_parser_only_accepts_candidates_glob(tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    (source / "result_sector.json").write_text("{}", encoding="utf-8")
    assert wb._has_pending_candidates(source) is False
    (source / "candidates_stock.json").write_text("{}", encoding="utf-8")
    assert wb._has_pending_candidates(source) is True


def test_schedule_skips_without_candidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "选股报告"
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.SkipReason)
    assert "no candidates_*.json" in result.skip_message


def test_schedule_requests_run_with_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "选股报告"
    source.mkdir()
    (source / "candidates_stock.json").write_text(json.dumps({}), encoding="utf-8")
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.RunRequest)
    assert result.run_key == "workbuddy-import:2026-08-14T16:10:00"
    assert result.tags == {"trigger_type": "schedule", "bridge_root": str(tmp_path)}


def test_schedule_definition_is_weekday_every_five_minutes_and_stopped() -> None:
    assert wb.workbuddy_result_import_schedule.cron_schedule == "*/5 * * * 1-5"
    assert wb.workbuddy_result_import_schedule.execution_timezone == "Asia/Shanghai"
    assert wb.workbuddy_result_import_schedule.default_status == dg.DefaultScheduleStatus.STOPPED


def test_op_delegates_to_existing_import_entry_without_real_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=tmp_path / "reports")
    captured: dict[str, object] = {}

    def fake_import(bridge_root, source_dir, *, settings):
        captured.update(
            bridge_root=bridge_root,
            source_dir=source_dir,
            database_url=settings.database_url,
        )
        return 0

    result = wb._run_workbuddy_import(settings=settings, importer=fake_import)

    assert result == 0
    assert captured == {
        "bridge_root": tmp_path.resolve(),
        "source_dir": (tmp_path / "reports").resolve(),
        "database_url": settings.database_url,
    }


def test_definitions_loads_existing_and_workbuddy_definitions() -> None:
    from invest_pipeline.definitions import defs

    assert {job.name for job in defs.jobs or []} >= {
        "personal_etf_daily_job",
        "real_exposure_job",
        "stock_market_data_job",
        "workbuddy_import_job",
    }
    assert {schedule.name for schedule in defs.schedules or []} >= {
        "personal_etf_daily_schedule",
        "workbuddy_result_import_schedule",
    }
