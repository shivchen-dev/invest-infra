"""Controlled command service for queueing an external ResearchRun."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase, ResearchPlaybook
from invest_domain.research.research_case import ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus

JIUWENSWARM_RUNNER_KEY = "jiuwenswarm-runner-v1"
"""Historical runner key for the retired JiuwenSwarm adapter.

Preserved as an explicit compatibility constant so callers that still
need to re-queue or replay against the retired JiuwenSwarm boundary
can pass it through :meth:`ResearchRunCommandService.queue`. Current
Stage 4D plans do not depend on it and the API default path must no
longer queue runs against this key.
"""

FAKE_RUNNER_KEY = "fake-runner-v1"
"""Deterministic runner key for the in-process :class:`FakeResearchRunner`.

The API default path uses this key so queued runs can be driven to a
terminal state without contacting the retired JiuwenSwarm gateway.
"""


class ResearchRunCommandError(RuntimeError):
    """A requested ResearchRun cannot be queued safely."""


class _CaseRepository(Protocol):
    def get(self, case_id: UUID): ...

    def save_transition(self, previous_status, transitioned_case): ...


class _EvidencePackRepository(Protocol):
    def get_by_id(self, pack_id: UUID): ...


class _ExternalEvidenceRepository(Protocol):
    def list_by_case(self, research_case_id: UUID): ...


class _ResearchRunRepository(Protocol):
    def list_by_case(self, case_id: UUID): ...

    def add(self, run: ResearchRun): ...


@dataclass(frozen=True, slots=True)
class ResearchRunCommandService:
    case_repository: _CaseRepository
    evidence_pack_repository: _EvidencePackRepository
    external_evidence_repository: _ExternalEvidenceRepository
    run_repository: _ResearchRunRepository
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def queue(
        self,
        *,
        case_id: UUID,
        evidence_pack_id: UUID,
        playbook: ResearchPlaybook,
        runner_key: str = FAKE_RUNNER_KEY,
    ) -> tuple[ResearchRun, bool]:
        case = self.case_repository.get(case_id)
        if case is None:
            raise ResearchRunCommandError("Research Case not found")
        if not isinstance(playbook, ResearchPlaybook):
            raise TypeError("playbook must be a ResearchPlaybook")
        if not isinstance(runner_key, str) or not runner_key.strip():
            raise ResearchRunCommandError("runner_key must be a non-blank string")
        if not self.external_evidence_repository.list_by_case(case_id):
            raise ResearchRunCommandError("Research Case has no admitted external evidence")

        pack = self.evidence_pack_repository.get_by_id(evidence_pack_id)
        if pack is None:
            raise ResearchRunCommandError("EvidencePack not found")
        self._validate_pack(case, pack)

        for existing in self.run_repository.list_by_case(case_id):
            if (
                existing.evidence_pack_id == evidence_pack_id
                and existing.runner_key == runner_key
                and existing.playbook_key == playbook.playbook_key
                and existing.status
                in {
                    ResearchRunStatus.QUEUED,
                    ResearchRunStatus.RUNNING,
                    ResearchRunStatus.SUCCEEDED,
                }
            ):
                return existing, True

        if case.status is ResearchCaseStatus.DRAFT:
            self.case_repository.save_transition(
                case.status,
                case.transition(ResearchCaseStatus.READY, occurred_at=self.clock()),
            )
        elif case.status is not ResearchCaseStatus.READY:
            raise ResearchRunCommandError(
                f"Research Case must be draft or ready, got {case.status.value!r}"
            )

        run = ResearchRun.create(
            case_id=case.case_id,
            evidence_pack_id=pack.pack_id,
            runner_key=runner_key,
            playbook_key=playbook.playbook_key,
        )
        return self.run_repository.add(run), False

    @staticmethod
    def _validate_pack(case: ResearchCase, pack: EvidencePack) -> None:
        if pack.pack_id is None:
            raise ResearchRunCommandError("EvidencePack must be persisted")
        if pack.case.case_id != case.case_id:
            raise ResearchRunCommandError("EvidencePack does not belong to Research Case")
        if pack.case.instrument_id != case.instrument_id:
            raise ResearchRunCommandError("EvidencePack instrument does not match Case")
        if pack.case.as_of_date != case.as_of_date:
            raise ResearchRunCommandError("EvidencePack date does not match Case")
        if pack.case.question != case.question or pack.case.horizon != case.horizon:
            raise ResearchRunCommandError("EvidencePack question does not match Case")
