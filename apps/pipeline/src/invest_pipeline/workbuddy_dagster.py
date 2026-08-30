"""Dagster orchestration for importing WorkBuddy candidate results."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import dagster as dg

from invest_pipeline.config import Settings, get_settings
from invest_pipeline.workbuddy_bridge_cli import run_import

_AUTO_SCHEDULE_ENV = "INVEST_PIPELINE_WORKBUDDY_AUTO_SCHEDULE_ENABLED"

_READY_DIR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.ready$")


def _auto_schedule_enabled() -> bool:
    return os.environ.get(_AUTO_SCHEDULE_ENV, "").strip().lower() == "true"


def _resolve_paths(settings: Settings | None = None) -> tuple[Path, Path]:
    configured = settings or get_settings()
    return configured.workbuddy_bridge_root.resolve(), configured.workbuddy_source_dir.resolve()


def _has_legacy_candidate_file(source_dir: Path) -> bool:
    return source_dir.is_dir() and any(source_dir.glob("candidates_*.json"))


def _has_real_ready_directory(source_dir: Path) -> bool:
    if not source_dir.is_dir():
        return False
    return any(
        not child.is_symlink()
        and child.is_dir()
        and bool(_READY_DIR_RE.fullmatch(child.name))
        for child in source_dir.iterdir()
    )


def _has_pending_candidates(source_dir: Path) -> bool:
    return _has_legacy_candidate_file(source_dir) or _has_real_ready_directory(source_dir)


def _pending_kind(source_dir: Path) -> str | None:
    if _has_legacy_candidate_file(source_dir):
        return "candidates_json"
    if _has_real_ready_directory(source_dir):
        return "ready_directory"
    return None


def _run_workbuddy_import(
    *, settings: Settings | None = None, importer: Callable[..., int] = run_import
) -> int:
    configured = settings or get_settings()
    bridge_root, source_dir = _resolve_paths(configured)
    return importer(bridge_root, source_dir, settings=configured)


@dg.op(name="workbuddy_import_op")
def import_workbuddy_candidates_op(context) -> None:
    """Import visible WorkBuddy candidates through the existing Bridge CLI entry."""
    result = _run_workbuddy_import()
    context.log.info("WorkBuddy import completed with return code %d", result)
    if result != 0:
        raise RuntimeError("WorkBuddy import failed")


@dg.job(name="workbuddy_import_job")
def workbuddy_result_import_job() -> None:
    import_workbuddy_candidates_op()


@dg.schedule(
    job=workbuddy_result_import_job,
    cron_schedule="*/5 * * * 1-5",
    execution_timezone="Asia/Shanghai",
    default_status=(
        dg.DefaultScheduleStatus.RUNNING
        if _auto_schedule_enabled()
        else dg.DefaultScheduleStatus.STOPPED
    ),
)
def workbuddy_result_import_schedule(context: dg.ScheduleEvaluationContext):
    """Run when a completed WorkBuddy candidate file or ready package directory is visible."""
    bridge_root, source_dir = _resolve_paths()
    pending_kind = _pending_kind(source_dir)
    if pending_kind is None:
        return dg.SkipReason(
            f"no candidates_*.json or *.ready directory under {source_dir}"
        )
    scheduled_at = context.scheduled_execution_time.replace(microsecond=0).isoformat()
    return dg.RunRequest(
        run_key=f"workbuddy-import:{scheduled_at}",
        tags={
            "trigger_type": "schedule",
            "bridge_root": str(bridge_root),
            "pending_source": pending_kind,
        },
    )


__all__ = [
    "import_workbuddy_candidates_op",
    "workbuddy_result_import_job",
    "workbuddy_result_import_schedule",
    "_auto_schedule_enabled",
    "_has_pending_candidates",
    "_resolve_paths",
    "_run_workbuddy_import",
]
