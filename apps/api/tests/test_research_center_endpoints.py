"""Tests for the ``/api/v1/research-center`` read-only endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the application-level :class:`ResearchCenterQueryService` replaced
through a ``MagicMock`` so the handler can be driven without a live
PostgreSQL connection (and without composing the breadth / freshness /
research / candidate-pool / opportunity underlying services). The
router-level tests assert the HTTP contract:

* the response shape is the frozen ``ResearchCenterResponse`` v1 with
  ``schema_version="1.0.0"``;
* the new Slice 2A ``research`` sub-segment projects the application
  view onto the public JSON shape with ``schema_version="1.0.0"``;
* the new Slice 2B ``candidate_pool`` and ``opportunities``
  sub-segments project the application views onto the public JSON
  shape with the bounded three-state vocabulary;
* ``generated_at`` and ``market.data_freshness.checked_at`` are stamped
  from the same UTC wall-clock call so two callers hitting the
  endpoint in the same instant observe the same timestamp pair;
* the four contract states (``available | partial | unavailable |
  failed``) round-trip through the response with the breadth /
  freshness sub-segments set or ``None`` exactly as the application
  service hands them off;
* the research sub-segment three-state vocabulary (``available |
  empty | failed``) round-trips with explicit ``case_count`` /
  ``run_count`` / ``latest_case`` / ``evidence`` payloads, never with
  fabricated zero values masquerading as "unavailable";
* the candidate-pool and opportunity sub-segments round-trip with
  their three-state vocabulary (``available | empty | failed``) and
  no driver-level detail (path, connection string, credential text)
  ever leaks into the response body;
* the OpenAPI declaration exposes a single GET and the response
  ``$ref`` points at ``ResearchCenterResponse``;
* raw exception / connection-string / credential text never appears in
  a normal 200 response (the application service translates the
  three controlled query errors into a missing or failed
  sub-segment, and any other exception propagates through the generic
  FastAPI boundary rather than leaking through this surface).

The application-level tests in
:mod:`tests.test_research_center_service` exercise the service against
mock breadth / freshness / research / candidate-pool / external
workflow services and own the state machine, observation mapping,
capability placeholders, ``as_of_date`` resolution and narrow
per-source error boundary.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.application.research_center import (
    RESEARCH_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ResearchCenterBreadthView,
    ResearchCenterCandidatePoolSummaryView,
    ResearchCenterCapabilitiesView,
    ResearchCenterCapabilityView,
    ResearchCenterDataFreshnessView,
    ResearchCenterLatestCaseView,
    ResearchCenterMarketView,
    ResearchCenterObservationView,
    ResearchCenterOpportunitySummaryView,
    ResearchCenterQueryService,
    ResearchCenterResearchEvidenceView,
    ResearchCenterResearchSummaryView,
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


def _research_summary_view(
    *,
    state: str = "available",
    case_count: int | None = 3,
    run_count: int | None = 2,
    latest_case: ResearchCenterLatestCaseView | None = None,
    evidence: ResearchCenterResearchEvidenceView | None = None,
) -> ResearchCenterResearchSummaryView:
    """Return a populated research sub-segment view for endpoint tests."""

    if evidence is None:
        evidence = ResearchCenterResearchEvidenceView(
            state="empty",
            pack_id=None,
            quality_status=None,
            freshness_status=None,
        )
    return ResearchCenterResearchSummaryView(
        state=state,  # type: ignore[arg-type]
        case_count=case_count,
        run_count=run_count,
        latest_case=latest_case,
        evidence=evidence,
    )


_UNSET: object = object()
"""Sentinel for distinguishing "argument not supplied" from explicit ``None``."""


def _candidate_pool_summary_view(
    *,
    state: str = "available",
    run_id=_UNSET,
    trade_date: date | None = _AS_OF,
    input_row_count: int | None = 10,
    included_count: int | None = 4,
    excluded_count: int | None = 6,
    reason: str | None = None,
) -> ResearchCenterCandidatePoolSummaryView:
    """Return a populated candidate-pool sub-segment view for endpoint tests."""

    return ResearchCenterCandidatePoolSummaryView(
        state=state,  # type: ignore[arg-type]
        run_id=uuid4() if run_id is _UNSET else run_id,
        trade_date=trade_date,
        input_row_count=input_row_count,
        included_count=included_count,
        excluded_count=excluded_count,
        reason=reason,
    )


def _opportunity_summary_view(
    *,
    state: str = "available",
    observation_count: int | None = 3,
    latest_as_of: date | None = _AS_OF,
    admission_status_counts: dict[str, int] | None | object = _UNSET,
    reason: str | None = None,
) -> ResearchCenterOpportunitySummaryView:
    """Return a populated opportunity sub-segment view for endpoint tests."""

    if admission_status_counts is _UNSET:
        admission_status_counts = {
            "pending": 1,
            "corroborated": 0,
            "admitted": 2,
            "rejected": 0,
            "conflict": 0,
        }
    return ResearchCenterOpportunitySummaryView(
        state=state,  # type: ignore[arg-type]
        observation_count=observation_count,
        latest_as_of=latest_as_of,
        admission_status_counts=admission_status_counts,  # type: ignore[arg-type]
        reason=reason,
    )


def _response_view(
    *,
    state: str = "available",
    breadth: ResearchCenterBreadthView | None,
    data_freshness: ResearchCenterDataFreshnessView | None,
    as_of_date: date | None = _AS_OF,
    quality_status: str | None = "complete",
    freshness_status: str | None = "fresh",
    research: ResearchCenterResearchSummaryView | None = None,
    candidate_pool: ResearchCenterCandidatePoolSummaryView | None = None,
    opportunities: ResearchCenterOpportunitySummaryView | None = None,
) -> ResearchCenterResponseView:
    """Build a populated :class:`ResearchCenterResponse` view for endpoint tests."""

    if research is None:
        research = _research_summary_view()
    if candidate_pool is None:
        candidate_pool = _candidate_pool_summary_view()
    if opportunities is None:
        opportunities = _opportunity_summary_view()
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
        research=research,
        candidate_pool=candidate_pool,
        opportunities=opportunities,
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


class TestResearchCenterResearchSummarySerialization:
    """Coverage for the Slice 2A ``research`` sub-segment on the wire."""

    def test_available_state_projects_counts_and_latest_case_identity(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        latest_case_id = uuid4()
        pack_id = uuid4()
        research = _research_summary_view(
            state="available",
            case_count=4,
            run_count=7,
            latest_case=ResearchCenterLatestCaseView(
                case_id=latest_case_id,
                as_of_date=date(2026, 8, 14),
            ),
            evidence=ResearchCenterResearchEvidenceView(
                state="available",
                pack_id=pack_id,
                quality_status="complete",
                freshness_status="fresh",
            ),
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            research=research,
        )

        body = client.get(ENDPOINT).json()

        research_body = body["research"]
        assert research_body["schema_version"] == RESEARCH_SCHEMA_VERSION
        assert research_body["state"] == "available"
        assert research_body["case_count"] == 4
        assert research_body["run_count"] == 7
        assert research_body["latest_case"] == {
            "case_id": str(latest_case_id),
            "as_of_date": "2026-08-14",
        }
        assert research_body["evidence"] == {
            "state": "available",
            "pack_id": str(pack_id),
            "quality_status": "complete",
            "freshness_status": "fresh",
        }

    def test_empty_state_projects_zero_counts_and_no_latest_case(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research = _research_summary_view(
            state="empty",
            case_count=0,
            run_count=0,
            latest_case=None,
            evidence=ResearchCenterResearchEvidenceView(
                state="empty",
                pack_id=None,
                quality_status=None,
                freshness_status=None,
            ),
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            research=research,
        )

        body = client.get(ENDPOINT).json()

        research_body = body["research"]
        assert research_body["schema_version"] == RESEARCH_SCHEMA_VERSION
        assert research_body["state"] == "empty"
        # Real zero counts are explicit empty, not "unavailable".
        assert research_body["case_count"] == 0
        assert research_body["run_count"] == 0
        assert research_body["latest_case"] is None
        assert research_body["evidence"] == {
            "state": "empty",
            "pack_id": None,
            "quality_status": None,
            "freshness_status": None,
        }

    def test_failed_state_emits_null_counts_not_zero(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research = _research_summary_view(
            state="failed",
            case_count=None,
            run_count=None,
            latest_case=None,
            evidence=ResearchCenterResearchEvidenceView(
                state="empty",
                pack_id=None,
                quality_status=None,
                freshness_status=None,
            ),
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            research=research,
        )

        body = client.get(ENDPOINT).json()

        research_body = body["research"]
        assert research_body["schema_version"] == RESEARCH_SCHEMA_VERSION
        assert research_body["state"] == "failed"
        # Null counts must remain ``null`` so the UI cannot mistake a
        # controlled failure for "data unavailable".
        assert research_body["case_count"] is None
        assert research_body["run_count"] is None
        assert research_body["latest_case"] is None

    def test_research_subsegment_survives_other_market_subsegments_failing(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        # Defensive: a partial market state (breadth failed, freshness
        # available) must still surface the research sub-segment
        # verbatim so the central page can render the research slice
        # even when the market slice is degraded.
        research = _research_summary_view(
            state="available",
            case_count=1,
            run_count=0,
            latest_case=ResearchCenterLatestCaseView(
                case_id=uuid4(),
                as_of_date=date(2026, 8, 14),
            ),
            evidence=ResearchCenterResearchEvidenceView(
                state="empty",
                pack_id=None,
                quality_status=None,
                freshness_status=None,
            ),
        )
        research_center_service.get_research_center.return_value = _response_view(
            state="partial",
            breadth=ResearchCenterBreadthView(state="failed"),
            data_freshness=_data_freshness_view(
                state="available", status="fresh"
            ),
            quality_status=None,
            freshness_status=None,
            research=research,
        )

        body = client.get(ENDPOINT).json()

        assert body["state"] == "partial"
        assert body["market"]["state"] == "partial"
        assert body["research"]["state"] == "available"
        assert body["research"]["case_count"] == 1
        assert body["market"]["breadth"]["state"] == "failed"

    def test_research_subsegment_keys_match_documented_contract(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        body = client.get(ENDPOINT).json()

        research_body = body["research"]
        # Only the documented keys are emitted; the front-end cannot
        # reach into the underlying domain objects.
        assert set(research_body) == {
            "schema_version",
            "state",
            "case_count",
            "run_count",
            "latest_case",
            "evidence",
        }
        assert set(research_body["evidence"]) == {
            "state",
            "pack_id",
            "quality_status",
            "freshness_status",
        }
        if research_body["latest_case"] is not None:
            assert set(research_body["latest_case"]) == {
                "case_id",
                "as_of_date",
            }

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


class TestResearchCenterResearchDependencyWiring:
    """``/api/v1/research-center`` receives the dependency-injected service."""

    def test_router_uses_injected_research_center_service_for_research_slice(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            research=_research_summary_view(
                state="available",
                case_count=2,
                run_count=1,
                latest_case=ResearchCenterLatestCaseView(
                    case_id=uuid4(),
                    as_of_date=date(2026, 8, 14),
                ),
                evidence=ResearchCenterResearchEvidenceView(
                    state="empty",
                    pack_id=None,
                    quality_status=None,
                    freshness_status=None,
                ),
            ),
        )

        response = client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        # The router must call the dependency-injected service
        # exactly once for the whole envelope; the research sub-segment
        # is composed server-side inside the application service, so
        # there is no second source call to assert.
        research_center_service.get_research_center.assert_called_once_with()
        assert body["research"]["state"] == "available"
        assert body["research"]["case_count"] == 2


class TestResearchCenterCandidatePoolSummarySerialization:
    """Coverage for the Slice 2B ``candidate_pool`` sub-segment on the wire."""

    def test_available_state_projects_run_identity_and_counts(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        run_id = uuid4()
        candidate_pool = _candidate_pool_summary_view(
            state="available",
            run_id=run_id,
            trade_date=date(2026, 8, 14),
            input_row_count=10,
            included_count=4,
            excluded_count=6,
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            candidate_pool=candidate_pool,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["candidate_pool"]
        assert sub_body["state"] == "available"
        assert sub_body["run_id"] == str(run_id)
        assert sub_body["trade_date"] == "2026-08-14"
        assert sub_body["input_row_count"] == 10
        assert sub_body["included_count"] == 4
        assert sub_body["excluded_count"] == 6
        assert sub_body["reason"] is None

    def test_empty_state_uses_null_fields_not_zero(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        candidate_pool = _candidate_pool_summary_view(
            state="empty",
            run_id=None,
            trade_date=None,
            input_row_count=None,
            included_count=None,
            excluded_count=None,
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            candidate_pool=candidate_pool,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["candidate_pool"]
        assert sub_body["state"] == "empty"
        # Null fields must remain ``null`` so the UI cannot mistake a
        # missing published run for a populated zero total.
        assert sub_body["run_id"] is None
        assert sub_body["trade_date"] is None
        assert sub_body["input_row_count"] is None
        assert sub_body["included_count"] is None
        assert sub_body["excluded_count"] is None

    def test_failed_query_error_emits_failed_with_query_failed_reason(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        candidate_pool = _candidate_pool_summary_view(
            state="failed",
            run_id=None,
            trade_date=None,
            input_row_count=None,
            included_count=None,
            excluded_count=None,
            reason="candidate_pool_query_failed",
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            candidate_pool=candidate_pool,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["candidate_pool"]
        assert sub_body["state"] == "failed"
        assert sub_body["reason"] == "candidate_pool_query_failed"
        assert sub_body["run_id"] is None
        assert sub_body["trade_date"] is None
        assert sub_body["input_row_count"] is None
        assert sub_body["included_count"] is None
        assert sub_body["excluded_count"] is None

    def test_failed_snapshot_missing_emits_distinct_reason(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        candidate_pool = _candidate_pool_summary_view(
            state="failed",
            run_id=None,
            trade_date=None,
            input_row_count=None,
            included_count=None,
            excluded_count=None,
            reason="candidate_pool_snapshot_missing",
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            candidate_pool=candidate_pool,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["candidate_pool"]
        assert sub_body["state"] == "failed"
        # Distinct reason so the UI can distinguish a snapshot
        # integrity violation from a regular query failure without
        # leaking the underlying identifier.
        assert sub_body["reason"] == "candidate_pool_snapshot_missing"

    def test_subsegment_keys_match_documented_contract(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        body = client.get(ENDPOINT).json()

        assert set(body["candidate_pool"]) == {
            "state",
            "run_id",
            "trade_date",
            "input_row_count",
            "included_count",
            "excluded_count",
            "reason",
        }


class TestResearchCenterOpportunitySummarySerialization:
    """Coverage for the Slice 2B ``opportunities`` sub-segment on the wire."""

    def test_available_state_projects_count_latest_as_of_and_status_mix(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        opportunities = _opportunity_summary_view(
            state="available",
            observation_count=3,
            latest_as_of=date(2026, 8, 14),
            admission_status_counts={
                "pending": 1,
                "corroborated": 0,
                "admitted": 2,
                "rejected": 0,
                "conflict": 0,
            },
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            opportunities=opportunities,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["opportunities"]
        assert sub_body["state"] == "available"
        assert sub_body["observation_count"] == 3
        assert sub_body["latest_as_of"] == "2026-08-14"
        assert sub_body["admission_status_counts"] == {
            "pending": 1,
            "corroborated": 0,
            "admitted": 2,
            "rejected": 0,
            "conflict": 0,
        }
        assert sub_body["reason"] is None

    def test_empty_state_projects_zero_count_and_stable_reason(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        opportunities = _opportunity_summary_view(
            state="empty",
            observation_count=0,
            latest_as_of=None,
            admission_status_counts=None,
            reason="no_opportunity_observations",
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            opportunities=opportunities,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["opportunities"]
        assert sub_body["state"] == "empty"
        # Real zero is explicit: the radar reader observed zero rows.
        assert sub_body["observation_count"] == 0
        assert sub_body["latest_as_of"] is None
        assert sub_body["admission_status_counts"] is None
        assert sub_body["reason"] == "no_opportunity_observations"

    def test_failed_state_emits_null_counts_not_zero(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        opportunities = _opportunity_summary_view(
            state="failed",
            observation_count=None,
            latest_as_of=None,
            admission_status_counts=None,
            reason="opportunity_radar_query_failed",
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            opportunities=opportunities,
        )

        body = client.get(ENDPOINT).json()

        sub_body = body["opportunities"]
        assert sub_body["state"] == "failed"
        assert sub_body["reason"] == "opportunity_radar_query_failed"
        # Null counts must remain ``null`` so the UI cannot mistake a
        # controlled failure for "data unavailable".
        assert sub_body["observation_count"] is None
        assert sub_body["latest_as_of"] is None
        assert sub_body["admission_status_counts"] is None

    def test_subsegment_keys_match_documented_contract(
        self,
        client: TestClient,
        research_center_service: MagicMock,
    ) -> None:
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
        )

        body = client.get(ENDPOINT).json()

        assert set(body["opportunities"]) == {
            "state",
            "observation_count",
            "latest_as_of",
            "admission_status_counts",
            "reason",
        }


class TestResearchCenterSubsegmentFailureLeakage:
    """The failure sub-segments must never echo driver-level detail."""

    @pytest.mark.parametrize(
        "subsegment",
        ["candidate_pool", "opportunities"],
    )
    def test_failed_subsegments_never_echo_driver_level_detail(
        self,
        client: TestClient,
        research_center_service: MagicMock,
        subsegment: str,
    ) -> None:
        candidate_pool = _candidate_pool_summary_view(
            state="failed",
            run_id=None,
            trade_date=None,
            input_row_count=None,
            included_count=None,
            excluded_count=None,
            reason="candidate_pool_query_failed",
        )
        opportunities = _opportunity_summary_view(
            state="failed",
            observation_count=None,
            latest_as_of=None,
            admission_status_counts=None,
            reason="opportunity_radar_query_failed",
        )
        research_center_service.get_research_center.return_value = _response_view(
            breadth=_breadth_view(),
            data_freshness=_data_freshness_view(),
            candidate_pool=candidate_pool,
            opportunities=opportunities,
        )

        body_text = client.get(ENDPOINT).text

        for forbidden in (
            "postgres",
            "postgresql",
            "secret",
            "password",
            "Traceback",
            "/home/",
        ):
            assert forbidden not in body_text, (
                f"forbidden token {forbidden!r} leaked via {subsegment}"
            )


__all__ = [
    "TestResearchCenterCandidatePoolSummarySerialization",
    "TestResearchCenterHappyPath",
    "TestResearchCenterOpenAPI",
    "TestResearchCenterOpportunitySummarySerialization",
    "TestResearchCenterResearchDependencyWiring",
    "TestResearchCenterResearchSummarySerialization",
    "TestResearchCenterServiceWiring",
    "TestResearchCenterStateSerialization",
    "TestResearchCenterSubsegmentFailureLeakage",
    "TestResearchCenterUnknownException",
]
