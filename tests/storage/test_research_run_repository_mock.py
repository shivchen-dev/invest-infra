"""Mock-based unit tests for :class:`SqlAlchemyResearchRunRepository`.

Slice 2 of the PR-5.5 ``research_run_persistence_plan``. The repository
wraps the freshly-minted ``analytics.research_runs`` row model and owns
the lifecycle round-trip; the database CHECK constraints and unique
indexes are exercised separately by the integration suite. This file
exercises the SQLAlchemy adapter with a fake ``Session`` so the unit
tests stay fast and deterministic, mirroring the pattern used by
``tests/storage/test_research_context_pack_repository_mock.py`` and
the existing ``SqlAlchemyResearchCaseRepository`` mock tests.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_storage import ResearchRunRow, SqlAlchemyResearchRunRepository
from invest_storage.repositories import ResearchRunTransitionError
from sqlalchemy.orm import Session

STARTED_AT = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _queued(*, case_id: UUID | None = None, run_id: UUID | None = None) -> ResearchRun:
    return ResearchRun(
        run_id=run_id or uuid4(),
        case_id=case_id or uuid4(),
        evidence_pack_id=uuid4(),
        runner_key="runner-a",
        playbook_key="playbook-v1",
        status=ResearchRunStatus.QUEUED,
        attempt=1,
    )


def row_for(
    run: ResearchRun,
    *,
    external_request_id: str | None = None,
    external_session_id: str | None = None,
) -> ResearchRunRow:
    row = MagicMock(spec=ResearchRunRow)
    row.run_id = run.run_id
    row.case_id = run.case_id
    row.evidence_pack_id = run.evidence_pack_id
    row.runner_key = run.runner_key
    row.playbook_key = run.playbook_key
    row.status = run.status.value
    row.attempt = run.attempt
    row.started_at = run.started_at
    row.finished_at = run.finished_at
    row.error_summary = run.error_summary
    row.external_request_id = external_request_id
    row.external_session_id = external_session_id
    return row


class ResearchRunRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock(spec=Session)
        self.repo = SqlAlchemyResearchRunRepository(self.session)

    def test_add_persists_row_and_returns_canonical(self) -> None:
        run = _queued()

        result = self.repo.add(run)

        self.assertEqual(result, run)
        self.assertEqual(self.session.add.call_count, 1)
        self.assertEqual(self.session.flush.call_count, 1)
        persisted = self.session.add.call_args.args[0]
        self.assertEqual(persisted.run_id, run.run_id)
        self.assertEqual(persisted.status, run.status.value)
        self.assertEqual(persisted.attempt, 1)

    def test_get_returns_none_when_absent(self) -> None:
        self.session.get.return_value = None
        self.assertIsNone(self.repo.get(uuid4()))

    def test_get_round_trips_row(self) -> None:
        run = _queued()
        self.session.get.return_value = row_for(run)
        result = self.repo.get(run.run_id)
        self.assertEqual(result, run)

    def test_list_by_case_orders_deterministically(self) -> None:
        case_id = uuid4()
        a = _queued(case_id=case_id)
        b = _queued(case_id=case_id)
        rows = [row_for(b), row_for(a)]
        self.session.scalars.return_value.all.return_value = rows
        result = self.repo.list_by_case(case_id)
        self.assertEqual(result, [b, a])

    def test_save_transition_succeeds_when_previous_status_matches(self) -> None:
        queued = _queued()
        running = queued.start(occurred_at=STARTED_AT)
        pre = row_for(queued)
        post = row_for(running)
        self.session.get.side_effect = [pre, post]
        self.session.execute.return_value.rowcount = 1

        result = self.repo.save_transition(
            ResearchRunStatus.QUEUED,
            running,
        )

        self.assertEqual(result, running)
        statement = self.session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertEqual(compiled.params.get("status"), "running")
        self.assertEqual(self.session.flush.call_count, 1)

    def test_save_transition_raises_when_status_drifted(self) -> None:
        queued = _queued()
        running = queued.start(occurred_at=STARTED_AT)
        self.session.get.return_value = row_for(running)
        self.session.execute.return_value.rowcount = 0

        with self.assertRaises(ResearchRunTransitionError):
            self.repo.save_transition(ResearchRunStatus.QUEUED, running)

    def test_save_transition_raises_when_row_missing(self) -> None:
        queued = _queued()
        running = queued.start(occurred_at=STARTED_AT)
        self.session.get.return_value = None

        with self.assertRaises(LookupError):
            self.repo.save_transition(ResearchRunStatus.QUEUED, running)

    def test_bind_external_identity_rejects_blank_values(self) -> None:
        run = _queued()
        self.session.get.return_value = row_for(run)
        with self.assertRaises(ValueError):
            self.repo.bind_external_identity(
                run.run_id,
                external_request_id="",
                external_session_id="sess-1",
            )
        with self.assertRaises(ValueError):
            self.repo.bind_external_identity(
                run.run_id,
                external_request_id="req-1",
                external_session_id="   ",
            )

    def test_bind_external_identity_rejects_neither_id(self) -> None:
        run = _queued()
        self.session.get.return_value = row_for(run)

        with self.assertRaises(ValueError):
            self.repo.bind_external_identity(run.run_id)
        self.session.execute.assert_not_called()

    def test_bind_external_identity_trims_supplied_ids(self) -> None:
        run = _queued()
        row_before = row_for(run)
        updated = row_for(run, external_request_id="req-42", external_session_id="sess-42")
        self.session.get.side_effect = [row_before, updated]
        self.session.execute.return_value.rowcount = 1

        self.repo.bind_external_identity(
            run.run_id,
            external_request_id="  req-42  ",
            external_session_id="\tsess-42\n",
        )

        statement = self.session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertEqual(compiled.params.get("external_request_id"), "req-42")
        self.assertEqual(compiled.params.get("external_session_id"), "sess-42")

    def test_bind_external_identity_preserves_unbound_field(self) -> None:
        run = _queued()
        row_before = row_for(run, external_request_id="req-existing")
        updated = row_for(run, external_request_id="req-existing", external_session_id="sess-42")
        self.session.get.side_effect = [row_before, updated]
        self.session.execute.return_value.rowcount = 1

        self.repo.bind_external_identity(
            run.run_id,
            external_session_id="  sess-42  ",
        )

        statement = self.session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertEqual(compiled.params.get("external_session_id"), "sess-42")
        self.assertNotIn("external_request_id", compiled.params)

    def test_bind_external_identity_persists_nonblank_values(self) -> None:
        run = _queued()
        self.session.get.return_value = row_for(run)
        self.session.execute.return_value.rowcount = 1

        result = self.repo.bind_external_identity(
            run.run_id,
            external_request_id="req-42",
            external_session_id="sess-42",
        )

        self.assertEqual(result.run_id, run.run_id)
        statement = self.session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertEqual(compiled.params.get("external_request_id"), "req-42")
        self.assertEqual(compiled.params.get("external_session_id"), "sess-42")

    def test_lookup_by_external_session_id_round_trip(self) -> None:
        run = _queued()
        stored = row_for(
            run,
            external_request_id="req-1",
            external_session_id="sess-1",
        )
        self.session.scalars.return_value.first.return_value = stored
        result = self.repo.lookup_by_external_session_id("sess-1")
        self.assertEqual(result, run)

    def test_lookup_by_external_session_id_returns_none_when_absent(self) -> None:
        self.session.scalars.return_value.first.return_value = None
        self.assertIsNone(self.repo.lookup_by_external_session_id("nope"))


if __name__ == "__main__":
    unittest.main()
