"""Application service for ExternalObservation admission decisions."""

from __future__ import annotations

from invest_domain.integration import (
    AdmissionDecision,
    AdmissionVerification,
    evaluate_admission,
)


class ObservationAdmissionService:
    """Evaluate and persist an admission decision in one caller-owned UoW."""

    def __init__(self, observation_repository) -> None:
        self._observations = observation_repository

    def decide(self, observation_id, verification: AdmissionVerification) -> AdmissionDecision:
        observation = self._observations.get_by_id(observation_id)
        if observation is None:
            raise LookupError(f"ExternalObservation {observation_id!s} not found")
        decision = evaluate_admission(observation, verification)
        updated = observation.apply_admission(decision)
        self._observations.save_admission(updated)
        return decision


__all__ = ["ObservationAdmissionService"]
