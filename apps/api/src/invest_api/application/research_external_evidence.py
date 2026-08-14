from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from invest_domain.integration import ExternalEvidenceItem, observation_to_evidence_item


class ExternalEvidenceLinkError(RuntimeError):
    """A requested external observation could not be linked to a Research Case."""


class _CaseReader(Protocol):
    def get(self, case_id: UUID): ...


class _ObservationReader(Protocol):
    def get_by_id(self, observation_id: UUID): ...


class _ArtifactReader(Protocol):
    def get_by_id(self, artifact_id: UUID): ...


class _EvidenceWriter(Protocol):
    def add(self, research_case_id: UUID, item: ExternalEvidenceItem) -> ExternalEvidenceItem: ...


@dataclass(frozen=True, slots=True)
class ResearchExternalEvidenceService:
    case_reader: _CaseReader
    observation_reader: _ObservationReader
    artifact_reader: _ArtifactReader
    evidence_writer: _EvidenceWriter

    def link(self, *, case_id: UUID, observation_id: UUID) -> ExternalEvidenceItem:
        case = self.case_reader.get(case_id)
        if case is None:
            raise ExternalEvidenceLinkError("Research Case not found")
        observation = self.observation_reader.get_by_id(observation_id)
        if observation is None:
            raise ExternalEvidenceLinkError("External Observation not found")
        if (
            observation.instrument_id is not None
            and observation.instrument_id != case.instrument_id.value
        ):
            raise ExternalEvidenceLinkError("Observation instrument does not match Research Case")
        artifact = None
        if observation.artifact_id is not None:
            artifact = self.artifact_reader.get_by_id(observation.artifact_id)
            if artifact is None:
                raise ExternalEvidenceLinkError("Observation Artifact not found")
        try:
            item = observation_to_evidence_item(observation, artifact)
        except ValueError as exc:
            raise ExternalEvidenceLinkError(str(exc)) from exc
        return self.evidence_writer.add(case_id, item)
