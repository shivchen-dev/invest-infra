from __future__ import annotations

from typing import Protocol
from uuid import UUID

from invest_domain.research import EvidencePack, ResearchCase
from invest_domain.research.research_run import ResearchResult, ResearchRun
from sqlalchemy.exc import SQLAlchemyError


class ResearchCaseReader(Protocol):
    def list_recent(self, *, limit: int, offset: int) -> list[ResearchCase]: ...
    def count_all(self) -> int: ...
    def get(self, case_id: UUID) -> ResearchCase | None: ...


class ResearchEvidenceReader(Protocol):
    def list_by_case(self, case_id: UUID) -> list[EvidencePack]: ...


class ResearchRunReader(Protocol):
    def list_recent(self, *, limit: int, offset: int) -> list[ResearchRun]: ...
    def count_all(self) -> int: ...
    def get(self, run_id: UUID) -> ResearchRun | None: ...


class ResearchResultReader(Protocol):
    def get_by_run_id(self, run_id: UUID) -> ResearchResult | None: ...


class ResearchQueryError(RuntimeError):
    pass


class ResearchQueryService:
    def __init__(
        self,
        case_repository: ResearchCaseReader,
        evidence_repository: ResearchEvidenceReader,
        run_repository: ResearchRunReader,
        result_repository: ResearchResultReader,
    ) -> None:
        self._cases = case_repository
        self._evidence = evidence_repository
        self._runs = run_repository
        self._results = result_repository

    def list_cases(self, *, limit: int, offset: int) -> tuple[list[ResearchCase], int]:
        try:
            return (
                self._cases.list_recent(limit=limit, offset=offset),
                self._cases.count_all(),
            )
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_case(self, case_id: UUID) -> ResearchCase | None:
        try:
            return self._cases.get(case_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_case_evidence(self, case_id: UUID) -> list[EvidencePack] | None:
        try:
            if self._cases.get(case_id) is None:
                return None
            return self._evidence.list_by_case(case_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def list_runs(self, *, limit: int, offset: int) -> tuple[list[ResearchRun], int]:
        try:
            return (
                self._runs.list_recent(limit=limit, offset=offset),
                self._runs.count_all(),
            )
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_run(self, run_id: UUID) -> ResearchRun | None:
        try:
            return self._runs.get(run_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc

    def get_run_result(self, run_id: UUID) -> ResearchResult | None:
        try:
            if self._runs.get(run_id) is None:
                return None
            return self._results.get_by_run_id(run_id)
        except SQLAlchemyError as exc:
            raise ResearchQueryError("research query failed") from exc


__all__ = [
    "ResearchCaseReader",
    "ResearchEvidenceReader",
    "ResearchQueryError",
    "ResearchQueryService",
    "ResearchResultReader",
    "ResearchRunReader",
]
