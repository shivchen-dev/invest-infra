"""Integration tests for :class:`SqlAlchemyPipelineRunRepository`.

Each test runs inside the savepoint-isolated ``db_session`` fixture
defined in :mod:`tests.storage.integration.conftest`. The fixture spins
up a disposable PostgreSQL container via Testcontainers and rolls back
every change after the test, so the four tests in this file can share a
single container without leaking data between cases.

The fixtures create the ``app.pipeline_runs`` schema (with the
``created_at`` / ``updated_at`` columns and the status ``CHECK``
constraint introduced in migration ``20260730_0004``) directly through
``Base.metadata.create_all``. The repository only relies on the
SQLAlchemy model so the migration is exercised on a real PostgreSQL
deployment rather than re-implemented in the fixture.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_storage import SqlAlchemyPipelineRunRepository
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def pipeline_run_repository(db_session) -> Iterator[SqlAlchemyPipelineRunRepository]:
    """Yield a fresh :class:`SqlAlchemyPipelineRunRepository` per test."""

    yield SqlAlchemyPipelineRunRepository(db_session)


def _new_run(
    *,
    job_name: str = "etf_daily",
    algorithm_version: str = "v1.0",
    started_at: datetime | None = None,
) -> PipelineRun:
    return PipelineRun(
        job_name=job_name,
        algorithm_version=algorithm_version,
        status=PipelineRunStatus.PENDING,
        started_at=started_at or datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
    )


def test_start_and_complete_full_lifecycle(
    pipeline_run_repository: SqlAlchemyPipelineRunRepository,
) -> None:
    """``start`` -> ``mark_succeeded`` round-trip persists every column."""

    started_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished_at = started_at + timedelta(minutes=5)
    run = _new_run(job_name="etf_daily", started_at=started_at)

    started = pipeline_run_repository.start(run)

    assert isinstance(started, PipelineRun)
    assert started.id is not None
    assert started.status_value == "running"
    assert started.finished_at is None
    assert started.error_message is None
    assert started.created_at is not None
    assert started.updated_at is not None

    completed = pipeline_run_repository.mark_succeeded(
        started.id, finished_at=finished_at
    )

    assert completed.id == started.id
    assert completed.status_value == "succeeded"
    assert completed.finished_at == finished_at
    assert completed.error_message is None

    fetched = pipeline_run_repository.get_by_id(started.id)
    assert fetched is not None
    assert fetched.status_value == "succeeded"
    assert fetched.finished_at == finished_at
    assert fetched.error_message is None


def test_mark_failed_records_error_message(
    pipeline_run_repository: SqlAlchemyPipelineRunRepository,
) -> None:
    """``mark_failed`` stores the error message and finishes the run."""

    started_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    finished_at = started_at + timedelta(seconds=42)
    started = pipeline_run_repository.start(_new_run(started_at=started_at))

    failed = pipeline_run_repository.mark_failed(
        started.id, error="provider timeout", finished_at=finished_at
    )

    assert failed.status_value == "failed"
    assert failed.error_message == "provider timeout"
    assert failed.finished_at == finished_at

    fetched = pipeline_run_repository.get_by_id(started.id)
    assert fetched is not None
    assert fetched.error_message == "provider timeout"
    assert fetched.status_value == "failed"

    assert pipeline_run_repository.count_by_status("failed") == 1
    assert pipeline_run_repository.count_by_status("succeeded") == 0


def test_concurrent_runs_have_distinct_ids(
    pipeline_run_repository: SqlAlchemyPipelineRunRepository,
) -> None:
    """Two ``start`` calls in the same session produce distinct UUIDs."""

    base = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    first = pipeline_run_repository.start(
        _new_run(job_name="etf_daily", started_at=base)
    )
    second = pipeline_run_repository.start(
        _new_run(
            job_name="etf_daily",
            algorithm_version="v1.1",
            started_at=base + timedelta(seconds=1),
        )
    )

    assert first.id is not None
    assert second.id is not None
    assert first.id != second.id
    assert first.algorithm_version == "v1.0"
    assert second.algorithm_version == "v1.1"
    assert pipeline_run_repository.count_by_status("running") == 2


def test_list_recent_filters_by_status(
    pipeline_run_repository: SqlAlchemyPipelineRunRepository,
) -> None:
    """``list_recent`` returns the runs ordered by ``started_at`` desc."""

    base = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    runs = [
        pipeline_run_repository.start(
            _new_run(
                job_name="etf_daily",
                started_at=base + timedelta(minutes=offset),
            )
        )
        for offset in range(4)
    ]
    succeeded_target = runs[1]
    finished = base + timedelta(minutes=2)
    pipeline_run_repository.mark_succeeded(succeeded_target.id, finished_at=finished)
    pipeline_run_repository.mark_failed(
        runs[2].id, error="boom", finished_at=base + timedelta(minutes=3)
    )

    recent = pipeline_run_repository.list_recent(limit=10, offset=0)

    assert [run.id for run in recent] == [run.id for run in reversed(runs)]
    statuses = [run.status_value for run in recent]
    assert statuses == ["running", "failed", "succeeded", "running"]

    succeeded_recent = [
        run for run in recent if run.status_value == "succeeded"
    ]
    assert len(succeeded_recent) == 1
    assert succeeded_recent[0].id == succeeded_target.id
    assert succeeded_recent[0].finished_at == finished

    failed_recent = [run for run in recent if run.status_value == "failed"]
    assert len(failed_recent) == 1
    assert failed_recent[0].error_message == "boom"

    assert pipeline_run_repository.count_by_status("running") == 2
    assert pipeline_run_repository.count_by_status("succeeded") == 1
    assert pipeline_run_repository.count_by_status("failed") == 1
    assert pipeline_run_repository.count_by_status("pending") == 0


def test_unknown_status_violates_check_constraint(
    pipeline_run_repository: SqlAlchemyPipelineRunRepository,
    db_session,
) -> None:
    """The CHECK constraint defined on ``PipelineRunRow.status`` rejects unknown values.

    The repository never bypasses the four-value vocabulary itself, so
    we exercise the schema-level guard by running a raw ``UPDATE``
    through the same session. Mirrors the constraint added by
    migration ``0004``.
    """

    from sqlalchemy import text

    started = pipeline_run_repository.start(_new_run())
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "UPDATE app.pipeline_runs SET status = 'mystery' WHERE id = :id"
            ),
            {"id": started.id},
        )