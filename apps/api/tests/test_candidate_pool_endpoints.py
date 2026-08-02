"""Tests for the ``/api/v1/candidate-pool/latest`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the storage-layer repository constructors patched to ``MagicMock``
instances so the test can inject deterministic runs, snapshots and
items without a live PostgreSQL connection.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from tests.conftest import (
    make_candidate_pool_run,
    make_input_snapshot,
    make_pool_item,
)

LATEST_ENDPOINT = "/api/v1/candidate-pool/latest"
LATEST_DIFF_ENDPOINT = "/api/v1/candidate-pool/latest/diff"


class TestGetLatestCandidatePool:
    """Coverage for ``GET /api/v1/candidate-pool/latest``."""

    def test_returns_run_with_items_and_content_hash(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
    ) -> None:
        first_instrument = uuid4()
        second_instrument = uuid4()
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31),
            instrument_ids=[first_instrument, second_instrument],
            content_hash="0" * 64,
        )
        run = make_candidate_pool_run(input_snapshot_id=snapshot.id, input_row_count=2)
        items = [
            make_pool_item(instrument_id=first_instrument, rank=1),
            make_pool_item(
                instrument_id=second_instrument,
                included=False,
                rank=None,
                total_score=None,
            ),
        ]
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = items

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["snapshot_date"] == run.trade_date.isoformat()
        assert body["row_count"] == 2
        assert body["content_hash"] == snapshot.content_hash
        assert len(body["items"]) == 2
        first = body["items"][0]
        assert first["instrument_id"] == str(first_instrument)
        assert first["included"] is True
        assert first["rank"] == 1
        assert first["rule_results"][0]["rule_key"] == "liquidity"
        second = body["items"][1]
        assert second["included"] is False
        assert second["exclusion_reasons"][0]["code"] == "suspended"
        candidate_pool_run_repo.list_by_status.assert_called_once()
        candidate_pool_item_repo.list_by_run_id.assert_called_once()
        input_snapshot_repo.list_by_date.assert_called_once()

    def test_returns_404_when_no_published_run_exists(
        self, client, candidate_pool_run_repo
    ) -> None:
        candidate_pool_run_repo.list_by_status.return_value = []

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "no published candidate pool" in response.json()["detail"]

    def test_returns_500_when_snapshot_missing(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
    ) -> None:
        run = make_candidate_pool_run()
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = []
        candidate_pool_item_repo.list_by_run_id.return_value = []

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 500
        assert "input snapshot" in response.json()["detail"]

    def test_uses_input_row_count_for_row_count(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
    ) -> None:
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31),
            instrument_ids=[uuid4() for _ in range(42)],
            content_hash="c" * 64,
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id, input_row_count=42
        )
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = []

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        assert response.json()["row_count"] == 42

    @pytest.mark.parametrize("status_value", ["calculated", "validated", "rejected"])
    def test_non_published_runs_are_ignored(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
        status_value: str,
    ) -> None:
        from datetime import UTC, datetime

        from invest_domain.candidate_pool.models import CandidatePoolStatus

        status_enum = CandidatePoolStatus(status_value)
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31), instrument_ids=[uuid4()]
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id,
            status=status_enum,
            rejection_reason="coverage below threshold",
        )
        candidate_pool_run_repo.list_by_status.return_value = []
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = []

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert run.status is status_enum
        assert isinstance(run.created_at, datetime)
        assert run.created_at.tzinfo is UTC

    def test_items_round_trip_with_full_json_fidelity(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
    ) -> None:
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31),
            instrument_ids=[uuid4()],
            content_hash="d" * 64,
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id, input_row_count=1
        )
        instrument_id = uuid4()
        item = make_pool_item(instrument_id=instrument_id, rank=1)
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = [item]

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        item_payload = body["items"][0]
        assert item_payload["instrument_id"] == str(instrument_id)
        assert item_payload["included"] is True
        assert item_payload["rank"] == 1
        assert item_payload["metrics"] == {"liquidity": "1.5"}
        rule = item_payload["rule_results"][0]
        assert rule["rule_key"] == "liquidity"
        assert rule["severity"] == "info"
        assert rule["value"] == "1.5"
        assert rule["threshold"] == "1.0"


class TestGetCandidatePoolDiff:
    """Coverage for the PR-04 candidate-pool diff endpoints."""

    def _items_for(self, instrument_ids):
        return [
            make_pool_item(instrument_id=iid, rank=idx + 1)
            for idx, iid in enumerate(instrument_ids)
        ]

    def test_diff_returns_added_retained_and_removed(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        removed = uuid4()
        added = uuid4()
        previous_ids = [retained, removed]
        current_ids = [retained, added]

        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            self._items_for(current_ids),
            self._items_for(previous_ids),
        ]

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] == previous.trade_date.isoformat()
        assert body["added"] == [str(added)]
        assert body["retained"] == [str(retained)]
        assert body["removed"] == [str(removed)]
        candidate_pool_run_repo.get_by_id.assert_called_once_with(current.id)
        assert candidate_pool_item_repo.list_by_run_id.call_count == 2
        candidate_pool_item_repo.list_by_run_id.assert_any_call(current.id)
        candidate_pool_item_repo.list_by_run_id.assert_any_call(previous.id)

    def test_diff_with_no_previous_run_reports_everything_as_added(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
    ) -> None:
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        current_ids = [first, second]

        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current]
        candidate_pool_item_repo.list_by_run_id.return_value = self._items_for(
            current_ids
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] is None
        assert body["added"] == sorted(str(iid) for iid in current_ids)
        assert body["retained"] == []
        assert body["removed"] == []
        candidate_pool_item_repo.list_by_run_id.assert_called_once_with(current.id)

    def test_diff_returns_404_for_missing_run(
        self,
        client,
        candidate_pool_run_repo,
    ) -> None:
        candidate_pool_run_repo.get_by_id.return_value = None

        response = client.get(f"/api/v1/candidate-pool/{uuid4()}/diff")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
        candidate_pool_run_repo.list_by_status.assert_not_called()

    @pytest.mark.parametrize("status_value", ["calculated", "validated", "rejected"])
    def test_diff_returns_404_for_non_published_run(
        self,
        client,
        candidate_pool_run_repo,
        status_value: str,
    ) -> None:
        from invest_domain.candidate_pool.models import CandidatePoolStatus

        run = make_candidate_pool_run(
            trade_date=date(2026, 7, 31), status=CandidatePoolStatus(status_value)
        )
        candidate_pool_run_repo.get_by_id.return_value = run

        response = client.get(f"/api/v1/candidate-pool/{run.id}/diff")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
        candidate_pool_run_repo.list_by_status.assert_not_called()

    def test_latest_diff_uses_latest_published_run(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()

        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            [make_pool_item(instrument_id=retained, rank=1)],
            [make_pool_item(instrument_id=retained, rank=1)],
        ]

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] == previous.trade_date.isoformat()
        assert body["added"] == []
        assert body["retained"] == [str(retained)]
        assert body["removed"] == []

    def test_latest_diff_returns_404_when_no_published_run(
        self,
        client,
        candidate_pool_run_repo,
    ) -> None:
        candidate_pool_run_repo.list_by_status.return_value = []

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 404
        assert "no published candidate pool" in response.json()["detail"]