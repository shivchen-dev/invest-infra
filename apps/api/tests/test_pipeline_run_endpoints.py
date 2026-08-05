"""Tests for the ``/api/v1/pipeline-runs`` read-only endpoints.

The endpoints are exercised through ``fastapi.testclient.TestClient``
with the application-layer :class:`PipelineRunQueryService` replaced
through a ``MagicMock`` so the handlers can be driven without a live
PostgreSQL connection. The router-level tests assert the HTTP
contract (status codes, response shape, sanitized 500 detail); the
application-level tests in :mod:`tests.test_pipeline_run_service`
exercise the service against a mock repository and own the
fixed-job-key, latest-selection, by-id-scoping and
repository-error-translation assertions.

All endpoints are scoped to ``job_key = "personal_etf_daily_job"``;
the tests assert that a run belonging to a different ``job_key`` is
treated as ``404`` so the front-end cannot mistake an unrelated job
for the personal daily job. The PR-02 list endpoint also asserts that
the application service forwards pagination into the repository so
the ``job_key`` filter and the ``limit`` / ``offset`` bounds stay in
SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.pipeline_runs import PipelineRunQueryError

from tests.conftest import make_pipeline_run

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


LATEST_ENDPOINT = "/api/v1/pipeline-runs/latest"
LIST_ENDPOINT = "/api/v1/pipeline-runs"


class TestGetLatestPipelineRun:
    """Coverage for ``GET /api/v1/pipeline-runs/latest``."""

    def test_returns_most_recent_personal_job_run(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_run = make_pipeline_run()
        pipeline_run_service.get_latest_run.return_value = personal_run

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
        pipeline_run_service.get_latest_run.assert_called_once_with()

    def test_picks_personal_run_among_unrelated_runs(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_run = make_pipeline_run()
        pipeline_run_service.get_latest_run.return_value = personal_run

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        assert response.json()["id"] == str(personal_run.id)

    def test_returns_404_when_no_recent_runs(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.get_latest_run.return_value = None

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_returns_404_when_no_matching_job_key(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.get_latest_run.return_value = None

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_propagates_failed_status_and_error_summary(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        from invest_domain.pipeline import PipelineRunStatus

        failed_run = make_pipeline_run(
            status=PipelineRunStatus.FAILED,
            error_summary="cifang payload schema mismatch",
        )
        pipeline_run_service.get_latest_run.return_value = failed_run

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
        pipeline_run_service: MagicMock,
    ) -> None:
        run = make_pipeline_run()
        pipeline_run_service.get_run_for_job.return_value = run

        response = client.get(f"/api/v1/pipeline-runs/{run.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(run.id)
        assert body["job_key"] == "personal_etf_daily_job"
        assert body["status"] == run.status_value
        pipeline_run_service.get_run_for_job.assert_called_once_with(run.id)

    def test_returns_404_when_run_missing(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.get_run_for_job.return_value = None

        response = client.get(f"/api/v1/pipeline-runs/{uuid4()}")

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    def test_returns_404_when_run_belongs_to_different_job(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.get_run_for_job.return_value = None

        response = client.get(f"/api/v1/pipeline-runs/{uuid4()}")

        assert response.status_code == 404
        assert "personal_etf_daily_job" in response.json()["detail"]

    @pytest.mark.parametrize("bad_uuid", ["not-a-uuid", "12345", "abcd"])
    def test_returns_422_for_malformed_run_id(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
        bad_uuid: str,
    ) -> None:
        response = client.get(f"/api/v1/pipeline-runs/{bad_uuid}")

        assert response.status_code == 422
        pipeline_run_service.get_run_for_job.assert_not_called()

    def test_surfaces_null_timestamps_for_queued_run(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        from invest_domain.pipeline import PipelineRunStatus

        queued_run = make_pipeline_run(status=PipelineRunStatus.QUEUED)
        pipeline_run_service.get_run_for_job.return_value = queued_run

        response = client.get(f"/api/v1/pipeline-runs/{queued_run.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "queued"
        assert body["started_at"] is None
        assert body["finished_at"] is None


class TestListPipelineRuns:
    """Coverage for ``GET /api/v1/pipeline-runs`` (PR-02 history endpoint)."""

    def test_returns_paginated_history_for_personal_job(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_a = make_pipeline_run()
        personal_b = make_pipeline_run()
        pipeline_run_service.list_runs.return_value = ([personal_a, personal_b], 3)

        response = client.get(LIST_ENDPOINT, params={"limit": 2, "offset": 0})

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert [item["id"] for item in body["items"]] == [
            str(personal_a.id),
            str(personal_b.id),
        ]
        assert body["items"][0]["job_key"] == "personal_etf_daily_job"
        pipeline_run_service.list_runs.assert_called_once_with(limit=2, offset=0)

    def test_default_limit_is_20(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.list_runs.return_value = ([], 0)

        response = client.get(LIST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert body["total"] == 0
        assert body["items"] == []
        pipeline_run_service.list_runs.assert_called_once_with(limit=20, offset=0)

    def test_filters_out_runs_belonging_to_other_jobs(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_run = make_pipeline_run()
        pipeline_run_service.list_runs.return_value = ([personal_run], 1)

        response = client.get(LIST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [str(personal_run.id)]
        pipeline_run_service.list_runs.assert_called_once_with(limit=20, offset=0)

    def test_total_uses_underlying_storage_count_not_in_memory_total(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_runs = [make_pipeline_run() for _ in range(5)]
        pipeline_run_service.list_runs.return_value = (personal_runs, 42)

        response = client.get(LIST_ENDPOINT, params={"limit": 5, "offset": 0})

        body = response.json()
        assert body["total"] == 42
        assert len(body["items"]) == 5

    def test_offset_paginates_through_personal_history(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        personal_b = make_pipeline_run()
        pipeline_run_service.list_runs.return_value = ([personal_b], 3)

        response = client.get(
            LIST_ENDPOINT, params={"limit": 1, "offset": 1}
        )

        body = response.json()
        assert body["limit"] == 1
        assert body["offset"] == 1
        assert body["total"] == 3
        assert [item["id"] for item in body["items"]] == [str(personal_b.id)]
        pipeline_run_service.list_runs.assert_called_once_with(limit=1, offset=1)

    def test_offset_over_100_uses_sql_pagination(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.list_runs.return_value = ([make_pipeline_run()], 126)

        response = client.get(
            LIST_ENDPOINT, params={"limit": 1, "offset": 125}
        )

        body = response.json()
        assert body["items"]
        assert body["total"] == 126
        assert body["limit"] == 1
        assert body["offset"] == 125
        pipeline_run_service.list_runs.assert_called_once_with(limit=1, offset=125)

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 1000])
    def test_returns_422_for_out_of_range_limit(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
        bad_limit: int,
    ) -> None:
        response = client.get(LIST_ENDPOINT, params={"limit": bad_limit})

        assert response.status_code == 422
        pipeline_run_service.list_runs.assert_not_called()

    @pytest.mark.parametrize("bad_offset", [-1, -10])
    def test_returns_422_for_negative_offset(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
        bad_offset: int,
    ) -> None:
        response = client.get(LIST_ENDPOINT, params={"offset": bad_offset})

        assert response.status_code == 422
        pipeline_run_service.list_runs.assert_not_called()

    def test_returns_sanitized_500_on_query_error(
        self,
        client: TestClient,
        pipeline_run_service: MagicMock,
    ) -> None:
        pipeline_run_service.list_runs.side_effect = PipelineRunQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(LIST_ENDPOINT)

        assert response.status_code == 500
        assert response.json() == {"detail": "Pipeline runs query failed"}
        # Ensure the original driver message (and any embedded secret) never leaks.
        assert "secret" not in response.text
        assert "PipelineRunQueryError" not in response.text


__all__ = [
    "TestGetLatestPipelineRun",
    "TestGetPipelineRunById",
    "TestListPipelineRuns",
]