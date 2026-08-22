"""HTTP-seam tests for the ``GET /api/v1/research-cases/{case_id}/workspace`` endpoint.

The endpoint is exercised through ``fastapi.testclient.TestClient`` with
the application-layer :class:`ResearchQueryService` replaced through a
``MagicMock`` so the handler can be driven without a live PostgreSQL
connection. The router-level tests assert the HTTP contract (status
codes, response shape, sanitized 500 detail, the parallel ``results``
slot, the read-only nature of the route and the case-scoped path) without
touching the real service logic.

The service-level orchestration (case existence short-circuit, parallel
result alignment and the ``SQLAlchemyError`` boundary) is exercised in
:mod:`tests.test_research_workspace_service`.

The happy-path response shape test reuses the real
:class:`EvidencePack` / :class:`ResearchResult` builders from
:mod:`tests.test_research_detail_serialization` so the router's
``from_domain`` mappers run on the canonical domain shapes; this
matches the existing PR-7 detail-endpoint contract.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from uuid import uuid4

from invest_api.application.research import (
    ResearchCaseWorkspaceArtifactView,
    ResearchCaseWorkspaceDiscoveryView,
    ResearchCaseWorkspaceView,
    ResearchQueryError,
)
from invest_domain.instruments import InstrumentId
from invest_domain.integration import AdmissionStatus
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus

from tests.test_research_detail_serialization import (
    _build_case,
    _build_pack,
    _build_result,
    _build_run,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


ENDPOINT_TEMPLATE = "/api/v1/research-cases/{case_id}/workspace"


def _endpoint(case_id) -> str:
    """Format the workspace endpoint URL for ``case_id``."""

    return ENDPOINT_TEMPLATE.format(case_id=case_id)


def make_case(as_of_date: date | None = None) -> ResearchCase:
    """Return a real :class:`ResearchCase` for the router's ``from_domain`` mapper."""

    return ResearchCase(
        case_id=uuid4(),
        instrument_id=InstrumentId(uuid4()),
        as_of_date=as_of_date or date(2026, 8, 7),
        question="Assess medium-term risks",
        horizon="20-60d",
        status=ResearchCaseStatus.DRAFT,
        created_at=datetime(2026, 8, 7, 9, tzinfo=UTC),
    )


def make_run(case_id) -> ResearchRun:
    """Return a real :class:`ResearchRun` for the router's ``from_domain`` mapper."""

    return ResearchRun(
        run_id=uuid4(),
        case_id=case_id,
        evidence_pack_id=uuid4(),
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
        status=ResearchRunStatus.SUCCEEDED,
        attempt=1,
        started_at=datetime(2026, 8, 7, 10, tzinfo=UTC),
        finished_at=datetime(2026, 8, 7, 10, 5, tzinfo=UTC),
    )


