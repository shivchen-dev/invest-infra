"""Command-side application service for Observation Admission."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from invest_domain.integration import AdmissionVerification, ExternalObservation, evaluate_admission


class ObservationRepository(Protocol):
    def get_by_id(self, observation_id: UUID): ...
    def save_admission(self, observation: ExternalObservation): ...


@dataclass(frozen=True, slots=True)
class AdmissionCommandResult:
    observation: ExternalObservation
    idempotent: bool


class ObservationAdmissionCommandService:
    def __init__(self, repository: ObservationRepository) -> None:
        self._repository = repository

    def decide(
        self,
        observation_id: UUID,
        verification: AdmissionVerification,
        *,
        idempotency_key: str,
    ) -> AdmissionCommandResult:
        observation = self._repository.get_by_id(observation_id)
        if observation is None:
            raise LookupError("ExternalObservation not found")
        previous_key = observation.metadata.get("admission", {}).get("idempotency_key")
        if previous_key == idempotency_key:
            return AdmissionCommandResult(observation, True)
        if observation.admission_status.value != "pending":
            raise ValueError("observation admission has already been decided")
        decision = evaluate_admission(observation, verification)
        updated = observation.apply_admission(decision)
        metadata = dict(updated.metadata)
        admission = dict(metadata["admission"])
        admission["idempotency_key"] = idempotency_key
        metadata["admission"] = admission
        updated = replace(updated, metadata=metadata)
        return AdmissionCommandResult(self._repository.save_admission(updated), False)


__all__ = ["AdmissionCommandResult", "ObservationAdmissionCommandService"]
