"""Controlled handoff from admitted external evidence to Research orchestration.

Stage 4D deliberately keeps the WorkBuddy payload outside the formal
``EvidencePack`` contract.  This service is the narrow seam between the two:
it only creates a legacy-keyed ``ResearchRun`` when the case already has an
immutable, complete EvidencePack and at least one admitted external evidence
item linked to it. The JiuwenSwarm key is retained for data compatibility and
does not identify a current production dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase, ResearchPlaybook
from invest_domain.research.research_case import ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_storage.unit_of_work import UnitOfWork

from invest_pipeline.research_orchestration_service import (
    ResearchOrchestrationOutcome,
    ResearchOrchestrationService,
)

__all__ = [
    "ExternalResearchHandoffInputError",
    "ExternalResearchHandoffService",
    "JIUWENSWARM_RUNNER_KEY",
]


JIUWENSWARM_RUNNER_KEY = "jiuwenswarm-runner-v1"
ClockFactory = Callable[[], datetime]
UnitOfWorkFactory = Callable[[], UnitOfWork]


class ExternalResearchHandoffInputError(ValueError):
    """Raised when an external observation cannot enter Research safely."""


@dataclass(frozen=True, slots=True)
class ExternalResearchHandoffService:
    """Queue and optionally execute one external-evidence research attempt.

    ``queue`` owns only the short database transaction.  ``execute`` commits
    that handoff before calling the existing orchestration service, preserving
    the long-running external gateway boundary already established by Slice 3.
    """

    uow_factory: UnitOfWorkFactory
    clock: ClockFactory

    def queue(
        self,
        *,
        case_id: UUID,
        evidence_pack_id: UUID,
        playbook: ResearchPlaybook,
        runner_key: str = JIUWENSWARM_RUNNER_KEY,
    ) -> ResearchRun:
        if not isinstance(case_id, UUID) or not isinstance(evidence_pack_id, UUID):
            raise TypeError("case_id and evidence_pack_id must be UUID instances")
        if not isinstance(playbook, ResearchPlaybook):
            raise TypeError("playbook must be a ResearchPlaybook")
        if runner_key != JIUWENSWARM_RUNNER_KEY:
            raise ExternalResearchHandoffInputError(
                f"unsupported external research runner {runner_key!r}; "
                f"expected {JIUWENSWARM_RUNNER_KEY!r}"
            )

        with self.uow_factory() as uow:
            case = uow.research_cases.get(case_id)
            if case is None:
                raise ExternalResearchHandoffInputError(f"ResearchCase {case_id!s} was not found")

            linked_external_evidence = uow.research_external_evidence.list_by_case(case_id)
            if not linked_external_evidence:
                raise ExternalResearchHandoffInputError(
                    f"ResearchCase {case_id!s} has no admitted external evidence"
                )

            pack = uow.research_evidence_packs.get_by_id(evidence_pack_id)
            if pack is None:
                raise ExternalResearchHandoffInputError(
                    f"EvidencePack {evidence_pack_id!s} was not found"
                )
            self._validate_pack(case, pack)

            for existing in uow.research_runs.list_by_case(case_id):
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
                    return existing

            if case.status is ResearchCaseStatus.DRAFT:
                case = uow.research_cases.save_transition(
                    case.status,
                    case.transition(
                        ResearchCaseStatus.READY,
                        occurred_at=self.clock(),
                    ),
                )
            elif case.status is not ResearchCaseStatus.READY:
                raise ExternalResearchHandoffInputError(
                    f"ResearchCase {case_id!s} must be draft or ready, got {case.status.value!r}"
                )

            run = ResearchRun.create(
                case_id=case.case_id,
                evidence_pack_id=pack.pack_id,
                runner_key=runner_key,
                playbook_key=playbook.playbook_key,
            )
            saved = uow.research_runs.add(run)
            uow.commit()
            return saved

    def execute(
        self,
        *,
        case_id: UUID,
        evidence_pack_id: UUID,
        playbook: ResearchPlaybook,
        orchestration: ResearchOrchestrationService,
        runner_key: str = JIUWENSWARM_RUNNER_KEY,
    ) -> ResearchOrchestrationOutcome:
        """Queue a validated run, then invoke the existing Slice 3 runner."""

        run = self.queue(
            case_id=case_id,
            evidence_pack_id=evidence_pack_id,
            playbook=playbook,
            runner_key=runner_key,
        )
        return orchestration.execute(run.run_id)

    @staticmethod
    def _validate_pack(case: ResearchCase, pack: EvidencePack) -> None:
        if pack.pack_id is None:
            raise ExternalResearchHandoffInputError(
                "EvidencePack must be persisted before Research handoff"
            )
        if pack.case.case_id != case.case_id:
            raise ExternalResearchHandoffInputError(
                f"EvidencePack {pack.pack_id!s} does not belong to ResearchCase {case.case_id!s}"
            )
        if pack.case.instrument_id != case.instrument_id:
            raise ExternalResearchHandoffInputError(
                "EvidencePack instrument_id does not match ResearchCase"
            )
        if pack.case.as_of_date != case.as_of_date:
            raise ExternalResearchHandoffInputError(
                "EvidencePack as_of_date does not match ResearchCase"
            )
        if pack.case.question != case.question or pack.case.horizon != case.horizon:
            raise ExternalResearchHandoffInputError(
                "EvidencePack question/horizon does not match ResearchCase"
            )
