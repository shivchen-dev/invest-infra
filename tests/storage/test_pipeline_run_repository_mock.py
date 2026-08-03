"""Mock-based unit tests for :class:`SqlAlchemyPipelineRunRepository`.

The tests drive a :class:`unittest.mock.MagicMock` ``Session`` so the
:class:`invest_storage.repositories.SqlAlchemyPipelineRunRepository`
can be verified without spinning up Testcontainers or speaking to a real
PostgreSQL. The repository never opens its own session, never commits,
and always returns the domain-side :class:`invest_domain.pipeline.PipelineRun`;
these tests pin all three contracts.

Each test exercises exactly one behaviour so a future regression in
either the SQLAlchemy call shape (``add`` / ``flush`` / ``get`` /
``scalars``) or the ORM-to-domain mapping can be localised.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.pipeline import PipelineRun, PipelineRunStatus
from invest_storage.models import PipelineRunRow
from invest_storage.repositories import SqlAlchemyPipelineRunRepository


def _make_run(
    *,
    job_key: str = "etf_daily",
    trigger_type: str = "manual",
    algorithm_version: str | None = "v1.0",
    status: PipelineRunStatus | str = PipelineRunStatus.RUNNING,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_summary: str | None = None,
) -> PipelineRun:
    return PipelineRun(
        job_key=job_key,
        trigger_type=trigger_type,
        status=status,
        algorithm_version=algorithm_version,
        started_at=started_at or datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
        finished_at=finished_at,
        error_summary=error_summary,
    )


def _make_row(
    *,
    row_id: UUID | None = None,
    job_key: str = "etf_daily",
    partition_key: str | None = None,
    trigger_type: str = "manual",
    status: str = "running",
    algorithm_version: str | None = "v1.0",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_summary: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    dagster_run_id: str | None = None,
    config_snapshot: dict | None = None,
) -> MagicMock:
    """Build a mock that looks like a :class:`PipelineRunRow`."""

    base = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    row = MagicMock(spec=PipelineRunRow)
    row.id = row_id or uuid4()
    row.job_key = job_key
    row.partition_key = partition_key
    row.trigger_type = trigger_type
    row.status = status
    row.algorithm_version = algorithm_version
    row.started_at = started_at or base
    row.finished_at = finished_at
    row.error_summary = error_summary
    row.created_at = created_at or base
    row.updated_at = updated_at or base
    row.dagster_run_id = dagster_run_id
    row.config_snapshot = config_snapshot or {}
    return row


class SqlAlchemyPipelineRunRepositoryMockTests(unittest.TestCase):
    """Mock-based tests for :class:`SqlAlchemyPipelineRunRepository`."""

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyPipelineRunRepository(self._session)

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------

    def test_start_inserts_row_with_status_running(self) -> None:
        run = _make_run()

        self._repo.start(run)

        self.assertEqual(self._session.add.call_count, 1)
        self.assertEqual(self._session.flush.call_count, 1)
        added_row = self._session.add.call_args[0][0]
        self.assertIsInstance(added_row, PipelineRunRow)
        self.assertEqual(added_row.status, "running")
        self.assertEqual(added_row.job_key, "etf_daily")
        self.assertEqual(added_row.algorithm_version, "v1.0")
        self.assertEqual(added_row.started_at, run.started_at)
        self.assertIsNone(added_row.error_summary)
        self.assertIsNone(added_row.finished_at)

    def test_start_returns_pipeline_run_with_persisted_id(self) -> None:
        run = _make_run()
        persisted_id = uuid4()

        def _attach_row(_row: Any) -> None:
            _row.id = persisted_id

        self._session.add.side_effect = _attach_row

        result = self._repo.start(run)

        self.assertIsInstance(result, PipelineRun)
        self.assertEqual(result.id, persisted_id)
        self.assertEqual(result.status_value, "running")
        self.assertEqual(result.job_key, run.job_key)
        self.assertEqual(result.algorithm_version, run.algorithm_version)
        self.assertEqual(result.started_at, run.started_at)
        self.assertIsNone(result.finished_at)
        self.assertIsNone(result.error_summary)

    # ------------------------------------------------------------------
    # mark_succeeded
    # ------------------------------------------------------------------

    def test_mark_succeeded_updates_status_and_finished_at(self) -> None:
        run_id = uuid4()
        existing = _make_row(row_id=run_id, status="running")
        self._session.get.return_value = existing
        finished_at = datetime(2026, 7, 30, 12, 5, tzinfo=UTC)

        result = self._repo.mark_succeeded(run_id, finished_at=finished_at)

        self._session.get.assert_called_once_with(PipelineRunRow, run_id)
        self.assertEqual(existing.status, "succeeded")
        self.assertEqual(existing.finished_at, finished_at)
        self.assertIsNone(existing.error_summary)
        self.assertEqual(self._session.flush.call_count, 1)
        self.assertIsInstance(result, PipelineRun)
        self.assertEqual(result.id, run_id)
        self.assertEqual(result.status_value, "succeeded")
        self.assertEqual(result.finished_at, finished_at)
        self.assertIsNone(result.error_summary)

    # ------------------------------------------------------------------
    # mark_failed
    # ------------------------------------------------------------------

    def test_mark_failed_sets_error_and_status(self) -> None:
        run_id = uuid4()
        existing = _make_row(row_id=run_id, status="running")
        self._session.get.return_value = existing
        finished_at = datetime(2026, 7, 30, 12, 5, tzinfo=UTC)

        result = self._repo.mark_failed(
            run_id, error="provider timeout", finished_at=finished_at
        )

        self._session.get.assert_called_once_with(PipelineRunRow, run_id)
        self.assertEqual(existing.status, "failed")
        self.assertEqual(existing.finished_at, finished_at)
        self.assertEqual(existing.error_summary, "provider timeout")
        self.assertEqual(self._session.flush.call_count, 1)
        self.assertIsInstance(result, PipelineRun)
        self.assertEqual(result.status_value, "failed")
        self.assertEqual(result.error_summary, "provider timeout")
        self.assertEqual(result.finished_at, finished_at)

    # ------------------------------------------------------------------
    # get_by_id
    # ------------------------------------------------------------------

    def test_get_by_id_returns_run_when_present(self) -> None:
        run_id = uuid4()
        row = _make_row(
            row_id=run_id,
            status="succeeded",
            finished_at=datetime(2026, 7, 30, 12, 5, tzinfo=UTC),
        )
        self._session.get.return_value = row

        result = self._repo.get_by_id(run_id)

        self._session.get.assert_called_once_with(PipelineRunRow, run_id)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsInstance(result, PipelineRun)
        self.assertEqual(result.id, run_id)
        self.assertEqual(result.status_value, "succeeded")
        self.assertEqual(result.finished_at, row.finished_at)

    def test_get_by_id_returns_none_when_absent(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        result = self._repo.get_by_id(missing)

        self._session.get.assert_called_once_with(PipelineRunRow, missing)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # list_recent
    # ------------------------------------------------------------------

    def test_list_recent_returns_runs_ordered_by_started_at_desc(self) -> None:
        first = _make_row(started_at=datetime(2026, 7, 30, 14, 0, tzinfo=UTC))
        second = _make_row(started_at=datetime(2026, 7, 30, 13, 0, tzinfo=UTC))
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [first, second]

        result = self._repo.list_recent(limit=10, offset=0)

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(len(result), 2)
        self.assertEqual([item.id for item in result], [first.id, second.id])
        self.assertEqual(
            [item.started_at for item in result],
            [first.started_at, second.started_at],
        )
        for item in result:
            self.assertIsInstance(item, PipelineRun)

    def test_list_by_job_key_applies_filter_and_pagination(self) -> None:
        first = _make_row(job_key="personal_etf_daily_job")
        second = _make_row(job_key="personal_etf_daily_job")
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [first, second]

        result = self._repo.list_by_job_key(
            "personal_etf_daily_job", limit=1, offset=125
        )

        statement = self._session.scalars.call_args.args[0]
        compiled = statement.compile()
        self.assertIn("personal_etf_daily_job", compiled.params.values())
        self.assertEqual(statement._limit_clause.value, 1)
        self.assertEqual(statement._offset_clause.value, 125)
        self.assertEqual([item.id for item in result], [first.id, second.id])
        for item in result:
            self.assertIsInstance(item, PipelineRun)

    def test_count_by_job_key_filters_correctly(self) -> None:
        self._session.scalar.return_value = 42

        result = self._repo.count_by_job_key("personal_etf_daily_job")

        statement = self._session.scalar.call_args.args[0]
        compiled = statement.compile()
        self.assertIn("personal_etf_daily_job", compiled.params.values())
        self.assertEqual(result, 42)

    # ------------------------------------------------------------------
    # count_by_status
    # ------------------------------------------------------------------

    def test_count_by_status_filters_correctly(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [uuid4(), uuid4()]

        result = self._repo.count_by_status("running")

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(result, 2)

    # ------------------------------------------------------------------
    # get_blocking_by_job_and_partition (idempotency lookup)
    # ------------------------------------------------------------------

    def test_get_blocking_by_job_and_partition_returns_row(self) -> None:
        latest = _make_row(
            row_id=uuid4(),
            job_key="personal_etf_daily_job",
            partition_key="2026-07-30",
            status="succeeded",
            started_at=datetime(2026, 7, 30, 13, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 30, 13, 5, tzinfo=UTC),
        )
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = latest

        result = self._repo.get_blocking_by_job_and_partition(
            job_key="personal_etf_daily_job",
            partition_key="2026-07-30",
        )

        lock_statement = self._session.execute.call_args.args[0]
        self.assertIn("pg_advisory_xact_lock", str(lock_statement))
        self._session.execute.assert_called_once()
        statement = self._session.scalars.call_args.args[0]
        compiled = statement.compile()
        params = dict(compiled.params)
        self.assertIn("personal_etf_daily_job", params.values())
        self.assertIn("2026-07-30", params.values())
        self.assertIn(
            ["queued", "running", "succeeded"],
            params.values(),
        )
        scalars_mock.first.assert_called_once_with()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, latest.id)
        self.assertEqual(result.status_value, "succeeded")
        self.assertEqual(result.job_key, "personal_etf_daily_job")
        self.assertEqual(result.partition_key, "2026-07-30")

    def test_get_blocking_by_job_and_partition_returns_none_when_absent(
        self,
    ) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        result = self._repo.get_blocking_by_job_and_partition(
            job_key="personal_etf_daily_job",
            partition_key="2026-07-30",
        )

        scalars_mock.first.assert_called_once_with()
        self.assertIsNone(result)

    def test_get_blocking_by_job_and_partition_rejects_empty_job_key(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.get_blocking_by_job_and_partition(
                job_key="",
                partition_key="2026-07-30",
            )

    # ------------------------------------------------------------------
    # mark_succeeded idempotency
    # ------------------------------------------------------------------

    def test_mark_succeeded_is_noop_when_already_succeeded(self) -> None:
        """Calling mark_succeeded on a succeeded row is a no-op."""
        run_id = uuid4()
        original_finished = datetime(2026, 7, 30, 12, 5, tzinfo=UTC)
        existing = _make_row(
            row_id=run_id,
            status="succeeded",
            finished_at=original_finished,
        )
        self._session.get.return_value = existing

        new_finished = datetime(2026, 7, 30, 13, 0, tzinfo=UTC)
        result = self._repo.mark_succeeded(run_id, finished_at=new_finished)

        # Status stays succeeded; finished_at is NOT overwritten.
        self.assertEqual(existing.status, "succeeded")
        self.assertEqual(existing.finished_at, original_finished)
        # No flush is performed for the no-op path.
        self.assertEqual(self._session.flush.call_count, 0)
        self.assertIsInstance(result, PipelineRun)
        self.assertEqual(result.id, run_id)
        self.assertEqual(result.finished_at, original_finished)

    # ------------------------------------------------------------------
    # mark_failed sticky-success guard
    # ------------------------------------------------------------------

    def test_mark_failed_refuses_to_downgrade_succeeded(self) -> None:
        """A succeeded row must not be downgraded to failed."""
        run_id = uuid4()
        existing = _make_row(
            row_id=run_id,
            status="succeeded",
            finished_at=datetime(2026, 7, 30, 12, 5, tzinfo=UTC),
        )
        self._session.get.return_value = existing

        with self.assertRaises(ValueError) as ctx:
            self._repo.mark_failed(
                run_id,
                error="late failure",
                finished_at=datetime(2026, 7, 30, 13, 0, tzinfo=UTC),
            )

        self.assertIn("already in 'succeeded'", str(ctx.exception))
        # The row must be untouched.
        self.assertEqual(existing.status, "succeeded")
        self.assertEqual(self._session.flush.call_count, 0)

    def test_mark_failed_can_overwrite_failed_state(self) -> None:
        """A failed row may be re-marked as failed (failed is retryable)."""
        run_id = uuid4()
        existing = _make_row(
            row_id=run_id,
            status="failed",
            error_summary="transient",
            finished_at=datetime(2026, 7, 30, 12, 5, tzinfo=UTC),
        )
        self._session.get.return_value = existing

        result = self._repo.mark_failed(
            run_id,
            error="second failure",
            finished_at=datetime(2026, 7, 30, 13, 0, tzinfo=UTC),
        )

        self.assertEqual(existing.status, "failed")
        self.assertEqual(existing.error_summary, "second failure")
        self.assertEqual(self._session.flush.call_count, 1)
        self.assertEqual(result.error_summary, "second failure")


if __name__ == "__main__":
    unittest.main()