class TestWorkspaceEndpoint:
    """Coverage for the ``GET /api/v1/research-cases/{case_id}/workspace`` HTTP contract."""

    def test_returns_404_when_case_is_missing(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        research_service.get_workspace.return_value = None
        case_id = uuid4()

        response = client.get(_endpoint(case_id))

        assert response.status_code == 404
        assert response.json() == {"detail": "Research case not found"}
        research_service.get_workspace.assert_called_once_with(case_id)

    def test_returns_422_for_malformed_case_id(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        response = client.get(_endpoint("not-a-uuid"))

        assert response.status_code == 422
        research_service.get_workspace.assert_not_called()

    def test_returns_sanitized_500_on_research_query_error(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        research_service.get_workspace.side_effect = ResearchQueryError(
            "connection string: postgres://user:secret@host/db"
        )

        response = client.get(_endpoint(uuid4()))

        assert response.status_code == 500
        assert response.json() == {"detail": "Research query failed"}
        assert "secret" not in response.text
        assert "ResearchQueryError" not in response.text

    def test_returns_405_for_write_methods(
        self,
        client: TestClient,
    ) -> None:
        case_id = uuid4()

        assert client.post(_endpoint(case_id), json={}).status_code == 405
        assert client.put(_endpoint(case_id), json={}).status_code == 405
        assert client.patch(_endpoint(case_id), json={}).status_code == 405
        assert client.delete(_endpoint(case_id)).status_code == 405

    def test_composes_case_evidence_runs_and_results_into_response(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
        run = _build_run(case, pack.pack_id)
        result = _build_result(run, pack)
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[pack],
            runs=[run],
            results=[result],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        # The composed case uses the canonical ``ResearchCaseResponse`` shape
        # so the front-end can deep-link without a follow-up round trip.
        assert body["case"]["case_id"] == str(case.case_id)
        assert isinstance(body["evidence_packs"], list)
        assert len(body["evidence_packs"]) == 1
        assert body["evidence_packs"][0]["pack_id"] == str(pack.pack_id)
        assert isinstance(body["runs"], list)
        assert len(body["runs"]) == 1
        assert body["runs"][0]["run_id"] == str(run.run_id)
        assert body["runs"][0]["status"] == "succeeded"
        # ``results`` is parallel to ``runs``: the slot carries the canonical
        # ``ResearchResultResponse`` shape; ``result_id`` and ``run_id`` are
        # echoed back so the front-end can cross-link.
        assert isinstance(body["results"], list)
        assert len(body["results"]) == 1
        assert body["results"][0] is not None
        assert body["results"][0]["result_id"] == str(result.result_id)
        assert body["results"][0]["run_id"] == str(run.run_id)
        assert body["results"][0]["conclusion"] == "Positive with bounded downside"
        research_service.get_workspace.assert_called_once_with(case.case_id)

    def test_results_is_nullable_per_run_when_result_missing(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
        first_run = _build_run(case, pack.pack_id)
        second_run = _build_run(case, pack.pack_id)
        # Only the second run published a result; the first slot must
        # be ``null`` rather than fabricated.
        second_result = _build_result(second_run, pack)
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[],
            runs=[first_run, second_run],
            results=[None, second_result],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        assert len(body["runs"]) == 2
        assert body["runs"][0]["run_id"] == str(first_run.run_id)
        assert body["runs"][1]["run_id"] == str(second_run.run_id)
        assert len(body["results"]) == 2
        # First slot is ``null``; second slot carries the canonical
        # ``ResearchResultResponse`` shape.
        assert body["results"][0] is None
        assert body["results"][1] is not None
        assert body["results"][1]["run_id"] == str(second_run.run_id)

    def test_empty_evidence_and_runs_surface_as_explicit_empty_lists(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = make_case()
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[],
            runs=[],
            results=[],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        assert body["case"]["case_id"] == str(case.case_id)
        assert body["evidence_packs"] == []
        assert body["runs"] == []
        assert body["results"] == []
        # The Stage 4D Task 3.3 ``external_discovery`` slot is
        # always present on the response (the service defaults it to
        # ``[]``) so the workspace page can render an explicit empty
        # state when no external evidence is bound.
        assert body["external_discovery"] == []
        research_service.get_workspace.assert_called_once_with(case.case_id)

    def test_external_discovery_is_serialized_when_bound_to_case(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        observation_id = uuid4()
        run_id = uuid4()
        artifact_view = ResearchCaseWorkspaceArtifactView(
            logical_uri="archive://run/a.json",
            content_hash="a" * 64,
            media_type="application/json",
            size_bytes=256,
            run_id=run_id,
            created_at=datetime(2026, 8, 14, 8, 30, tzinfo=UTC),
        )
        discovery = ResearchCaseWorkspaceDiscoveryView(
            evidence_id="ext-evi:ffffffff",
            observation_id=observation_id,
            run_id=run_id,
            producer="workbuddy",
            as_of=date(2026, 8, 14),
            observed_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
            source_uri="archive://run/a.json",
            content_hash="a" * 64,
            admission_status=AdmissionStatus.ADMITTED.value,
            admission={
                "status": "admitted",
                "reason": "all admission checks passed",
                "rules_version": "observation-admission/1.0",
                "decided_by": "system",
                "checks": {
                    "identity_ok": True,
                    "freshness_ok": True,
                    "unit_ok": True,
                    "internal_cross_check_ok": True,
                    "conflict_detected": False,
                },
            },
            artifact=artifact_view,
        )
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[],
            runs=[],
            results=[],
            external_discovery=[discovery],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["external_discovery"], list)
        assert len(body["external_discovery"]) == 1
        item = body["external_discovery"][0]
        assert item["evidence_id"] == "ext-evi:ffffffff"
        assert item["observation_id"] == str(observation_id)
        assert item["run_id"] == str(run_id)
        assert item["producer"] == "workbuddy"
        assert item["admission_status"] == "admitted"
        # Admission decision metadata is projected verbatim so the
        # WorkBuddy observation, formal admission and research
        # interpretation remain visibly distinct in the UI.
        assert item["admission"]["status"] == "admitted"
        assert item["admission"]["rules_version"] == "observation-admission/1.0"
        # The safe artifact projection: logical_uri + hash +
        # media_type + size + run_id + created_at. Host paths and
        # shared-directory paths must never appear in the response.
        assert item["artifact"] is not None
        assert item["artifact"]["logical_uri"] == "archive://run/a.json"
        assert item["artifact"]["media_type"] == "application/json"
        assert item["artifact"]["size_bytes"] == 256
        assert item["artifact"]["run_id"] == str(run_id)
        assert "host" not in str(item["artifact"]).lower()
        assert "shared" not in str(item["artifact"]).lower()

    def test_external_discovery_artifact_missing_is_serialized_as_null(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        observation_id = uuid4()
        run_id = uuid4()
        discovery = ResearchCaseWorkspaceDiscoveryView(
            evidence_id="ext-evi:gggggggg",
            observation_id=observation_id,
            run_id=run_id,
            producer="workbuddy",
            as_of=date(2026, 8, 14),
            observed_at=datetime(2026, 8, 14, 9, tzinfo=UTC),
            source_uri="archive://run/a.json",
            content_hash="a" * 64,
            admission_status=AdmissionStatus.ADMITTED.value,
            admission={"status": "admitted"},
            artifact=None,
        )
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[],
            runs=[],
            results=[],
            external_discovery=[discovery],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        assert len(body["external_discovery"]) == 1
        # The workspace never fabricates artifact data: a missing
        # bounded artifact lookup projects as ``null`` so the
        # front-end renders an understandable unavailable state.
        assert body["external_discovery"][0]["artifact"] is None
        # Admission / producer metadata still surface so the WorkBuddy
        # provenance stays visible even when the artifact row is
        # missing.
        assert body["external_discovery"][0]["producer"] == "workbuddy"
        assert body["external_discovery"][0]["admission_status"] == "admitted"


class TestWorkspaceEndpointMethodSurface:
    """The :class:`ResearchQueryService` must expose ``get_workspace``."""

    def test_service_exposes_get_workspace(
        self, research_service: MagicMock
    ) -> None:
        assert hasattr(research_service, "get_workspace")


__all__ = [
    "TestWorkspaceEndpoint",
    "TestWorkspaceEndpointMethodSurface",
]

