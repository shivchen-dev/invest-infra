"""Command-side application service for Observation Admission.

This module is the single place where the server-side verification
facts are derived for an admission command. The HTTP request schema
deliberately does NOT expose any verification boolean — see
:mod:`invest_api.schemas.admission`. All four verification facts are
computed here from the loaded
:class:`invest_domain.integration.ExternalObservation`, an injectable
business-date clock, and the repository's recent observations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol
from uuid import UUID

from invest_domain.integration import (
    AdmissionStatus,
    AdmissionVerification,
    ExternalObservation,
    evaluate_admission,
)
from invest_domain.shared.canonical import canonical_sha256

from invest_api.clock import market_today

SERVER_DECISION_PRINCIPAL: str = "system"
SERVER_RULES_VERSION: str = "observation-admission/1.0"
FRESHNESS_WINDOW_DAYS: int = 7


class ObservationRepository(Protocol):
    def get_by_id(self, observation_id: UUID): ...
    def list_recent(
        self,
        *,
        status: AdmissionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ): ...
    def save_admission(self, observation: ExternalObservation): ...


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _payload_hash(payload) -> str:
    return canonical_sha256(dict(payload))


def _identity_ok(observation: ExternalObservation) -> bool:
    if observation.instrument_id is None:
        return False
    return _non_blank(observation.symbol)


def _freshness_ok(as_of: date, today: date) -> bool:
    if as_of > today:
        return False
    return (today - as_of).days <= FRESHNESS_WINDOW_DAYS


def _unit_ok(payload: Mapping[str, object]) -> bool:
    return _non_blank(payload.get("unit")) and _non_blank(payload.get("definition"))


def _resolve_internal_check(
    observation: ExternalObservation,
    peers: Iterable[ExternalObservation],
) -> tuple[bool | None, bool]:
    """Return ``(internal_cross_check_ok, conflict_detected)``.

    Scans every recent peer sharing the same ``instrument_id`` and
    ``as_of`` and lets *conflict* win over corroboration:

    * any peer with a different canonical payload → ``(False, True)``
    * otherwise any peer with the same canonical payload → ``(True, False)``
    * no peer matches → ``(None, False)``
    """

    target_hash = _payload_hash(observation.payload)
    saw_identical = False
    for peer in peers:
        if peer.observation_id == observation.observation_id:
            continue
        if peer.instrument_id != observation.instrument_id:
            continue
        if peer.as_of != observation.as_of:
            continue
        if _payload_hash(peer.payload) != target_hash:
            return False, True
        saw_identical = True
    if saw_identical:
        return True, False
    return None, False


def _build_verification(
    observation: ExternalObservation,
    *,
    today: date,
    peers: Iterable[ExternalObservation],
) -> AdmissionVerification:
    internal_cross_check_ok, conflict_detected = _resolve_internal_check(observation, peers)
    return AdmissionVerification(
        identity_ok=_identity_ok(observation),
        freshness_ok=_freshness_ok(observation.as_of, today),
        unit_ok=_unit_ok(observation.payload),
        internal_cross_check_ok=internal_cross_check_ok,
        conflict_detected=conflict_detected,
        rules_version=SERVER_RULES_VERSION,
        decided_by=SERVER_DECISION_PRINCIPAL,
        reason=None,
    )


@dataclass(frozen=True, slots=True)
class AdmissionCommandResult:
    observation: ExternalObservation
    idempotent: bool


class ObservationAdmissionCommandService:
    """Application service that decides admission for a single observation."""

    def __init__(
        self,
        repository: ObservationRepository,
        *,
        clock: Callable[[], date] = market_today,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def decide(
        self,
        observation_id: UUID,
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
        peers = list(self._repository.list_recent())
        verification = _build_verification(observation, today=self._clock(), peers=peers)
        decision = evaluate_admission(observation, verification)
        updated = observation.apply_admission(decision)
        metadata = dict(updated.metadata)
        admission = dict(metadata["admission"])
        admission["idempotency_key"] = idempotency_key
        metadata["admission"] = admission
        updated = replace(updated, metadata=metadata)
        return AdmissionCommandResult(self._repository.save_admission(updated), False)


__all__ = [
    "AdmissionCommandResult",
    "FRESHNESS_WINDOW_DAYS",
    "ObservationAdmissionCommandService",
    "SERVER_DECISION_PRINCIPAL",
    "SERVER_RULES_VERSION",
]
