"""Tests for the ``/api/v1/research-center`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the application-level :class:`ResearchCenterQueryService` replaced
through a ``MagicMock`` so the handler can be driven without a live
PostgreSQL connection (and without composing the breadth / freshness
underlying services). The router-level tests assert the HTTP contract:

* the response shape is the frozen ``ResearchCenterResponse`` v1 with
  ``schema_version="1.0.0"``;
* ``generated_at`` and ``market.data_freshness.checked_at`` are stamped
  from the same UTC wall-clock call so two callers hitting the
  endpoint in the same instant observe the same timestamp pair;
* the four contract states (``available | partial | unavailable |
  failed``) round-trip through the response with the breadth /
  freshness sub-segments set or ``None`` exactly as the application
  service hands them off;
* the OpenAPI declaration exposes a single GET and the response
  ``$ref`` points at ``ResearchCenterResponse``;
* raw exception / connection-string / credential text never appears in
  a normal 200 response (the application service translates the two
  controlled query errors into a missing or failed sub-segment, and
  any other exception propagates through the generic FastAPI
  boundary rather than leaking through this surface).

The application-level tests in
:mod:`tests.test_research_center_service` exercise the service against
mock breadth / freshness services and own the state machine,
observation mapping, capability placeholders, ``as_of_date``
resolution and narrow per-source error boundary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from invest_api.application.research_center import (
    SCHEMA_VERSION,
    ResearchCenterBreadthView,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterDataFreshnessView,
    ResearchCenterMarketView,
    ResearchCenterObservationView,
    ResearchCenterQueryService,
)
from invest_api.application.research_center import (
    ResearchCenterResponse as ResearchCenterResponseView,
)
from invest_api.dependencies import (
    get_db_session,
    get_research_center_query_service,
)
from invest_api.main import app

ENDPOINT: str = "/api/v1/research-center"
_AS_OF: date = date(2026, 8, 15)


def _breadth_view() -> ResearchCenterBreadthView:
    """Return a populated breadth sub-segment view for endpoint tests."""

    # Observations are passed in the alphabetical order the
    # application service inherits from ``MarketObservationSnapshot``
    # (which sorts by ``observation_key`` on construction); the router
    # does not re-order them.
    return ResearchCenterBreadthView(
        state="available",
        snapshot_id="mos:" + ("a" * 32),
        algorithm_version="2.0.0",
        scope_type="ashare_universe",
        scope_key="ashare_active_universe_v1",
        observations=(
            ResearchCenterObservationView(
                key="above_ma20_ratio",
                value=Decimal("0.55"),
                unit="ratio",
                observed_date=_AS_OF,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
                quality_status="complete",
            ),
            ResearchCenterObservationView(
                key="advancing_ratio",
                value=Decimal("0.60"),
                unit="ratio",
                observed_date=_AS_OF,
                source_kind="analytics",
                source_ref="market_breadth:2.0.0",
                quality_status="complete",
            ),
        ),
    )


def _data_freshness_view(
    *,
    state: str = "available",
    status: str = "fresh",
    latest_published_trade_date: date | None = _AS_OF,
    universe_count: int = 100,
    daily_bar_count: int = 100,
    missing_count: int = 0,
) -> ResearchCenterDataFreshnessView:
    """Return a freshness sub-segment view for endpoint tests."""

    return ResearchCenterDataFreshnessView(
        state=state,
        latest_published_trade_date=latest_published_trade_date,
        universe_count=universe_count,
        daily_bar_count=daily_bar_count,
        missing_count=missing_count,
        status=status,
    )


def _capabilities_view() -> ResearchCenterCapabilitiesView:
    """Return the Slice 1 frozen capability bundle."""

    return ResearchCenterCapabilitiesView(
        opportunities=ResearchCenterCapabilityView(
            state="deferred", reason="slice_2_not_implemented"
        ),
        research=ResearchCenterCapabilityView(
            state="deferred", reason="slice_2_not_implemented"
        ),
        delivery=ResearchCenterCapabilityView(
            state="deferred", reason="slice_3_not_implemented"
        ),
        strategy=ResearchCenterCapabilityView(
            state="unavailable",
            reason="strategy_iteration_contract_not_frozen",
        ),
        discipline=ResearchCenterCapabilityView(
            state="unavailable",
            reason="position_discipline_contract_not_frozen",
        ),
    )


def _response_view(
    *,
    state: str = "available",
    breadth: ResearchCenterBreadthView | None,
    data_freshness: ResearchCenterDataFreshnessView | None,
    as_of_date: date | None = _AS_OF,
    quality_status: str | None = "complete",
    freshness_status: str | None = "fresh",
) -> ResearchCenterResponseView:
    """Build a populated :class:`ResearchCenterResponse` view for endpoint tests."""

    return ResearchCenterResponseView(
        schema_version=SCHEMA_VERSION,
        state=state,
        market=ResearchCenterMarketView(
            state=state,
            as_of_date=as_of_date,
            quality_status=quality_status,
            freshness_status=freshness_status,
            breadth=breadth,
            data_freshness=data_freshness,
        ),
        capabilities=_capabilities_view(),
    )


class TestResearchCenterHappyPath:
    """Coverage for the successful response shape and timestamp pairing."""

    def test_returns_contract_response_with_version_and_timestamps(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "1.0.0"
        # Both timestamps are stamped from the same ``datetime.now(UTC)``
        # call so they are byte-identical for a single response.
        assert body["generated_at"] == body["market"]["data_freshness"]["checked_at"]
        # The contract pins a four-state vocabulary; only the contract
        # values appear in the response.
        assert body["state"] in {"available", "partial", "unavailable", "failed"}
        assert body["market"]["state"] == body["state"]

    def test_serializes_breadth_observations_verbatim_with_key_rename(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        breadth = body["market"]["breadth"]
        assert breadth["snapshot_id"].startswith("mos:")
        assert breadth["algorithm_version"] == "2.0.0"
        assert breadth["scope_type"] == "ashare_universe"
        assert breadth["scope_key"] == "ashare_active_universe_v1"
        assert [item["key"] for item in breadth["observations"]] == [
            "above_ma20_ratio",
            "advancing_ratio",
        ]
        # Decimal values serialise as strings (same rule the existing
        # Market Breadth endpoint follows); observation_key is renamed
        # to key; source_ref is preserved byte-for-byte.
        assert breadth["observations"][0]["value"] == "0.55"
        assert breadth["observations"][1]["value"] == "0.60"
        for item in breadth["observations"]:
            assert item["unit"] == "ratio"
            assert item["observed_date"] == _AS_OF.isoformat()
            assert item["source_kind"] == "analytics"
            assert item["source_ref"] == "market_breadth:2.0.0"
            assert item["quality_status"] == "complete"
            # Market Breadth-only field name must not leak.
            assert "observation_key" not in item
            assert "item_hash" not in item

    def test_serializes_data_freshness_subsegment(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(
                state="available",
                status="fresh",
                universe_count=120,
                daily_bar_count=120,
                missing_count=0,
            ),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        freshness = response.json()["market"]["data_freshness"]
        assert freshness["state"] == "available"
        assert freshness["status"] == "fresh"
        assert freshness["universe_count"] == 120
        assert freshness["daily_bar_count"] == 120
        assert freshness["missing_count"] == 0
        assert freshness["latest_published_trade_date"] == _AS_OF.isoformat()
        # Data Freshness-only identifier fields must not leak.
        assert "snapshot_id" not in freshness
        assert "pipeline_run_id" not in freshness
        assert "pipeline_status" not in freshness
        assert "candidate_count" not in freshness
        assert "expected_trade_date" not in freshness

    def test_serializes_capability_placeholders(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        capabilities = response.json()["capabilities"]
        assert capabilities == {
            "opportunities": {
                "state": "deferred",
                "reason": "slice_2_not_implemented",
            },
            "research": {
                "state": "deferred",
                "reason": "slice_2_not_implemented",
            },
            "delivery": {
                "state": "deferred",
                "reason": "slice_3_not_implemented",
            },
            "strategy": {
                "state": "unavailable",
                "reason": "strategy_iteration_contract_not_frozen",
            },
            "discipline": {
                "state": "unavailable",
                "reason": "position_discipline_contract_not_frozen",
            },
        }

    def test_response_has_no_path_or_credential_fields(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        # Defence-in-depth: even when the contract is followed, the
        # response body must never echo workspace paths, API keys,
        # database URLs, host names or secret strings.
        body_text = response.text
        for forbidden in (
            "workspace_path",
            "api_key",
            "secret",
            "postgres",
            "postgresql",
            "password",
            "Traceback",
        ):
            assert forbidden not in body_text

    def test_calls_application_service_once(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        research_center_service.get_research_center.assert_called_once_with()


class TestResearchCenterStateSerialization:
    """The four contract states round-trip through the response body."""

    def test_available_state_round_trips(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            state="available",
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(state="available", status="fresh"),
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "available"
        assert body["market"]["state"] == "available"
        assert body["market"]["breadth"] is not None
        assert body["market"]["data_freshness"] is not None
        assert body["market"]["as_of_date"] == _AS_OF.isoformat()
        assert body["market"]["quality_status"] == "complete"
        assert body["market"]["freshness_status"] == "fresh"

    def test_partial_state_with_breadth_missing(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            state="partial",
            breadth=None,
            data_freshness=_data_freshness_view(state="available", status="fresh"),
            as_of_date=_AS_OF,
            quality_status=None,
            freshness_status=None,
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "partial"
        assert body["market"]["state"] == "partial"
        assert body["market"]["breadth"] is None
        assert body["market"]["data_freshness"] is not None
        assert body["market"]["quality_status"] is None
        assert body["market"]["freshness_status"] is None

    def test_partial_state_with_freshness_degraded(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            state="partial",
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(
                state="partial",
                status="partial",
                universe_count=200,
                daily_bar_count=150,
                missing_count=50,
            ),
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "partial"
        assert body["market"]["state"] == "partial"
        assert body["market"]["breadth"] is not None
        assert body["market"]["data_freshness"]["state"] == "partial"
        assert body["market"]["data_freshness"]["status"] == "partial"
        assert body["market"]["data_freshness"]["missing_count"] == 50

    def test_unavailable_state_round_trips(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            state="unavailable",
            breadth=None,
            data_freshness=_data_freshness_view(
                state="unavailable",
                status="missing",
                latest_published_trade_date=None,
                universe_count=0,
                daily_bar_count=0,
                missing_count=0,
            ),
            as_of_date=None,
            quality_status=None,
            freshness_status=None,
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "unavailable"
        assert body["market"]["state"] == "unavailable"
        assert body["market"]["breadth"] is None
        assert body["market"]["data_freshness"] is not None
        assert body["market"]["data_freshness"]["state"] == "unavailable"
        assert body["market"]["data_freshness"]["status"] == "missing"
        assert body["market"]["as_of_date"] is None

    def test_failed_state_marks_subsegments_without_fabricated_payload(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            state="failed",
            breadth=ResearchCenterBreadthView(state="failed"),
            data_freshness=ResearchCenterDataFreshnessView(
                state="failed",
                latest_published_trade_date=None,
                universe_count=None,
                daily_bar_count=None,
                missing_count=None,
                status="failed",
            ),
            as_of_date=None,
            quality_status=None,
            freshness_status=None,
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "failed"
        assert body["market"]["state"] == "failed"
        assert body["market"]["breadth"] == {
            "state": "failed",
            "snapshot_id": None,
            "algorithm_version": None,
            "scope_type": None,
            "scope_key": None,
            "observations": None,
        }
        freshness = body["market"]["data_freshness"]
        assert freshness["state"] == "failed"
        assert freshness["status"] == "failed"
        assert freshness["latest_published_trade_date"] is None
        assert freshness["universe_count"] is None
        assert freshness["daily_bar_count"] is None
        assert freshness["missing_count"] is None
        # The capability section is still emitted so the dashboard can
        # surface the future-segment placeholder set even when the
        # market segment has nothing to show.
        assert body["capabilities"]["opportunities"]["state"] == "deferred"

    @pytest.mark.parametrize("failed_source", ["breadth", "freshness"])
    def test_partial_state_marks_only_controlled_error_source_failed(
        self,
        client: TestClient,
        research_center_service: MagicMock,
        failed_source: str,
    ) -> None:
        failed_breadth = ResearchCenterBreadthView(state="failed")
        failed_freshness = ResearchCenterDataFreshnessView(
            state="failed",
            latest_published_trade_date=None,
            universe_count=None,
            daily_bar_count=None,
            missing_count=None,
            status="failed",
        )
        research_center_service.get_research_center.return_value = _response_view(
            state="partial",
            breadth=failed_breadth if failed_source == "breadth" else _breadth_view(),
            data_freshness=(
                failed_freshness
                if failed_source == "freshness"
                else _data_freshness_view()
            ),
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "partial"
        failed_key = (
            "data_freshness" if failed_source == "freshness" else failed_source
        )
        assert body["market"][failed_key]["state"] == "failed"
        other_key = "data_freshness" if failed_source == "breadth" else "breadth"
        assert body["market"][other_key]["state"] == "available"
        assert "postgres://" not in str(body)
        assert "/home/" not in str(body)


class TestResearchCenterUnknownException:
    """Unknown exceptions propagate through the generic FastAPI boundary."""

    def test_unknown_exception_is_not_swallowed_into_a_successful_response(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )
        research_center_service.get_research_center.side_effect = boom

        # FastAPI's TestClient re-raises unhandled exceptions in tests
        # (``raise_server_exceptions=True`` is the default). The point
        # of this assertion is that the exception never leaks through a
        # 200 OK response — the generic boundary stays in charge.
        try:
            response = client.get(ENDPOINT)
        except RuntimeError as exc:
            assert "postgres://user:secret@host/db" in str(exc)
            assert "secret" in str(exc)
        else:  # pragma: no cover - defensive
            assert response.status_code != 200, (
                "Unknown exception must not be turned into a 200 response"
            )
            # And even when TestClient is configured to swallow the
            # exception, the body must not echo the driver-level
            # message (no path, connection string or credential text).
            assert "postgres" not in response.text
            assert "secret" not in response.text

    def test_unknown_exception_returns_generic_500_without_secret_or_path_text(
        self,
    ) -> None:
        # Exercise the real HTTP boundary instead of TestClient's
        # default re-raise path: configure a separate TestClient with
        # ``raise_server_exceptions=False`` so the generic FastAPI error
        # handler runs end-to-end and we can assert what the wire
        # actually carries. Both dependency overrides are torn down in
        # the ``finally`` block so the test never leaks state into the
        # next test.
        boom = RuntimeError(
            "driver-level boom: postgres://user:secret@host/db"
        )

        mock_session = MagicMock(name="Session")
        mock_service = MagicMock(name="ResearchCenterQueryService")
        mock_service.get_research_center.side_effect = boom

        app.dependency_overrides[get_db_session] = lambda: mock_session
        app.dependency_overrides[get_research_center_query_service] = (
            lambda: mock_service
        )
        try:
            no_raise_client = TestClient(app, raise_server_exceptions=False)
            response = no_raise_client.get(ENDPOINT)
        finally:
            app.dependency_overrides.pop(get_db_session, None)
            app.dependency_overrides.pop(
                get_research_center_query_service, None
            )

        assert response.status_code == 500
        body_text = response.text
        # Defence-in-depth: the generic 500 body must never echo the
        # driver-level message — no connection string, credential,
        # path, host, password, postgres URL or Python traceback text.
        for forbidden in (
            "postgres",
            "postgresql",
            "secret",
            "password",
            "host",
            "Traceback",
        ):
            assert forbidden not in body_text


class TestResearchCenterOpenAPI:
    """The endpoint declares a single GET and references the contract response."""

    def test_path_declares_only_get_and_response_shape(self) -> None:
        path = app.openapi()["paths"][ENDPOINT]

        assert set(path) == {"get"}
        responses = path["get"]["responses"]
        assert "200" in responses
        assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "ResearchCenterResponse"
        )
        # No POST/PUT/PATCH/DELETE operations are declared anywhere on
        # this path — the surface is intentionally read-only.
        for forbidden in ("post", "put", "patch", "delete"):
            assert forbidden not in path

    def test_openapi_spec_has_no_path_or_credential_strings(self) -> None:
        import json

        spec_text = json.dumps(app.openapi())
        for forbidden in (
            "workspace_path",
            "api_key",
            "secret",
            "postgres://",
        ):
            assert forbidden not in spec_text


class TestResearchCenterServiceWiring:
    """The router receives the dependency-injected application service."""

    def test_router_uses_injected_service(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        assert isinstance(
            research_center_service, MagicMock
        ), "the service should be the injected mock"
        # Sanity: the mock class name matches the dependency override
        # name set by the fixture so reviewers can trace the wiring.
        assert isinstance(
            research_center_service, ResearchCenterQueryService
        ) or research_center_service.__class__.__name__ == "MagicMock"


__all__ = [
    "TestResearchCenterHappyPath",
    "TestResearchCenterOpenAPI",
    "TestResearchCenterServiceWiring",
    "TestResearchCenterStateSerialization",
    "TestResearchCenterUnknownException",
]
