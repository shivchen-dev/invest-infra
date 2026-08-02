"""Dagster schedules for the personal daily pipeline."""

from __future__ import annotations

import os
from datetime import date

import dagster as dg
from invest_storage.database import build_engine, session_factory
from invest_storage.models import CandidatePoolRunRow, PipelineRunRow
from sqlalchemy import select

from invest_pipeline.config import get_settings
from invest_pipeline.daily_preflight import evaluate_daily_preflight
from invest_pipeline.personal_universe import load_personal_universe

_AUTO_SCHEDULE_ENV = "INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED"


def _auto_schedule_enabled() -> bool:
    return os.environ.get(_AUTO_SCHEDULE_ENV, "").strip().lower() == "true"


def _load_default_universe() -> object:
    return load_personal_universe(get_settings().personal_universe_path)


def _published_run_exists(trade_date: date) -> bool:
    engine = build_engine(get_settings().database_url)
    try:
        with session_factory(engine)() as session:
            return session.scalar(
                select(CandidatePoolRunRow.id).where(
                    CandidatePoolRunRow.trade_date == trade_date,
                    CandidatePoolRunRow.status == "published",
                )
            ) is not None
    finally:
        engine.dispose()


def _running_run_exists(trade_date: date) -> bool:
    engine = build_engine(get_settings().database_url)
    try:
        with session_factory(engine)() as session:
            return session.scalar(
                select(PipelineRunRow.id).where(
                    PipelineRunRow.job_key == "personal_etf_daily_job",
                    PipelineRunRow.partition_key == trade_date.isoformat(),
                    PipelineRunRow.status == "running",
                )
            ) is not None
    finally:
        engine.dispose()


@dg.schedule(
    job_name="personal_etf_daily_job",
    cron_schedule="10 16 * * 1-5",
    execution_timezone="Asia/Shanghai",
    default_status=(
        dg.DefaultScheduleStatus.RUNNING
        if _auto_schedule_enabled()
        else dg.DefaultScheduleStatus.STOPPED
    ),
)
def personal_etf_daily_schedule(context: dg.ScheduleEvaluationContext):
    """Create one stable daily RunRequest after pure preflight checks."""

    trade_date: date = context.scheduled_execution_time.date()
    result = evaluate_daily_preflight(
        trade_date=trade_date,
        provider_key=get_settings().provider_key,
        personal_universe_loader=_load_default_universe,
        published_run_exists=_published_run_exists,
        running_run_exists=_running_run_exists,
    )
    if result.decision == "skip":
        return dg.SkipReason(result.reason)
    if result.decision == "fail":
        raise RuntimeError(f"daily preflight failed: {result.reason}")
    return dg.RunRequest(
        run_key=f"personal-etf-daily:{trade_date.isoformat()}",
        partition_key=trade_date.isoformat(),
        tags={"trade_date": trade_date.isoformat(), "trigger_type": "schedule"},
    )
