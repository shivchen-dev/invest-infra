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
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)

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


class TestWorkspaceTimeline:
    """Coverage for the read-only ``timeline`` projection on the workspace envelope.

    The timeline is derived inside the Pydantic
    :class:`ResearchCaseWorkspaceResponse` from the already-composed
    resource surfaces, so these tests drive the public HTTP contract
    via ``TestClient`` and assert:

    - the closed event vocabulary (case_created,
      evidence_pack_available, external_observation,
      research_run_started, research_run_finished,
      research_result_published),
    - the deterministic ascending sort (timestamped events first,
      ``None`` timestamps last; ties broken on
      ``event_type`` / ``source_id``),
    - the explicit ``occurred_at = None`` for evidence packs (the
      domain carries no creation timestamp; the label must make the
      unavailability explicit so the front-end cannot read a date),
    - the visibility of failed runs (the run has both ``started_at``
      and ``finished_at`` set, so both events surface with the
      ``failed`` status).
    """

    def test_timeline_emits_all_event_types_for_happy_path(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
        run = _build_run(case, pack.pack_id)
        # The shared ``_build_result`` fixture uses ``datetime.now(UTC)``
        # which would make the timeline assertion non-deterministic;
        # build the result directly with an explicit ``created_at``.
        result = ResearchResult.create(
            run=run,
            evidence_pack=pack,
            conclusion="Positive with bounded downside",
            risks=("valuation", "liquidity"),
            evidence_ids=(pack.factors[0].evidence_id, pack.factors[1].evidence_id),
            report_markdown="# Report\n\nEvidence-backed.",
            model_key="model-key-v1",
            model_version="model-v1",
            playbook_version="playbook-v1",
            adapter_version="adapter-v1",
            created_at=datetime(2026, 3, 6, 10, 10, tzinfo=UTC),
        )
        observation_id = uuid4()
        discovery = ResearchCaseWorkspaceDiscoveryView(
            evidence_id="ext-evi:11111111",
            observation_id=observation_id,
            run_id=run.run_id,
            producer="workbuddy",
            as_of=date(2026, 3, 6),
            observed_at=datetime(2026, 3, 6, 8, 30, tzinfo=UTC),
            source_uri="archive://run/a.json",
            content_hash="a" * 64,
            admission_status=AdmissionStatus.ADMITTED.value,
            admission={"status": "admitted"},
            artifact=None,
        )
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[pack],
            runs=[run],
            results=[result],
            external_discovery=[discovery],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        body = response.json()
        event_types = [item["event_type"] for item in body["timeline"]]
        assert event_types == [
            "external_observation",
            "case_created",
            "research_run_started",
            "research_run_finished",
            "research_result_published",
            "evidence_pack_available",
        ]
        event_index = {event: index for index, event in enumerate(event_types)}
        assert event_index["case_created"] < event_index["research_run_started"]
        assert event_index["research_run_started"] < event_index["research_run_finished"]
        assert event_index["research_run_finished"] < event_index["research_result_published"]
        assert event_index["evidence_pack_available"] == len(event_types) - 1
        item_by_type = {item["event_type"]: item for item in body["timeline"]}
        assert item_by_type["case_created"]["source_id"] == str(case.case_id)
        assert item_by_type["case_created"]["status"] == "draft"
        assert item_by_type["case_created"]["occurred_at"] == "2026-03-06T09:00:00Z"
        assert item_by_type["evidence_pack_available"]["source_id"] == str(pack.pack_id)
        assert item_by_type["research_run_started"]["source_id"] == str(run.run_id)
        assert item_by_type["research_run_finished"]["source_id"] == str(run.run_id)
        assert (
            item_by_type["research_result_published"]["source_id"] == str(result.result_id)
        )
        assert item_by_type["external_observation"]["source_id"] == "ext-evi:11111111"
        assert item_by_type["external_observation"]["status"] == "admitted"
        assert item_by_type["external_observation"]["label"] == (
            "workbuddy / archive://run/a.json"
        )

    def test_timeline_sorts_timestamped_events_ascending_with_nulls_last(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack_a = _build_pack(case_id=case.case_id, pack_id=uuid4())
        pack_b = _build_pack(case_id=case.case_id, pack_id=uuid4())
        queued_run = ResearchRun.create(
            case_id=case.case_id,
            evidence_pack_id=pack_a.pack_id,
            runner_key="jiuwenswarm",
            playbook_key="etf_medium_term_assessment",
        )
        started_run = queued_run.start(
            occurred_at=datetime(2026, 3, 6, 11, 30, tzinfo=UTC),
        )
        succeeded_run = started_run.succeed(
            occurred_at=datetime(2026, 3, 6, 11, 35, tzinfo=UTC),
        )
        # Second run started **after** the first finished so the
        # sort order is unambiguous.
        second_run = ResearchRun.create(
            case_id=case.case_id,
            evidence_pack_id=pack_b.pack_id,
            runner_key="jiuwenswarm",
            playbook_key="etf_medium_term_assessment",
        ).start(occurred_at=datetime(2026, 3, 6, 12, tzinfo=UTC))
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[pack_a, pack_b],
            runs=[queued_run, succeeded_run, second_run],
            results=[None, None, None],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        timeline = response.json()["timeline"]
        occurred_at_values = [item["occurred_at"] for item in timeline]
        timestamped = [item for item in timeline if item["occurred_at"] is not None]
        # Every timestamped event sorts ascending by occurred_at.
        assert occurred_at_values[: len(timestamped)] == [
            item["occurred_at"] for item in timestamped
        ]
        assert timestamped == sorted(
            timestamped,
            key=lambda item: (item["occurred_at"], item["event_type"], item["source_id"]),
        )
        # Every null-timestamped event (evidence_pack_available only)
        # sits after every timestamped event.
        null_tail = [item for item in timeline if item["occurred_at"] is None]
        assert null_tail
        assert all(item["event_type"] == "evidence_pack_available" for item in null_tail)
        last_timestamped_index = max(
            index for index, item in enumerate(timeline) if item["occurred_at"] is not None
        )
        first_null_index = min(
            index for index, item in enumerate(timeline) if item["occurred_at"] is None
        )
        assert last_timestamped_index < first_null_index

    def test_timeline_marks_evidence_pack_timestamp_as_unavailable(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[pack],
            runs=[],
            results=[],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        timeline = response.json()["timeline"]
        pack_events = [
            item for item in timeline if item["event_type"] == "evidence_pack_available"
        ]
        assert len(pack_events) == 1
        item = pack_events[0]
        # The domain carries no creation timestamp for an
        # ``EvidencePack``; the workspace must surface the explicit
        # ``None`` rather than fabricate one.
        assert item["occurred_at"] is None
        assert item["source_id"] == str(pack.pack_id)
        assert item["status"] == pack.data_quality.quality_status.value
        # The label must make the unavailability explicit so the
        # front-end cannot accidentally render a date.
        assert "unavailable" in item["label"].lower()
        assert "timestamp" in item["label"].lower()
        assert "host" not in item["label"].lower()
        assert "path" not in item["label"].lower()

    def test_timeline_surfaces_failed_run_with_started_and_finished_events(
        self,
        client: TestClient,
        research_service: MagicMock,
    ) -> None:
        case = _build_case()
        pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
        queued_run = ResearchRun.create(
            case_id=case.case_id,
            evidence_pack_id=pack.pack_id,
            runner_key="jiuwenswarm",
            playbook_key="etf_medium_term_assessment",
        )
        running_run = queued_run.start(
            occurred_at=datetime(2026, 3, 6, 13, tzinfo=UTC),
        )
        failed_run = running_run.fail(
            error_summary="runner exited non-zero",
            occurred_at=datetime(2026, 3, 6, 13, 5, tzinfo=UTC),
        )
        view = ResearchCaseWorkspaceView(
            case=case,
            evidence_packs=[pack],
            runs=[failed_run],
            results=[None],
        )
        research_service.get_workspace.return_value = view

        response = client.get(_endpoint(case.case_id))

        assert response.status_code == 200
        timeline = response.json()["timeline"]
        event_types = [item["event_type"] for item in timeline]
        assert "research_run_started" in event_types
        assert "research_run_finished" in event_types
        # A failed run publishes no result; the result event must
        # therefore be absent (rather than fabricated).
        assert "research_result_published" not in event_types
        started_item = next(
            item for item in timeline if item["event_type"] == "research_run_started"
        )
        finished_item = next(
            item for item in timeline if item["event_type"] == "research_run_finished"
        )
        assert started_item["source_id"] == str(failed_run.run_id)
        assert finished_item["source_id"] == str(failed_run.run_id)
        assert started_item["status"] == "failed"
        assert finished_item["status"] == "failed"
        assert started_item["occurred_at"] == "2026-03-06T13:00:00Z"
        assert finished_item["occurred_at"] == "2026-03-06T13:05:00Z"
        # Sort: started < finished, both before the pack event.
        assert (
            event_types.index("research_run_started")
            < event_types.index("research_run_finished")
            < event_types.index("evidence_pack_available")
        )


__all__ = [
    "TestWorkspaceEndpoint",
    "TestWorkspaceEndpointMethodSurface",
    "TestWorkspaceTimeline",
]

