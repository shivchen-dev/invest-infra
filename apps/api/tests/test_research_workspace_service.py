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
- the :class:`sqlalchemy.exc.SQLAlchemyError` translation to
  :class:`ResearchQueryError` for every reader call site.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from invest_api.application.research import (
    ResearchCaseWorkspaceView,
    ResearchQueryError,
    ResearchQueryService,
)
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


__all__ = [
    "TestWorkspaceHappyPath",
    "TestWorkspaceMissingCase",
    "TestWorkspaceMissingResult",
    "TestWorkspaceProtocolSurface",
    "TestWorkspaceSqlAlchemyError",
]
