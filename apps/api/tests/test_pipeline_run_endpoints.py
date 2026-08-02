"""Tests for the ``/api/v1/pipeline-runs`` read-only endpoints.

The endpoints are exercised through ``fastapi.testclient.TestClient``
with the storage-layer ``SqlAlchemyPipelineRunRepository`` patched to a
``MagicMock`` instance so the handlers can be driven without a live
PostgreSQL connection. Both endpoints are scoped to
``job_key = "personal_etf_daily_job"``; the tests assert that a run
belonging to a different ``job_key`` is treated as ``404`` so the
front-end cannot mistake an unrelated job for the personal daily job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from tests.conftest import make_pipeline_run

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


LATEST_ENDPOINT = "/api/v1/pipeline-runs/latest"


class TestGetLatestPipelineRun:
    """Coverage for ``GET /api/v1/pipeline-runs/latest``."""

    def test_returns_most_recent_personal_job_run(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        personal_run = make_pipeline_run()
        unrelated_run = make_pipeline_run(
            job_key="unrelated_job",
            started_at=personal_run.started_at,
        )
        pipeline_run_repo.list_recent.return_value = [personal_run, unrelated_run]

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(personal_run.id)
        assert body["job_key"] == "personal_etf_daily_job"
        assert body["partition_key"] == personal_run.partition_key
        assert body["trigger_type"] == personal_run.trigger_type
        assert body["status"] == personal_run.status_value
        assert body["started_at"].startswith("2026-07-31T09:00:00")
        assert body["finished_at"].startswith("2026-07-31T10:00:00")
        assert body["error_code"] is None
        assert body["error_summary"] is None
        pipeline_run_repo.list_recent.assert_called_once()

    def test_picks_personal_run_among_unrelated_runs(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        newer_unrelated = make_pipeline_run(
            job_key="other_job",
            started_at=make_pipeline_run().started_at,
        )
        personal_run = make_pipeline_run()
        pipeline_run_repo.list_recent.return_value = [newer_unrelated, personal_run]

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        assert response.json()["id"] == str(personal_run.id)

    def test_returns_404_when_no_recent_runs(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        pipeline_run_repo.list_recent.return_value = []

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_returns_404_when_no_matching_job_key(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        pipeline_run_repo.list_recent.return_value = [
            make_pipeline_run(job_key="other_job"),
            make_pipeline_run(job_key="yet_another"),
        ]

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_propagates_failed_status_and_error_summary(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        from invest_domain.pipeline import PipelineRunStatus

        failed_run = make_pipeline_run(
            status=PipelineRunStatus.FAILED,
            error_summary="cifang payload schema mismatch",
        )
        pipeline_run_repo.list_recent.return_value = [failed_run]

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error_summary"] == "cifang payload schema mismatch"
        assert body["error_code"] is None


class TestGetPipelineRunById:
    """Coverage for ``GET /api/v1/pipeline-runs/{run_id}``."""

    def test_returns_run_for_matching_job_key(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        run = make_pipeline_run()
        pipeline_run_repo.get_by_id.return_value = run

        response = client.get(f"/api/v1/pipeline-runs/{run.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(run.id)
        assert body["job_key"] == "personal_etf_daily_job"
        assert body["status"] == run.status_value
        pipeline_run_repo.get_by_id.assert_called_once_with(run.id)

    def test_returns_404_when_run_missing(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        pipeline_run_repo.get_by_id.return_value = None

        response = client.get(f"/api/v1/pipeline-runs/{uuid4()}")

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_returns_404_when_run_belongs_to_different_job(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        other_run = make_pipeline_run(job_key="other_job")
        pipeline_run_repo.get_by_id.return_value = other_run

        response = client.get(f"/api/v1/pipeline-runs/{other_run.id}")

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    @pytest.mark.parametrize("bad_uuid", ["not-a-uuid", "12345", "abcd"])
    def test_returns_422_for_malformed_run_id(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
        bad_uuid: str,
    ) -> None:
        response = client.get(f"/api/v1/pipeline-runs/{bad_uuid}")

        assert response.status_code == 422
        pipeline_run_repo.get_by_id.assert_not_called()

    def test_surfaces_null_timestamps_for_queued_run(
        self,
        client: TestClient,
        pipeline_run_repo: MagicMock,
    ) -> None:
        from invest_domain.pipeline import PipelineRunStatus

        queued_run = make_pipeline_run(status=PipelineRunStatus.QUEUED)
        pipeline_run_repo.get_by_id.return_value = queued_run

        response = client.get(f"/api/v1/pipeline-runs/{queued_run.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["started_at"] is None
        assert body["finished_at"] is None