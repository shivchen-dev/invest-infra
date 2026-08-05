"""Tests for :class:`invest_api.application.pipeline_runs.PipelineRunQueryService`.

The endpoint tests in :mod:`tests.test_pipeline_run_endpoints` mock
the application service at the FastAPI boundary and verify the HTTP
contract. These tests bypass the HTTP layer: they construct the real
service against a mock repository so they can assert that the
service itself owns the fixed :data:`JOB_KEY` scope, the latest-row
selection scan, the by-id job-key scoping, and the
:class:`sqlalchemy.exc.SQLAlchemyError` translation to
:class:`PipelineRunQueryError`.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.pipeline_runs import (
    JOB_KEY,
    LATEST_LOOKBACK_LIMIT,
    PipelineRunQueryError,
    PipelineRunQueryService,
)

from tests.conftest import make_pipeline_run


def _build_service() -> tuple[PipelineRunQueryService, MagicMock]:
    """Return a real service wired to a mock repository."""

    repository = MagicMock(name="PipelineRunReader")
    return PipelineRunQueryService(repository), repository


class TestListRuns:
    """Coverage for :meth:`PipelineRunQueryService.list_runs`."""

    def test_scopes_pagination_to_fixed_job_key(
        self,
    ) -> None:
        service, repository = _build_service()
        personal_runs = [make_pipeline_run()]
        repository.list_by_job_key.return_value = personal_runs
        repository.count_by_job_key.return_value = 1

        page, total = service.list_runs(limit=20, offset=0)

        assert page is personal_runs
        assert total == 1
        repository.list_by_job_key.assert_called_once_with(
            JOB_KEY, limit=20, offset=0
        )
        repository.count_by_job_key.assert_called_once_with(JOB_KEY)

    @pytest.mark.parametrize(
        "limit,offset",
        [(1, 0), (50, 25), (100, 9999)],
    )
    def test_forwards_pagination_arguments_unchanged(
        self,
        limit: int,
        offset: int,
    ) -> None:
        service, repository = _build_service()
        repository.list_by_job_key.return_value = []
        repository.count_by_job_key.return_value = 0

        service.list_runs(limit=limit, offset=offset)

        repository.list_by_job_key.assert_called_once_with(
            JOB_KEY, limit=limit, offset=offset
        )

    def test_returns_total_from_repository_count(
        self,
    ) -> None:
        service, repository = _build_service()
        repository.list_by_job_key.return_value = []
        repository.count_by_job_key.return_value = 17

        _, total = service.list_runs(limit=20, offset=0)

        assert total == 17

    def test_translates_sqlalchemy_error_on_list(
        self,
    ) -> None:
        from sqlalchemy.exc import OperationalError

        service, repository = _build_service()
        repository.list_by_job_key.side_effect = OperationalError(
            "SELECT pipeline runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(PipelineRunQueryError):
            service.list_runs(limit=20, offset=0)
        repository.count_by_job_key.assert_not_called()

    def test_translates_sqlalchemy_error_on_count(
        self,
    ) -> None:
        from sqlalchemy.exc import OperationalError

        service, repository = _build_service()
        repository.list_by_job_key.return_value = []
        repository.count_by_job_key.side_effect = OperationalError(
            "SELECT count(pipeline runs)",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(PipelineRunQueryError):
            service.list_runs(limit=20, offset=0)


class TestGetLatestRun:
    """Coverage for :meth:`PipelineRunQueryService.get_latest_run`."""

    def test_returns_first_run_matching_fixed_job_key(
        self,
    ) -> None:
        service, repository = _build_service()
        personal_run = make_pipeline_run()
        unrelated_run = make_pipeline_run(job_key="unrelated_job")
        repository.list_recent.return_value = [personal_run, unrelated_run]

        result = service.get_latest_run()

        assert result is personal_run
        repository.list_recent.assert_called_once_with(
            limit=LATEST_LOOKBACK_LIMIT, offset=0
        )

    def test_skips_unrelated_runs_above_the_personal_run(
        self,
    ) -> None:
        service, repository = _build_service()
        unrelated_top = make_pipeline_run(job_key="other_job")
        unrelated_middle = make_pipeline_run(job_key="yet_another")
        personal_run = make_pipeline_run()
        repository.list_recent.return_value = [
            unrelated_top,
            unrelated_middle,
            personal_run,
        ]

        result = service.get_latest_run()

        assert result is personal_run

    def test_returns_none_when_no_matching_job_key(
        self,
    ) -> None:
        service, repository = _build_service()
        repository.list_recent.return_value = [
            make_pipeline_run(job_key="other_job"),
            make_pipeline_run(job_key="yet_another"),
        ]

        assert service.get_latest_run() is None

    def test_returns_none_when_recent_list_is_empty(
        self,
    ) -> None:
        service, repository = _build_service()
        repository.list_recent.return_value = []

        assert service.get_latest_run() is None

    def test_uses_fixed_lookback_limit(
        self,
    ) -> None:
        service, repository = _build_service()
        repository.list_recent.return_value = []

        service.get_latest_run()

        repository.list_recent.assert_called_once_with(
            limit=LATEST_LOOKBACK_LIMIT, offset=0
        )

    def test_translates_sqlalchemy_error(
        self,
    ) -> None:
        from sqlalchemy.exc import OperationalError

        service, repository = _build_service()
        repository.list_recent.side_effect = OperationalError(
            "SELECT recent runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(PipelineRunQueryError):
            service.get_latest_run()


class TestGetRunForJob:
    """Coverage for :meth:`PipelineRunQueryService.get_run_for_job`."""

    def test_returns_run_when_job_key_matches(
        self,
    ) -> None:
        service, repository = _build_service()
        run = make_pipeline_run()
        run_id = uuid4()
        repository.get_by_id.return_value = run

        result = service.get_run_for_job(run_id)

        assert result is run
        repository.get_by_id.assert_called_once_with(run_id)

    def test_returns_none_when_run_missing(
        self,
    ) -> None:
        service, repository = _build_service()
        run_id = uuid4()
        repository.get_by_id.return_value = None

        assert service.get_run_for_job(run_id) is None

    def test_returns_none_when_run_belongs_to_other_job(
        self,
    ) -> None:
        service, repository = _build_service()
        run_id = uuid4()
        other_run = make_pipeline_run(job_key="other_job")
        repository.get_by_id.return_value = other_run

        assert service.get_run_for_job(run_id) is None

    def test_translates_sqlalchemy_error(
        self,
    ) -> None:
        from sqlalchemy.exc import OperationalError

        service, repository = _build_service()
        run_id = uuid4()
        repository.get_by_id.side_effect = OperationalError(
            "SELECT pipeline run by id",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )

        with pytest.raises(PipelineRunQueryError):
            service.get_run_for_job(run_id)


class TestPipelineRunQueryError:
    """Coverage for the application exception type."""

    def test_is_runtime_error_subclass(self) -> None:
        assert issubclass(PipelineRunQueryError, RuntimeError)

    def test_carries_chained_sqlalchemy_error(self) -> None:
        from sqlalchemy.exc import OperationalError

        service, repository = _build_service()
        original = OperationalError(
            "SELECT pipeline runs",
            {},
            Exception("connection string: postgres://user:secret@host/db"),
        )
        repository.list_by_job_key.side_effect = original

        with pytest.raises(PipelineRunQueryError) as exc_info:
            service.list_runs(limit=20, offset=0)

        assert exc_info.value.__cause__ is original


__all__ = [
    "TestGetLatestRun",
    "TestGetRunForJob",
    "TestListRuns",
    "TestPipelineRunQueryError",
]