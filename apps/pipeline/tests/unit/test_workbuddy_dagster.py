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
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "result_sector.json").write_text("{}", encoding="utf-8")
    assert wb._has_pending_candidates(source) is False
    (source / "candidates_stock.json").write_text("{}", encoding="utf-8")
    assert wb._has_pending_candidates(source) is True


def test_schedule_skips_without_candidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.SkipReason)
    assert "no candidates_*.json" in result.skip_message


def test_schedule_requests_run_with_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "candidates_stock.json").write_text(json.dumps({}), encoding="utf-8")
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.RunRequest)
    assert result.run_key == "workbuddy-import:2026-08-14T16:10:00"
    assert result.tags["trigger_type"] == "schedule"
    assert result.tags["bridge_root"] == str(tmp_path.resolve())
    assert result.tags["pending_source"] == "candidates_json"


def test_schedule_skips_when_only_stage_ready_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge_root = tmp_path
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    results = bridge_root / "research" / "results"
    results.mkdir(parents=True)
    (results / "case-9.ready").mkdir()
    settings = Settings(workbuddy_bridge_root=bridge_root, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.SkipReason)
    assert "no candidates_*.json" in result.skip_message
    assert "stage-ready" not in result.skip_message


def test_schedule_still_skips_when_stage_ready_present_alongside_missing_candidates_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge_root = tmp_path
    source = tmp_path / "missing-source-dir"
    results = bridge_root / "observation" / "results"
    results.mkdir(parents=True)
    (results / "obs-1.ready").mkdir()
    settings = Settings(workbuddy_bridge_root=bridge_root, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.SkipReason)
    assert "no candidates_*.json" in result.skip_message


def test_has_pending_candidates_recognizes_real_ready_directory(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "ready-001.ready").mkdir()
    assert wb._has_pending_candidates(source) is True


def test_has_pending_candidates_ignores_malformed_temporary_and_file_entries(
    tmp_path: Path,
) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / ".ready").mkdir()
    (source / "with space.ready").mkdir()
    (source / "tmp-001.tmp").mkdir()
    (source / "ready-file.ready").write_text("not a directory", encoding="utf-8")
    assert wb._has_pending_candidates(source) is False


def test_has_pending_candidates_ignores_symlink_ready_directory(tmp_path: Path) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (source / "linked.ready").symlink_to(target)
    assert wb._has_pending_candidates(source) is False


def test_schedule_requests_run_when_only_real_ready_directory_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    (source / "ready-002.ready").mkdir()
    settings = Settings(workbuddy_bridge_root=tmp_path, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.RunRequest)
    assert result.run_key == "workbuddy-import:2026-08-14T16:10:00"
    assert result.tags["trigger_type"] == "schedule"
    assert result.tags["bridge_root"] == str(tmp_path.resolve())
    assert result.tags["pending_source"] == "ready_directory"


def test_schedule_skips_when_only_observation_stage_ready_directory_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bridge_root = tmp_path
    source = tmp_path / "candidate" / "results"
    source.mkdir(parents=True)
    observation = bridge_root / "observation" / "results"
    observation.mkdir(parents=True)
    (observation / "obs-9.ready").mkdir()
    settings = Settings(workbuddy_bridge_root=bridge_root, workbuddy_source_dir=source)
    monkeypatch.setattr(wb, "get_settings", lambda: settings)

    result = wb.workbuddy_result_import_schedule(_context())

    assert isinstance(result, dg.SkipReason)
    assert "no candidates_*.json" in result.skip_message
    assert "*.ready" in result.skip_message


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
