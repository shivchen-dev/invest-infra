"""Tests for the ``/api/v1/candidate-pool/latest`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the storage-layer repository constructors patched to ``MagicMock``
instances so the test can inject deterministic runs, snapshots and
items without a live PostgreSQL connection. PR-01
(``docs/plan/invest-infra-v2-next-stage-web-workbench-plan.md``) adds:

- Run-level metadata on the latest response (``run_id``, ``algorithm_*``,
  ``parameter_set_key``, ``included_count``, ``excluded_count``,
  ``published_at``).
- Server-side Instrument join so each item carries optional
  ``symbol`` / ``name`` / ``exchange`` display fields.
- Diff endpoint semantics tightened to only compare ``included=True``
  items with display fields attached.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from invest_domain.instruments import InstrumentId

from tests.conftest import (
    make_candidate_pool_run,
    make_input_snapshot,
    make_instrument,
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
        candidate_pool_instrument_repo,
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
        first_meta = make_instrument(
            instrument_id=InstrumentId(first_instrument),
            symbol="510300",
            name="HS300 ETF",
            exchange="SSE",
        )
        second_meta = make_instrument(
            instrument_id=InstrumentId(second_instrument),
            symbol="510500",
            name="SSE 500 ETF",
            exchange="SSE",
        )
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = items
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {
            first_instrument: first_meta,
            second_instrument: second_meta,
        }

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["run_id"] == str(run.id)
        assert body["trade_date"] == run.trade_date.isoformat()
        assert body["algorithm_key"] == run.algorithm_key
        assert body["algorithm_version"] == run.algorithm_version
        assert body["parameter_set_key"] == run.parameter_set_key
        assert body["snapshot_id"] == str(snapshot.id)
        assert body["content_hash"] == snapshot.content_hash
        assert body["row_count"] == 2
        assert body["included_count"] == run.included_count
        assert body["excluded_count"] == 0
        assert body["published_at"] is not None
        assert len(body["items"]) == 2
        first = body["items"][0]
        assert first["instrument_id"] == str(first_instrument)
        assert first["included"] is True
        assert first["rank"] == 1
        assert first["symbol"] == "510300"
        assert first["name"] == "HS300 ETF"
        assert first["exchange"] == "SSE"
        assert first["rule_results"][0]["rule_key"] == "liquidity"
        second = body["items"][1]
        assert second["included"] is False
        assert second["symbol"] == "510500"
        assert second["name"] == "SSE 500 ETF"
        assert second["exclusion_reasons"][0]["code"] == "suspended"
        candidate_pool_run_repo.list_by_status.assert_called_once()
        candidate_pool_item_repo.list_by_run_id.assert_called_once()
        input_snapshot_repo.list_by_date.assert_called_once()
        candidate_pool_instrument_repo.get_many_by_ids.assert_called_once()

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
        candidate_pool_instrument_repo,
    ) -> None:
        run = make_candidate_pool_run()
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = []
        candidate_pool_item_repo.list_by_run_id.return_value = []
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 500
        assert "input snapshot" in response.json()["detail"]

    def test_uses_input_row_count_for_row_count(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
        candidate_pool_instrument_repo,
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
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

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
        candidate_pool_instrument_repo,
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
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

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
        candidate_pool_instrument_repo,
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
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

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
        # Missing instruments degrade to ``None`` display fields instead
        # of failing the whole request.
        assert item_payload["symbol"] is None
        assert item_payload["name"] is None
        assert item_payload["exchange"] is None

    def test_reports_included_and_excluded_counts(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        input_snapshot_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        included_first = uuid4()
        included_second = uuid4()
        excluded_one = uuid4()
        excluded_two = uuid4()
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31),
            instrument_ids=[
                included_first,
                included_second,
                excluded_one,
                excluded_two,
            ],
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id,
            input_row_count=4,
            included_count=2,
        )
        items = [
            make_pool_item(instrument_id=included_first, rank=1),
            make_pool_item(instrument_id=included_second, rank=2),
            make_pool_item(
                instrument_id=excluded_one, included=False, rank=None, total_score=None
            ),
            make_pool_item(
                instrument_id=excluded_two, included=False, rank=None, total_score=None
            ),
        ]
        candidate_pool_run_repo.list_by_status.return_value = [run]
        input_snapshot_repo.list_by_date.return_value = [snapshot]
        candidate_pool_item_repo.list_by_run_id.return_value = items
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["included_count"] == 2
        assert body["excluded_count"] == 2


class TestGetCandidatePoolDiff:
    """Coverage for the candidate-pool diff endpoints (PR-01)."""

    def _included_items_for(self, instrument_ids):
        return [
            make_pool_item(instrument_id=iid, rank=idx + 1)
            for idx, iid in enumerate(instrument_ids)
        ]

    def _mixed_items_for(self, included_ids, excluded_ids):
        items = self._included_items_for(included_ids)
        items.extend(
            make_pool_item(
                instrument_id=iid,
                included=False,
                rank=None,
                total_score=None,
            )
            for iid in excluded_ids
        )
        return items

    def _instrument_map(self, instrument_ids):
        return {
            iid: make_instrument(
                instrument_id=InstrumentId(iid),
                symbol=f"S{iid.int % 10000:04d}",
                name=f"ETF {iid.int % 10000:04d}",
                exchange="SSE",
            )
            for iid in instrument_ids
        }

    def test_diff_returns_added_retained_and_removed(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
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
            self._included_items_for(current_ids),
            self._included_items_for(previous_ids),
        ]
        candidate_pool_instrument_repo.get_many_by_ids.return_value = self._instrument_map(
            set(current_ids) | set(previous_ids)
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] == previous.trade_date.isoformat()
        added_entry = body["added"][0]
        retained_entry = body["retained"][0]
        removed_entry = body["removed"][0]
        assert added_entry["instrument_id"] == str(added)
        assert retained_entry["instrument_id"] == str(retained)
        assert removed_entry["instrument_id"] == str(removed)
        for entry in (*body["added"], *body["retained"], *body["removed"]):
            assert entry["symbol"] is not None
            assert entry["name"] is not None
            assert entry["exchange"] == "SSE"
        candidate_pool_run_repo.get_by_id.assert_called_once_with(current.id)
        assert candidate_pool_item_repo.list_by_run_id.call_count == 2
        candidate_pool_item_repo.list_by_run_id.assert_any_call(current.id)
        candidate_pool_item_repo.list_by_run_id.assert_any_call(previous.id)
        candidate_pool_instrument_repo.get_many_by_ids.assert_called_once()

    def test_diff_excludes_excluded_items_from_all_buckets(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        excluded_previous = uuid4()
        excluded_current = uuid4()

        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            self._mixed_items_for([retained], [excluded_current]),
            self._mixed_items_for([retained], [excluded_previous]),
        ]
        candidate_pool_instrument_repo.get_many_by_ids.return_value = self._instrument_map(
            {retained, excluded_previous, excluded_current}
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        all_ids = {
            entry["instrument_id"]
            for entry in (*body["added"], *body["retained"], *body["removed"])
        }
        assert all_ids == {str(retained)}
        assert body["added"] == []
        assert body["removed"] == []

    def test_diff_with_no_previous_run_reports_everything_as_added(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        current_ids = [first, second]

        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current]
        candidate_pool_item_repo.list_by_run_id.return_value = self._included_items_for(
            current_ids
        )
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {
            first: make_instrument(
                instrument_id=InstrumentId(first),
                symbol="510500",
                name="SSE 500 ETF",
                exchange="SSE",
            ),
            second: make_instrument(
                instrument_id=InstrumentId(second),
                symbol="510300",
                name="HS300 ETF",
                exchange="SSE",
            ),
        }

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] is None
        added_symbols = [entry["symbol"] for entry in body["added"]]
        assert added_symbols == sorted(added_symbols)
        assert {entry["instrument_id"] for entry in body["added"]} == {
            str(first),
            str(second),
        }
        assert body["retained"] == []
        assert body["removed"] == []
        candidate_pool_item_repo.list_by_run_id.assert_called_once_with(current.id)
        candidate_pool_instrument_repo.get_many_by_ids.assert_called_once()

    def test_diff_with_current_all_excluded_reports_previous_as_removed(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        removed_first = uuid4()
        removed_second = uuid4()
        excluded_current = uuid4()

        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            [
                make_pool_item(
                    instrument_id=excluded_current,
                    included=False,
                    rank=None,
                    total_score=None,
                )
            ],
            self._included_items_for([removed_first, removed_second]),
        ]
        candidate_pool_instrument_repo.get_many_by_ids.return_value = self._instrument_map(
            {removed_first, removed_second, excluded_current}
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["added"] == []
        assert body["retained"] == []
        removed_ids = {entry["instrument_id"] for entry in body["removed"]}
        assert removed_ids == {str(removed_first), str(removed_second)}
        # Excluded items must never appear in any bucket even if they
        # were in the previous run too.
        all_ids = removed_ids | {
            entry["instrument_id"]
            for entry in (*body["added"], *body["retained"])
        }
        assert str(excluded_current) not in all_ids

    def test_diff_entries_are_ordered_by_symbol_then_instrument_id(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        third = uuid4()
        # Use UUIDs whose integer values are intentionally non-monotonic
        # so the symbol sort is what drives ordering.
        added_ids = [first, second, third]
        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            self._included_items_for(added_ids),
            [],
        ]
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {
            first: make_instrument(
                symbol="159915", name="ChiNext ETF", exchange="SZSE"
            ),
            second: make_instrument(
                symbol="510300", name="HS300 ETF", exchange="SSE"
            ),
            third: make_instrument(
                symbol="510500", name="SSE 500 ETF", exchange="SSE"
            ),
        }

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        added_symbols = [entry["symbol"] for entry in response.json()["added"]]
        assert added_symbols == sorted(added_symbols)

    def test_diff_entries_with_missing_instruments_have_null_display(
        self,
        client,
        candidate_pool_run_repo,
        candidate_pool_item_repo,
        candidate_pool_instrument_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        added = uuid4()
        candidate_pool_run_repo.get_by_id.return_value = current
        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            self._included_items_for([added]),
            [],
        ]
        # Empty map simulates a missing instrument row; the entry must
        # still appear in the bucket with ``None`` display fields.
        candidate_pool_instrument_repo.get_many_by_ids.return_value = {}

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert len(body["added"]) == 1
        entry = body["added"][0]
        assert entry["instrument_id"] == str(added)
        assert entry["symbol"] is None
        assert entry["name"] is None
        assert entry["exchange"] is None

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
        candidate_pool_instrument_repo,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()

        candidate_pool_run_repo.list_by_status.return_value = [current, previous]
        candidate_pool_item_repo.list_by_run_id.side_effect = [
            [make_pool_item(instrument_id=retained, rank=1)],
            [make_pool_item(instrument_id=retained, rank=1)],
        ]
        candidate_pool_instrument_repo.get_many_by_ids.return_value = self._instrument_map(
            {retained}
        )

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["trade_date"] == current.trade_date.isoformat()
        assert body["previous_trade_date"] == previous.trade_date.isoformat()
        assert body["added"] == []
        assert len(body["retained"]) == 1
        assert body["retained"][0]["instrument_id"] == str(retained)
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