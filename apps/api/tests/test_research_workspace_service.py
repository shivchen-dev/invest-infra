"""Tests for :meth:`invest_api.application.research.ResearchQueryService.get_workspace`.

The endpoint tests in :mod:`tests.test_research_workspace_endpoints`
mock the application service at the FastAPI boundary and verify the
HTTP contract. These tests bypass the HTTP layer: they construct the
real service against structurally-compatible mocks so they can assert
that the service itself owns the workspace orchestration:

- 404 resolution (returns ``None`` when the case is missing rather than
  raising; the router translates that to the standard 404 detail),
- the deterministic read sequence (``cases.get`` first, then
  ``evidence.list_by_case`` + ``runs.list_by_case``, then one
  ``results.get_by_run_id`` per run),
- the parallel ``results`` list that mirrors ``runs`` positionally and
  carries ``None`` for runs without a result,
- empty branches (no evidence, no runs, both empty) without inventing
  data,
- the Stage 4D Task 3.3 ``external_discovery`` slot: case-scoped
  list of admitted external-evidence items, missing source
  observations skipped, missing artifacts projected as ``None``,
  and the optional readers defaulting to an empty list when the
  service is built without them,
- the :class:`sqlalchemy.exc.SQLAlchemyError` translation to
  :class:`ResearchQueryError` for every reader call site, including
  the new external-chain readers.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.research import (
    ResearchCaseWorkspaceArtifactView,
    ResearchCaseWorkspaceDiscoveryView,
    ResearchCaseWorkspaceView,
    ResearchQueryError,
    ResearchQueryService,
)
from invest_domain.integration import AdmissionStatus
from sqlalchemy.exc import OperationalError


def _case_shim(*, case_id):
    """Return a structurally-compatible ``ResearchCase`` shim."""

    return SimpleNamespace(
        case_id=case_id,
        instrument_id=SimpleNamespace(value=uuid4()),
        as_of_date="2026-08-07",
        question="Assess medium-term risks",
        horizon="20-60d",
        status=SimpleNamespace(value="draft"),
        created_at="2026-08-07T09:00:00Z",
        closed_at=None,
        candidate_pool_run_id=None,
    )


def _pack_shim(*, pack_id, case_id):
    """Return a structurally-compatible ``EvidencePack`` shim."""

    return SimpleNamespace(
        pack_id=pack_id,
        case=SimpleNamespace(case_id=case_id),
    )


def _run_shim(*, run_id, case_id):
    """Return a structurally-compatible ``ResearchRun`` shim."""

    return SimpleNamespace(
        run_id=run_id,
        case_id=case_id,
        evidence_pack_id=uuid4(),
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
        status="succeeded",
        attempt=1,
        started_at="2026-08-07T10:00:00Z",
        finished_at="2026-08-07T10:05:00Z",
        error_summary=None,
    )


def _result_shim(*, run_id, result_id):
    """Return a structurally-compatible ``ResearchResult`` shim."""

    return SimpleNamespace(
        result_id=result_id,
        run_id=run_id,
    )


def _build_repositories(
    *,
    case=None,
    packs_by_case=None,
    runs_by_case=None,
    results_by_run=None,
):
    """Return a tuple of mock repositories configured for the workspace tests.

    ``packs_by_case`` is a mapping ``{case_id: [pack, ...]}`` and
    ``runs_by_case`` is a mapping ``{case_id: [run, ...]}``. Cases
    absent from either mapping resolve to ``[]`` so the empty
    branches are trivially driveable. ``results_by_run`` is a mapping
    ``{run_id: result}``; runs absent from the mapping resolve to
    ``None`` so the missing-result branch is trivially driveable.
    """

    packs = packs_by_case or {}
    runs_map = runs_by_case or {}
    results_map = results_by_run or {}

    cases = MagicMock(name="ResearchCaseRepository")
    cases.get.side_effect = (
        lambda case_id: case if case is not None and case_id == case.case_id else None
    )

    evidence = MagicMock(name="ResearchEvidenceRepository")
    evidence.list_by_case.side_effect = lambda case_id: list(packs.get(case_id, []))

    runs = MagicMock(name="ResearchRunRepository")
    runs.list_by_case.side_effect = lambda case_id: list(runs_map.get(case_id, []))

    results = MagicMock(name="ResearchResultRepository")
    results.get_by_run_id.side_effect = lambda run_id: results_map.get(run_id)

    return cases, evidence, runs, results


def _observation_shim(
    *,
    observation_id,
    run_id,
    source_uri="archive://run/a.json",
    producer="workbuddy",
    admission_status=AdmissionStatus.ADMITTED,
    admission_metadata=None,
    as_of_date=None,
):
    """Return a structurally-compatible ``ExternalObservation`` shim."""

    return SimpleNamespace(
        observation_id=observation_id,
        run_id=run_id,
        observed_at="2026-08-14T09:00:00Z",
        as_of=as_of_date or "2026-08-14",
        source_uri=source_uri,
        producer=producer,
        payload={},
        artifact_id=None,
        symbol=None,
        instrument_id=None,
        admission_status=SimpleNamespace(value=admission_status.value),
        metadata=(
            {"admission": dict(admission_metadata)}
            if admission_metadata is not None
            else {}
        ),
    )


def _evidence_item_shim(
    *,
    evidence_id,
    observation_id,
    run_id,
    artifact_id=None,
    content_hash="a" * 64,
    admission=None,
):
    """Return a structurally-compatible ``ExternalEvidenceItem`` shim."""

    return SimpleNamespace(
        evidence_id=evidence_id,
        observation_id=observation_id,
        run_id=run_id,
        artifact_id=artifact_id,
        artifact_content_hash="a" * 64 if artifact_id is not None else None,
        observed_at="2026-08-14T09:00:00Z",
        as_of="2026-08-14",
        source_uri="archive://run/a.json",
        producer="workbuddy",
        payload={},
        admission=dict(admission) if admission is not None else {},
        content_hash=content_hash,
    )


def _artifact_shim(
    *,
    artifact_id,
    run_id,
    logical_uri="archive://run/a.json",
    content_hash="a" * 64,
    media_type="application/json",
    size_bytes=128,
):
    """Return a structurally-compatible ``ExternalArtifact`` shim."""

    return SimpleNamespace(
        artifact_id=artifact_id,
        run_id=run_id,
        logical_uri=logical_uri,
        content_hash=content_hash,
        media_type=media_type,
        size_bytes=size_bytes,
        created_at="2026-08-14T08:30:00Z",
        metadata={},
    )


def _build_external_repositories(
    *,
    external_by_case=None,
    observations_by_id=None,
    artifacts_by_id=None,
):
    """Return a tuple of mock external-chain repositories.

    ``external_by_case`` maps ``case_id -> [ExternalEvidenceItem, ...]``;
    cases absent from the mapping resolve to ``[]`` so the empty
    branch is trivially driveable. ``observations_by_id`` and
    ``artifacts_by_id`` map id -> row; missing IDs resolve to ``None``
    so the missing-source / missing-artifact branches are driveable
    without explicit None checks.
    """

    external = external_by_case or {}
    obs_map = observations_by_id or {}
    art_map = artifacts_by_id or {}

    ext_evidence = MagicMock(name="ResearchExternalEvidenceRepository")
    ext_evidence.list_by_case.side_effect = lambda case_id: list(
        external.get(case_id, [])
    )

    observations = MagicMock(name="ExternalObservationRepository")
    observations.get_by_id.side_effect = lambda obs_id: obs_map.get(obs_id)

    artifacts = MagicMock(name="ExternalArtifactRepository")
    artifacts.get_by_id.side_effect = lambda art_id: art_map.get(art_id)

    return ext_evidence, observations, artifacts


class TestWorkspaceHappyPath:
    """Coverage for the populated case branch."""

    def test_composes_case_evidence_runs_and_results(self) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        first_pack = _pack_shim(pack_id=uuid4(), case_id=case_id)
        second_pack = _pack_shim(pack_id=uuid4(), case_id=case_id)
        first_run = _run_shim(run_id=uuid4(), case_id=case_id)
        second_run = _run_shim(run_id=uuid4(), case_id=case_id)
        first_result = _result_shim(
            run_id=first_run.run_id, result_id=uuid4()
        )
        cases, evidence, runs, results = _build_repositories(
            case=case,
            packs_by_case={case_id: [first_pack, second_pack]},
            runs_by_case={case_id: [first_run, second_run]},
            results_by_run={first_run.run_id: first_result},
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_workspace(case_id)

        assert isinstance(view, ResearchCaseWorkspaceView)
        assert view.case is case
        assert view.evidence_packs == [first_pack, second_pack]
        assert view.runs == [first_run, second_run]
        # ``results`` is the positional companion of ``runs``: the
        # first slot carries the published result, the second slot is
        # ``None`` because no row exists for ``second_run``.
        assert view.results == [first_result, None]
        assert len(view.results) == len(view.runs)

        cases.get.assert_called_once_with(case_id)
        evidence.list_by_case.assert_called_once_with(case_id)
        runs.list_by_case.assert_called_once_with(case_id)
        # One ``get_by_run_id`` call per run; never an arbitrary subset.
        results.get_by_run_id.assert_any_call(first_run.run_id)
        results.get_by_run_id.assert_any_call(second_run.run_id)
        assert results.get_by_run_id.call_count == 2

    def test_returns_view_with_all_lists_when_no_evidence_or_runs(self) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        cases, evidence, runs, results = _build_repositories(case=case)

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_workspace(case_id)

        assert view is not None
        assert view.case is case
        # Both ``evidence_packs`` and ``runs`` are explicit empty lists;
        # ``results`` mirrors ``runs`` and is therefore also ``[]``.
        assert view.evidence_packs == []
        assert view.runs == []
        assert view.results == []
        cases.get.assert_called_once_with(case_id)
        evidence.list_by_case.assert_called_once_with(case_id)
        runs.list_by_case.assert_called_once_with(case_id)
        # No runs -> no result lookups, the endpoint must not invent
        # results for a run list of zero length.
        results.get_by_run_id.assert_not_called()


class TestWorkspaceMissingCase:
    """Coverage for the missing-case branch (router stamps 404)."""

    def test_returns_none_when_case_is_missing(self) -> None:
        case_id = uuid4()
        cases, evidence, runs, results = _build_repositories(case=None)

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_workspace(case_id)

        assert view is None
        cases.get.assert_called_once_with(case_id)
        # The service must short-circuit before issuing nested reads so
        # the missing-case path does not fan out into the storage layer.
        evidence.list_by_case.assert_not_called()
        runs.list_by_case.assert_not_called()
        results.get_by_run_id.assert_not_called()


class TestWorkspaceMissingResult:
    """Coverage for the missing-result branch (nullable per-run slot)."""

    def test_results_is_aligned_with_runs_and_nullable_per_run(self) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        first_run = _run_shim(run_id=uuid4(), case_id=case_id)
        second_run = _run_shim(run_id=uuid4(), case_id=case_id)
        third_run = _run_shim(run_id=uuid4(), case_id=case_id)
        only_middle_result = _result_shim(
            run_id=second_run.run_id, result_id=uuid4()
        )
        cases, evidence, runs, results = _build_repositories(
            case=case,
            runs_by_case={case_id: [first_run, second_run, third_run]},
            results_by_run={second_run.run_id: only_middle_result},
        )

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_workspace(case_id)

        assert view is not None
        assert view.runs == [first_run, second_run, third_run]
        # Only ``second_run`` has a published result; the other two
        # slots are explicit ``None`` so the front-end renders an empty
        # result slot rather than inventing one.
        assert view.results == [None, only_middle_result, None]
        assert len(view.results) == len(view.runs)


class TestWorkspaceSqlAlchemyError:
    """``SQLAlchemyError`` must be translated to ``ResearchQueryError``."""

    @pytest.mark.parametrize(
        "configure",
        [
            lambda cases, _, runs, __: setattr(
                cases.get, "side_effect",
                OperationalError("SELECT case", {}, Exception("password=secret")),
            ),
            lambda cases, evidence, runs, results: setattr(
                evidence.list_by_case, "side_effect",
                OperationalError("SELECT packs", {}, Exception("password=secret")),
            ),
            lambda cases, evidence, runs, results: setattr(
                runs.list_by_case, "side_effect",
                OperationalError("SELECT runs", {}, Exception("password=secret")),
            ),
            lambda cases, evidence, runs, results: setattr(
                results.get_by_run_id, "side_effect",
                OperationalError("SELECT result", {}, Exception("password=secret")),
            ),
        ],
    )
    def test_translates_sqlalchemy_errors_without_details(
        self, configure
    ) -> None:
        # Build a fully populated workspace so every reader path is
        # exercised depending on which side_effect ``configure`` wires.
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        first_run = _run_shim(run_id=uuid4(), case_id=case_id)
        cases, evidence, runs, results = _build_repositories(
            case=case,
            packs_by_case={case_id: [_pack_shim(pack_id=uuid4(), case_id=case_id)]},
            runs_by_case={case_id: [first_run]},
            results_by_run={first_run.run_id: _result_shim(
                run_id=first_run.run_id, result_id=uuid4()
            )},
        )
        configure(cases, evidence, runs, results)

        with pytest.raises(ResearchQueryError) as exc_info:
            ResearchQueryService(cases, evidence, runs, results).get_workspace(case_id)

        assert str(exc_info.value) == "research query failed"
        # Sanitized: no driver-level detail leaks.
        assert "password" not in str(exc_info.value)
        assert "secret" not in str(exc_info.value)


class TestWorkspaceProtocolSurface:
    """The ``ResearchRunReader`` protocol must expose ``list_by_case``."""

    def test_research_run_reader_protocol_exposes_list_by_case(self) -> None:
        from invest_api.application.research import ResearchRunReader

        assert "list_by_case" in dir(ResearchRunReader)


class TestWorkspaceExternalDiscoveryHappyPath:
    """Coverage for the populated external-chain branch (Stage 4D Task 3.3)."""

    def test_composes_external_discovery_with_observation_and_artifact(
        self,
    ) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        run_id = uuid4()
        observation_id = uuid4()
        artifact_id = uuid4()
        observation = _observation_shim(
            observation_id=observation_id,
            run_id=run_id,
            source_uri="archive://run/a.json",
            producer="workbuddy",
            admission_status=AdmissionStatus.ADMITTED,
            admission_metadata={
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
        )
        artifact = _artifact_shim(artifact_id=artifact_id, run_id=run_id)
        evidence_item = _evidence_item_shim(
            evidence_id="ext-evi:aaaaaaaa",
            observation_id=observation_id,
            run_id=run_id,
            artifact_id=artifact_id,
            admission=observation.metadata["admission"],
        )
        cases, evidence, runs, results = _build_repositories(case=case)
        ext_evidence, observations, artifacts = _build_external_repositories(
            external_by_case={case_id: [evidence_item]},
            observations_by_id={observation_id: observation},
            artifacts_by_id={artifact_id: artifact},
        )

        service = ResearchQueryService(
            cases,
            evidence,
            runs,
            results,
            external_evidence_repository=ext_evidence,
            observation_repository=observations,
            artifact_repository=artifacts,
        )
        view = service.get_workspace(case_id)

        assert isinstance(view, ResearchCaseWorkspaceView)
        assert len(view.external_discovery) == 1
        item = view.external_discovery[0]
        assert isinstance(item, ResearchCaseWorkspaceDiscoveryView)
        assert item.evidence_id == "ext-evi:aaaaaaaa"
        assert item.observation_id == observation_id
        assert item.run_id == run_id
        assert item.producer == "workbuddy"
        assert item.source_uri == "archive://run/a.json"
        assert item.admission_status == "admitted"
        # The admission decision metadata is projected verbatim from
        # the bound evidence row; the service does not invent or
        # rewrite it.
        assert item.admission["status"] == "admitted"
        assert item.admission["rules_version"] == "observation-admission/1.0"
        # Artifact is projected into the safe view (logical_uri +
        # hash + media_type + size + run_id + created_at). Host
        # paths / shared-directory paths are never surfaced.
        assert item.artifact is not None
        assert isinstance(item.artifact, ResearchCaseWorkspaceArtifactView)
        assert item.artifact.logical_uri == "archive://run/a.json"
        assert item.artifact.media_type == "application/json"
        assert item.artifact.size_bytes == 128
        assert item.artifact.run_id == run_id

        # Bounded repository lookups: one list_by_case + one
        # observation get_by_id + one artifact get_by_id. The service
        # never falls back to a global scan.
        ext_evidence.list_by_case.assert_called_once_with(case_id)
        observations.get_by_id.assert_called_once_with(observation_id)
        artifacts.get_by_id.assert_called_once_with(artifact_id)

    def test_external_discovery_is_empty_when_no_evidence_bound(
        self,
    ) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        cases, evidence, runs, results = _build_repositories(case=case)
        ext_evidence, observations, artifacts = _build_external_repositories()

        service = ResearchQueryService(
            cases,
            evidence,
            runs,
            results,
            external_evidence_repository=ext_evidence,
            observation_repository=observations,
            artifact_repository=artifacts,
        )
        view = service.get_workspace(case_id)

        assert view is not None
        # Explicit empty list: the workspace never projects ``None``
        # for the external-discovery slot.
        assert view.external_discovery == []
        ext_evidence.list_by_case.assert_called_once_with(case_id)
        # No items -> no observation / artifact lookups; the service
        # short-circuits before issuing nested reads.
        observations.get_by_id.assert_not_called()
        artifacts.get_by_id.assert_not_called()


class TestWorkspaceExternalDiscoveryUnavailability:
    """Coverage for the artifact / observation unavailable branches."""

    def test_artifact_unavailable_is_projected_as_none(self) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        run_id = uuid4()
        observation_id = uuid4()
        artifact_id = uuid4()
        observation = _observation_shim(
            observation_id=observation_id,
            run_id=run_id,
            admission_status=AdmissionStatus.ADMITTED,
        )
        evidence_item = _evidence_item_shim(
            evidence_id="ext-evi:bbbbbbbb",
            observation_id=observation_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        cases, evidence, runs, results = _build_repositories(case=case)
        ext_evidence, observations, artifacts = _build_external_repositories(
            external_by_case={case_id: [evidence_item]},
            observations_by_id={observation_id: observation},
            # No artifact row registered -> lookup returns ``None``
            artifacts_by_id={},
        )

        service = ResearchQueryService(
            cases,
            evidence,
            runs,
            results,
            external_evidence_repository=ext_evidence,
            observation_repository=observations,
            artifact_repository=artifacts,
        )
        view = service.get_workspace(case_id)

        assert view is not None
        assert len(view.external_discovery) == 1
        # The service must not fabricate artifact data when the
        # bounded lookup misses: the workspace exposes ``None`` so
        # the front-end can render an understandable unavailable
        # state.
        assert view.external_discovery[0].artifact is None
        # Producer / admission metadata still surface from the
        # source observation so the WorkBuddy provenance is visible.
        assert view.external_discovery[0].producer == "workbuddy"
        assert view.external_discovery[0].admission_status == "admitted"
        artifacts.get_by_id.assert_called_once_with(artifact_id)

    def test_missing_source_observation_skips_the_row(self) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        run_id = uuid4()
        present_observation_id = uuid4()
        missing_observation_id = uuid4()
        present_artifact_id = uuid4()
        present_observation = _observation_shim(
            observation_id=present_observation_id,
            run_id=run_id,
        )
        present_artifact = _artifact_shim(
            artifact_id=present_artifact_id, run_id=run_id
        )
        present_item = _evidence_item_shim(
            evidence_id="ext-evi:cccccccc",
            observation_id=present_observation_id,
            run_id=run_id,
            artifact_id=present_artifact_id,
        )
        # The ``missing`` evidence row has no resolvable source
        # observation in storage; the service must skip it rather
        # than emit a dangling row.
        missing_item = _evidence_item_shim(
            evidence_id="ext-evi:dddddddd",
            observation_id=missing_observation_id,
            run_id=run_id,
        )
        cases, evidence, runs, results = _build_repositories(case=case)
        ext_evidence, observations, artifacts = _build_external_repositories(
            external_by_case={case_id: [present_item, missing_item]},
            observations_by_id={present_observation_id: present_observation},
            artifacts_by_id={present_artifact_id: present_artifact},
        )

        service = ResearchQueryService(
            cases,
            evidence,
            runs,
            results,
            external_evidence_repository=ext_evidence,
            observation_repository=observations,
            artifact_repository=artifacts,
        )
        view = service.get_workspace(case_id)

        assert view is not None
        assert len(view.external_discovery) == 1
        assert view.external_discovery[0].evidence_id == "ext-evi:cccccccc"
        observations.get_by_id.assert_any_call(present_observation_id)
        observations.get_by_id.assert_any_call(missing_observation_id)
        assert observations.get_by_id.call_count == 2

    def test_external_discovery_defaults_to_empty_without_readers(self) -> None:
        """When the service is built without external-chain readers,
        the workspace surfaces an explicit empty ``external_discovery``
        list rather than fabricating the slot."""
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        cases, evidence, runs, results = _build_repositories(case=case)

        service = ResearchQueryService(cases, evidence, runs, results)
        view = service.get_workspace(case_id)

        assert view is not None
        assert view.external_discovery == []


class TestWorkspaceExternalDiscoverySqlAlchemyError:
    """``SQLAlchemyError`` from the external-chain readers must be translated."""

    @pytest.mark.parametrize(
        "configure",
        [
            lambda ext, obs, art: setattr(
                ext.list_by_case, "side_effect",
                OperationalError("SELECT ext", {}, Exception("password=secret")),
            ),
            lambda ext, obs, art: setattr(
                obs.get_by_id, "side_effect",
                OperationalError("SELECT obs", {}, Exception("password=secret")),
            ),
            lambda ext, obs, art: setattr(
                art.get_by_id, "side_effect",
                OperationalError("SELECT art", {}, Exception("password=secret")),
            ),
        ],
    )
    def test_translates_sqlalchemy_errors_without_details(self, configure) -> None:
        case_id = uuid4()
        case = _case_shim(case_id=case_id)
        run_id = uuid4()
        observation_id = uuid4()
        artifact_id = uuid4()
        observation = _observation_shim(
            observation_id=observation_id, run_id=run_id
        )
        artifact = _artifact_shim(artifact_id=artifact_id, run_id=run_id)
        evidence_item = _evidence_item_shim(
            evidence_id="ext-evi:eeeeeeee",
            observation_id=observation_id,
            run_id=run_id,
            artifact_id=artifact_id,
        )
        cases, evidence, runs, results = _build_repositories(case=case)
        ext_evidence, observations, artifacts = _build_external_repositories(
            external_by_case={case_id: [evidence_item]},
            observations_by_id={observation_id: observation},
            artifacts_by_id={artifact_id: artifact},
        )
        configure(ext_evidence, observations, artifacts)

        with pytest.raises(ResearchQueryError) as exc_info:
            ResearchQueryService(
                cases,
                evidence,
                runs,
                results,
                external_evidence_repository=ext_evidence,
                observation_repository=observations,
                artifact_repository=artifacts,
            ).get_workspace(case_id)

        assert str(exc_info.value) == "research query failed"
        # Sanitized: no driver-level detail leaks.
        assert "password" not in str(exc_info.value)
        assert "secret" not in str(exc_info.value)


class TestWorkspaceExternalDiscoveryProtocolSurface:
    """The new reader protocols must expose the read methods the workspace uses."""

    def test_external_evidence_reader_protocol_exposes_list_by_case(self) -> None:
        from invest_api.application.research import ResearchExternalEvidenceReader

        assert "list_by_case" in dir(ResearchExternalEvidenceReader)

    def test_observation_reader_protocol_exposes_get_by_id(self) -> None:
        from invest_api.application.research import ExternalObservationReader

        assert "get_by_id" in dir(ExternalObservationReader)

    def test_artifact_reader_protocol_exposes_get_by_id(self) -> None:
        from invest_api.application.research import ExternalArtifactReader

        assert "get_by_id" in dir(ExternalArtifactReader)


__all__ = [
    "TestWorkspaceExternalDiscoveryHappyPath",
    "TestWorkspaceExternalDiscoveryProtocolSurface",
    "TestWorkspaceExternalDiscoverySqlAlchemyError",
    "TestWorkspaceExternalDiscoveryUnavailability",
    "TestWorkspaceHappyPath",
    "TestWorkspaceMissingCase",
    "TestWorkspaceMissingResult",
    "TestWorkspaceProtocolSurface",
    "TestWorkspaceSqlAlchemyError",
]
