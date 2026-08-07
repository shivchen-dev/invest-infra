"""Mock-based unit tests for :class:`SqlAlchemyResearchResultRepository`.

Slice 2 of the PR-5.5 ``research_run_persistence_plan``. The repository
wraps the freshly-minted ``analytics.research_results`` row model and
honours the immutability / idempotency contract:

- :meth:`add` inserts a fresh row; when the same ``run_id`` is already
  bound to a row carrying the same business payload, the existing row
  is returned instead (idempotent replay). When the existing row's
  payload diverges a :class:`ResearchResultConflictError` is raised.
- :meth:`add` wraps the INSERT in a nested savepoint so the
  precheck/insert race on ``uq_research_results_run_id`` re-reads the
  canonical row and survives without poisoning the surrounding
  transaction. Other integrity violations still surface.
- Read paths mirror the application-service access patterns:
  ``get_by_id`` and ``get_by_run_id``.
- The ``risks`` and ``evidence_ids`` JSONB tuple/list roundtrip must
  preserve the original ordering on the way out.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.research.research_run import ResearchResult
from invest_storage import ResearchResultRow, SqlAlchemyResearchResultRepository
from invest_storage.repositories import (
    ResearchResultConflictError,
    _is_run_id_unique_violation,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATED_AT = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)


def make_result(
    *,
    result_id: UUID | None = None,
    run_id: UUID | None = None,
    evidence_pack_id: UUID | None = None,
    conclusion: str = "Conclusion text",
    risks: tuple[str, ...] = ("risk-a", "risk-b"),
    evidence_ids: tuple[str, ...] = ("ev-1", "ev-2"),
    report_markdown: str = "# Report",
    model_key: str = "model-x",
    model_version: str = "1.0",
    playbook_version: str = "1.0",
    adapter_version: str = "1.0",
) -> ResearchResult:
    return ResearchResult(
        result_id=result_id or uuid4(),
        run_id=run_id or uuid4(),
        evidence_pack_id=evidence_pack_id or uuid4(),
        conclusion=conclusion,
        risks=risks,
        evidence_ids=evidence_ids,
        report_markdown=report_markdown,
        model_key=model_key,
        model_version=model_version,
        playbook_version=playbook_version,
        adapter_version=adapter_version,
        created_at=CREATED_AT,
    )


def row_for(result: ResearchResult) -> ResearchResultRow:
    row = MagicMock(spec=ResearchResultRow)
    row.result_id = result.result_id
    row.run_id = result.run_id
    row.evidence_pack_id = result.evidence_pack_id
    row.conclusion = result.conclusion
    row.risks = list(result.risks)
    row.evidence_ids = list(result.evidence_ids)
    row.report_markdown = result.report_markdown
    row.model_key = result.model_key
    row.model_version = result.model_version
    row.playbook_version = result.playbook_version
    row.adapter_version = result.adapter_version
    row.created_at = result.created_at
    return row


class _RecordingSession:
    """Lightweight stand-in for a SQLAlchemy ``Session``.

    Mirrors just enough surface for
    :class:`SqlAlchemyResearchResultRepository`:
    ``add`` / ``flush`` / ``scalars(...).first()`` / ``expire_all`` and
    ``begin_nested`` (context-manager returning a no-op savepoint so the
    race tests can drive the flush to raise an :class:`IntegrityError`
    inside the savepoint). Tracks call order so tests can assert that a
    failing insert rolls back cleanly without invoking ``rollback()``
    on the outer transaction.
    """

    def __init__(
        self,
        *,
        scalars_first: list[object] | None = None,
        flush_exc: BaseException | None = None,
    ) -> None:
        self._scalars_first_queue = list(scalars_first or [None])
        self._flush_exc = flush_exc
        self.added: list[object] = []
        self.flush_calls = 0
        self.expire_all_calls = 0
        self.savepoint_log: list[str] = []
        self.outer_rollbacks = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        self.flush_calls += 1
        if self._flush_exc is not None:
            raise self._flush_exc

    def expire_all(self) -> None:
        self.expire_all_calls += 1

    def rollback(self) -> None:
        self.outer_rollbacks += 1

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    def scalars(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(self._scalars_first_queue)

    @contextmanager
    def begin_nested(self):
        self.savepoint_log.append("enter")
        try:
            yield SimpleNamespace()
        finally:
            self.savepoint_log.append("exit")


class _ScalarResult:
    def __init__(self, queue: list[object | None]) -> None:
        self._queue = queue

    def first(self) -> object | None:
        if not self._queue:
            return None
        return self._queue.pop(0)


class ResearchResultRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(spec=Session)
        self.repo = SqlAlchemyResearchResultRepository(self.session)

    def test_add_persists_row_and_returns_canonical(self) -> None:
        result = make_result()
        self.session.scalars.return_value.first.return_value = None

        returned = self.repo.add(result)

        self.assertEqual(returned, result)
        self.assertEqual(self.session.add.call_count, 1)
        self.assertEqual(self.session.flush.call_count, 1)
        persisted = self.session.add.call_args.args[0]
        self.assertEqual(persisted.result_id, result.result_id)
        self.assertEqual(persisted.run_id, result.run_id)
        self.assertEqual(list(persisted.risks), list(result.risks))
        self.assertEqual(list(persisted.evidence_ids), list(result.evidence_ids))

    def test_add_is_idempotent_for_matching_payload(self) -> None:
        result = make_result()
        existing = row_for(result)
        self.session.scalars.return_value.first.return_value = existing

        returned = self.repo.add(result)

        self.assertEqual(returned, result)
        self.session.add.assert_not_called()

    def test_add_raises_conflict_on_payload_mismatch(self) -> None:
        result = make_result()
        existing = row_for(result)
        existing.conclusion = "different conclusion"
        self.session.scalars.return_value.first.return_value = existing

        with self.assertRaises(ResearchResultConflictError):
            self.repo.add(result)
        self.session.add.assert_not_called()

    def test_add_handles_run_id_unique_race_with_matching_payload(self) -> None:
        result = make_result()
        winner = row_for(result)

        session = _RecordingSession(scalars_first=[None, winner])
        session._flush_exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                "duplicate key value violates unique constraint "
                '"uq_research_results_run_id"',
                diag=_FakeDiag("uq_research_results_run_id"),
            ),
        )
        repo = SqlAlchemyResearchResultRepository(session)

        returned = repo.add(result)

        self.assertEqual(returned, result)
        self.assertEqual(session.savepoint_log, ["enter", "exit"])
        self.assertEqual(session.expire_all_calls, 1)
        self.assertEqual(session.outer_rollbacks, 0)

    def test_add_handles_run_id_unique_race_with_divergent_payload(self) -> None:
        result = make_result()
        winner = row_for(result)
        winner.conclusion = "different conclusion"

        session = _RecordingSession(
            scalars_first=[None, winner],
        )
        session._flush_exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                "duplicate key value violates unique constraint "
                '"uq_research_results_run_id"',
                diag=_FakeDiag("uq_research_results_run_id"),
            ),
        )
        repo = SqlAlchemyResearchResultRepository(session)

        with self.assertRaises(ResearchResultConflictError):
            repo.add(result)
        self.assertEqual(session.savepoint_log, ["enter", "exit"])
        self.assertEqual(session.outer_rollbacks, 0)

    def test_add_reraises_unrelated_integrity_error(self) -> None:
        result = make_result()
        session = _RecordingSession(scalars_first=[None])
        session._flush_exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                'null value in column "run_id" violates not-null constraint',
                diag=_FakeDiag("run_id_not_null"),
            ),
        )
        repo = SqlAlchemyResearchResultRepository(session)

        with self.assertRaises(IntegrityError):
            repo.add(result)
        self.assertEqual(session.savepoint_log, ["enter", "exit"])
        self.assertEqual(session.expire_all_calls, 0)
        self.assertEqual(session.outer_rollbacks, 0)

    def test_is_run_id_unique_violation_recognises_constraint_name(self) -> None:
        exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                "duplicate key value violates unique constraint "
                '"uq_research_results_run_id"',
                diag=_FakeDiag("uq_research_results_run_id"),
            ),
        )
        self.assertTrue(_is_run_id_unique_violation(exc))

    def test_is_run_id_unique_violation_rejects_other_constraints(self) -> None:
        exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                "duplicate key value violates unique constraint "
                '"uq_research_evidence_packs_content_hash"',
                diag=_FakeDiag("uq_research_evidence_packs_content_hash"),
            ),
        )
        self.assertFalse(_is_run_id_unique_violation(exc))

    def test_is_run_id_unique_violation_rejects_non_unique_sqlstate(self) -> None:
        exc = IntegrityError(
            "stmt",
            params=None,
            orig=_FakeOrig(
                "null value in column violates not-null constraint",
                diag=_FakeDiag("ck_research_results_conclusion_nonblank"),
                sqlstate="23502",
            ),
        )
        self.assertFalse(_is_run_id_unique_violation(exc))

    def test_get_by_id_round_trips_tuple_lists(self) -> None:
        result = make_result(
            risks=("risk-c", "risk-a"),
            evidence_ids=("ev-z", "ev-a", "ev-m"),
        )
        self.session.get.return_value = row_for(result)
        returned = self.repo.get_by_id(result.result_id)
        self.assertEqual(returned, result)
        self.assertEqual(returned.risks, ("risk-c", "risk-a"))
        self.assertEqual(returned.evidence_ids, ("ev-z", "ev-a", "ev-m"))

    def test_get_by_id_returns_none_when_absent(self) -> None:
        self.session.get.return_value = None
        self.assertIsNone(self.repo.get_by_id(uuid4()))

    def test_get_by_run_id_round_trips(self) -> None:
        result = make_result()
        self.session.scalars.return_value.first.return_value = row_for(result)
        returned = self.repo.get_by_run_id(result.run_id)
        self.assertEqual(returned, result)

    def test_get_by_run_id_returns_none_when_absent(self) -> None:
        self.session.scalars.return_value.first.return_value = None
        self.assertIsNone(self.repo.get_by_run_id(uuid4()))


class _FakeDiag:
    def __init__(self, constraint_name: str | None = None) -> None:
        self.constraint_name = constraint_name


class _FakeOrig:
    def __init__(
        self,
        message: str,
        *,
        diag: _FakeDiag | None = None,
        sqlstate: str | None = "23505",
    ) -> None:
        self.sqlstate = sqlstate
        self.pgcode = sqlstate
        self.diag = diag
        self._message = message

    def __str__(self) -> str:
        return self._message


if __name__ == "__main__":
    unittest.main()
