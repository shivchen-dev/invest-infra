"""Tests for the ``/api/v1/candidate-pool`` read-only endpoints.

The endpoints are exercised through ``fastapi.testclient.TestClient``
with the application-layer :class:`CandidatePoolQueryService` replaced
through a ``MagicMock`` so the handlers can be driven without a live
PostgreSQL connection. The router-level tests assert the HTTP
contract (status codes, response shape, sanitized 500 detail, included
display fields, sort order); the application-level tests in
:mod:`tests.test_candidate_pool_service` exercise the service against
mock repositories and own the ``PUBLISHED`` filter, the input-snapshot
lookup, the predecessor selection, the included-only set diff and the
repository-error-translation assertions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.candidate_pool import (
    CandidatePoolDiffEntryView,
    CandidatePoolDiffView,
    CandidatePoolQueryError,
    CandidatePoolSnapshotMissingError,
    LatestCandidatePoolView,
)
from invest_domain.candidate_pool.models import CandidatePoolStatus
from invest_domain.instruments.models import InstrumentId

from tests.conftest import (
    make_candidate_pool_run,
    make_input_snapshot,
    make_instrument,
    make_pool_item,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


LATEST_ENDPOINT = "/api/v1/candidate-pool/latest"
LATEST_DIFF_ENDPOINT = "/api/v1/candidate-pool/latest/diff"


def _build_latest_view(
    *,
    run=None,
    snapshot=None,
    items=(),
    instrument_map=None,
):
    """Return a :class:`LatestCandidatePoolView` for the latest endpoint."""

    if run is None:
        run = make_candidate_pool_run()
    if snapshot is None:
        snapshot = make_input_snapshot(
            snapshot_date=run.trade_date,
            instrument_ids=[item.instrument_id.value for item in items]
            or [uuid4()],
        )
    if instrument_map is None:
        instrument_map = {}
    return LatestCandidatePoolView(
        run=run,
        snapshot=snapshot,
        items=tuple(items),
        instruments_by_id=instrument_map,
    )


def _build_diff_view(
    *,
    trade_date: date,
    previous_trade_date: date | None,
    added=(),
    retained=(),
    removed=(),
) -> CandidatePoolDiffView:
    """Return a :class:`CandidatePoolDiffView` for the diff endpoints."""

    return CandidatePoolDiffView(
        trade_date=trade_date,
        previous_trade_date=previous_trade_date,
        added=tuple(added),
        retained=tuple(retained),
        removed=tuple(removed),
    )


def _entry_for(
    instrument_id,
    *,
    symbol: str | None = "510300",
    name: str | None = "HS300 ETF",
    exchange: str | None = "SSE",
) -> CandidatePoolDiffEntryView:
    return CandidatePoolDiffEntryView(
        instrument_id=instrument_id,
        symbol=symbol,
        name=name,
        exchange=exchange,
    )


class TestGetLatestCandidatePool:
    """Coverage for ``GET /api/v1/candidate-pool/latest``."""

    def test_returns_run_with_items_and_content_hash(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
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
        view = _build_latest_view(
            run=run,
            snapshot=snapshot,
            items=items,
            instrument_map={
                first_instrument: first_meta,
                second_instrument: second_meta,
            },
        )
        candidate_pool_service.get_latest.return_value = view

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
        candidate_pool_service.get_latest.assert_called_once_with()

    def test_returns_404_when_no_published_run_exists(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_latest.return_value = None

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404
        assert "no published candidate pool" in response.json()["detail"]

    def test_returns_500_when_snapshot_missing(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        run_id = uuid4()
        candidate_pool_service.get_latest.side_effect = (
            CandidatePoolSnapshotMissingError(snapshot_id=snapshot_id, run_id=run_id)
        )

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 500
        assert "input snapshot" in response.json()["detail"]

    def test_returns_sanitized_500_on_query_error(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_latest.side_effect = CandidatePoolQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 500
        assert response.json() == {"detail": "Candidate pool query failed"}
        assert "secret" not in response.text
        assert "CandidatePoolQueryError" not in response.text

    def test_uses_input_row_count_for_row_count(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31),
            instrument_ids=[uuid4() for _ in range(42)],
            content_hash="c" * 64,
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id, input_row_count=42
        )
        candidate_pool_service.get_latest.return_value = _build_latest_view(
            run=run, snapshot=snapshot, items=(), instrument_map={}
        )

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        assert response.json()["row_count"] == 42

    @pytest.mark.parametrize("status_value", ["calculated", "validated", "rejected"])
    def test_non_published_runs_are_ignored(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
        status_value: str,
    ) -> None:
        status_enum = CandidatePoolStatus(status_value)
        snapshot = make_input_snapshot(
            snapshot_date=date(2026, 7, 31), instrument_ids=[uuid4()]
        )
        run = make_candidate_pool_run(
            input_snapshot_id=snapshot.id,
            status=status_enum,
            rejection_reason="coverage below threshold",
        )
        candidate_pool_service.get_latest.return_value = None
        assert run.status is status_enum
        assert isinstance(run.created_at, datetime)
        assert run.created_at.tzinfo is UTC

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 404

    def test_items_round_trip_with_full_json_fidelity(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
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
        candidate_pool_service.get_latest.return_value = _build_latest_view(
            run=run, snapshot=snapshot, items=[item], instrument_map={}
        )

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
        client: TestClient,
        candidate_pool_service: MagicMock,
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
        candidate_pool_service.get_latest.return_value = _build_latest_view(
            run=run, snapshot=snapshot, items=items, instrument_map={}
        )

        response = client.get(LATEST_ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["included_count"] == 2
        assert body["excluded_count"] == 2


class TestGetCandidatePoolDiff:
    """Coverage for the candidate-pool diff endpoints."""

    def test_diff_returns_added_retained_and_removed(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        removed = uuid4()
        added = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            added=[_entry_for(added)],
            retained=[_entry_for(retained)],
            removed=[_entry_for(removed)],
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
        candidate_pool_service.get_run_diff.assert_called_once_with(current.id)

    def test_diff_excludes_excluded_items_from_all_buckets(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            retained=[_entry_for(retained)],
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
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=None,
            added=[
                _entry_for(second, symbol="510300", name="HS300 ETF"),
                _entry_for(first, symbol="510500", name="SSE 500 ETF"),
            ],
        )

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

    def test_diff_with_current_all_excluded_reports_previous_as_removed(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        removed_first = uuid4()
        removed_second = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            removed=[
                _entry_for(removed_first),
                _entry_for(removed_second),
            ],
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        body = response.json()
        assert body["added"] == []
        assert body["retained"] == []
        removed_ids = {entry["instrument_id"] for entry in body["removed"]}
        assert removed_ids == {str(removed_first), str(removed_second)}

    def test_diff_entries_are_ordered_by_symbol_then_instrument_id(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        first = uuid4()
        second = uuid4()
        third = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            added=[
                _entry_for(first, symbol="159915", name="ChiNext ETF", exchange="SZSE"),
                _entry_for(second, symbol="510300", name="HS300 ETF", exchange="SSE"),
                _entry_for(third, symbol="510500", name="SSE 500 ETF", exchange="SSE"),
            ],
        )

        response = client.get(f"/api/v1/candidate-pool/{current.id}/diff")

        assert response.status_code == 200
        added_symbols = [entry["symbol"] for entry in response.json()["added"]]
        assert added_symbols == sorted(added_symbols)

    def test_diff_entries_with_missing_instruments_have_null_display(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        added = uuid4()
        candidate_pool_service.get_run_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            added=[
                CandidatePoolDiffEntryView(
                    instrument_id=added, symbol=None, name=None, exchange=None
                )
            ],
        )

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
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_run_diff.return_value = None

        response = client.get(f"/api/v1/candidate-pool/{uuid4()}/diff")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.parametrize("status_value", ["calculated", "validated", "rejected"])
    def test_diff_returns_404_for_non_published_run(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
        status_value: str,
    ) -> None:
        run = make_candidate_pool_run(
            trade_date=date(2026, 7, 31), status=CandidatePoolStatus(status_value)
        )
        candidate_pool_service.get_run_diff.return_value = None

        response = client.get(f"/api/v1/candidate-pool/{run.id}/diff")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_diff_returns_500_when_snapshot_missing(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        run_id = uuid4()
        candidate_pool_service.get_run_diff.side_effect = (
            CandidatePoolSnapshotMissingError(snapshot_id=snapshot_id, run_id=run_id)
        )

        response = client.get(f"/api/v1/candidate-pool/{run_id}/diff")

        assert response.status_code == 500
        assert "input snapshot" in response.json()["detail"]

    def test_diff_returns_sanitized_500_on_query_error(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_run_diff.side_effect = CandidatePoolQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(f"/api/v1/candidate-pool/{uuid4()}/diff")

        assert response.status_code == 500
        assert response.json() == {"detail": "Candidate pool query failed"}
        assert "secret" not in response.text

    def test_latest_diff_uses_latest_published_run(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        previous = make_candidate_pool_run(trade_date=date(2026, 7, 30))
        current = make_candidate_pool_run(trade_date=date(2026, 7, 31))
        retained = uuid4()
        candidate_pool_service.get_latest_diff.return_value = _build_diff_view(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            retained=[_entry_for(retained)],
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
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_latest_diff.return_value = None

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 404
        assert "no published candidate pool" in response.json()["detail"]

    def test_latest_diff_returns_500_when_snapshot_missing(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        snapshot_id = uuid4()
        run_id = uuid4()
        candidate_pool_service.get_latest_diff.side_effect = (
            CandidatePoolSnapshotMissingError(snapshot_id=snapshot_id, run_id=run_id)
        )

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 500
        assert "input snapshot" in response.json()["detail"]

    def test_latest_diff_returns_sanitized_500_on_query_error(
        self,
        client: TestClient,
        candidate_pool_service: MagicMock,
    ) -> None:
        candidate_pool_service.get_latest_diff.side_effect = CandidatePoolQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(LATEST_DIFF_ENDPOINT)

        assert response.status_code == 500
        assert response.json() == {"detail": "Candidate pool query failed"}
        assert "secret" not in response.text


__all__ = [
    "TestGetCandidatePoolDiff",
    "TestGetLatestCandidatePool",
]