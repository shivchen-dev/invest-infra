"""Immutable domain contracts for external workflow observations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from invest_domain.shared.canonical import canonical_sha256


class ProducerStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IntakeStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    REJECTED = "rejected"


class AdmissionStatus(StrEnum):
    PENDING = "pending"
    CORROBORATED = "corroborated"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    CONFLICT = "conflict"


def _uuid(value: UUID, name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")
    return value


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _optional_aware(value: datetime | None, name: str) -> None:
    if value is not None:
        _aware(value, name)


def _mapping(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _canonical_payload(value: Any) -> Any:
    """Make JSON-like producer values compatible with domain canonical hashing."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("evidence payload contains a non-finite float")
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_canonical_payload(item) for item in value)
    return value


def _hash(value: str) -> str:
    value = _text(value, "content_hash").lower()
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("content_hash must be 64 lowercase hexadecimal characters")
    return value


@dataclass(frozen=True, slots=True)
class ExternalWorkflowRun:
    run_id: UUID
    producer: str
    schema_version: str
    producer_status: ProducerStatus
    intake_status: IntakeStatus
    started_at: datetime
    finished_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _uuid(self.run_id, "run_id"))
        object.__setattr__(self, "producer", _text(self.producer, "producer"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if not isinstance(self.producer_status, ProducerStatus):
            raise TypeError("producer_status must be ProducerStatus")
        if not isinstance(self.intake_status, IntakeStatus):
            raise TypeError("intake_status must be IntakeStatus")
        _aware(self.started_at, "started_at")
        _optional_aware(self.finished_at, "finished_at")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class ExternalArtifact:
    artifact_id: UUID
    run_id: UUID
    logical_uri: str
    content_hash: str
    media_type: str
    size_bytes: int
    created_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _uuid(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "run_id", _uuid(self.run_id, "run_id"))
        object.__setattr__(self, "logical_uri", _text(self.logical_uri, "logical_uri"))
        object.__setattr__(self, "content_hash", _hash(self.content_hash))
        object.__setattr__(self, "media_type", _text(self.media_type, "media_type"))
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer")
        _aware(self.created_at, "created_at")
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class ExternalObservation:
    """External fact candidate; admission does not make it Evidence implicitly."""

    observation_id: UUID
    run_id: UUID
    observed_at: datetime
    as_of: date
    source_uri: str
    producer: str
    payload: Mapping[str, Any]
    artifact_id: UUID | None = None
    symbol: str | None = None
    instrument_id: UUID | None = None
    admission_status: AdmissionStatus = AdmissionStatus.PENDING
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in ((self.observation_id, "observation_id"), (self.run_id, "run_id")):
            _uuid(value, name)
        if self.artifact_id is not None:
            _uuid(self.artifact_id, "artifact_id")
        if self.instrument_id is not None:
            _uuid(self.instrument_id, "instrument_id")
        _aware(self.observed_at, "observed_at")
        if isinstance(self.as_of, datetime) or not isinstance(self.as_of, date):
            raise TypeError("as_of must be a date, not datetime")
        for value, name in ((self.source_uri, "source_uri"), (self.producer, "producer")):
            _text(value, name)
        if self.symbol is not None:
            _text(self.symbol, "symbol")
        if not isinstance(self.admission_status, AdmissionStatus):
            raise TypeError("admission_status must be AdmissionStatus")
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def apply_admission(self, decision: AdmissionDecision) -> ExternalObservation:
        if self.admission_status in (AdmissionStatus.ADMITTED, AdmissionStatus.REJECTED):
            raise ValueError("terminal observation admission status cannot be changed")
        if decision.observation_id != self.observation_id:
            raise ValueError("admission decision observation_id does not match observation")
        metadata = dict(self.metadata)
        metadata["admission"] = decision.to_metadata()
        return replace(self, admission_status=decision.status, metadata=metadata)


@dataclass(frozen=True, slots=True)
class ExternalEvidenceItem:
    """Immutable Research evidence item derived from an admitted observation."""

    evidence_id: str
    observation_id: UUID
    run_id: UUID
    artifact_id: UUID | None
    artifact_content_hash: str | None
    observed_at: datetime
    as_of: date
    source_uri: str
    producer: str
    payload: Mapping[str, Any]
    admission: Mapping[str, Any]
    content_hash: str

    def __post_init__(self) -> None:
        _uuid(self.observation_id, "observation_id")
        _uuid(self.run_id, "run_id")
        if self.artifact_id is not None:
            _uuid(self.artifact_id, "artifact_id")
        if self.artifact_content_hash is not None:
            _hash(self.artifact_content_hash)
        _aware(self.observed_at, "observed_at")
        if not isinstance(self.as_of, date) or isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a date, not datetime")
        _text(self.source_uri, "source_uri")
        _text(self.producer, "producer")
        object.__setattr__(self, "payload", _mapping(self.payload, "payload"))
        object.__setattr__(self, "admission", _mapping(self.admission, "admission"))
        expected = canonical_sha256(self.content_projection())
        if self.content_hash and self.content_hash != expected:
            raise ValueError("ExternalEvidenceItem.content_hash does not match content")
        object.__setattr__(self, "content_hash", expected)
        expected_id = f"ext-evi:{self.observation_id}:{expected[:16]}"
        if self.evidence_id and self.evidence_id != expected_id:
            raise ValueError("ExternalEvidenceItem.evidence_id does not match content")
        object.__setattr__(self, "evidence_id", expected_id)

    def content_projection(self) -> dict[str, Any]:
        return {
            "evidence_type": "external_observation",
            "observation_id": self.observation_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_content_hash": self.artifact_content_hash,
            "observed_at": self.observed_at,
            "as_of": self.as_of,
            "source_uri": self.source_uri,
            "producer": self.producer,
            "payload": _canonical_payload(self.payload),
            "admission": _canonical_payload(self.admission),
        }


def observation_to_evidence_item(
    observation: ExternalObservation,
    artifact: ExternalArtifact | None = None,
) -> ExternalEvidenceItem:
    """Convert only an admitted observation into immutable evidence."""
    if observation.admission_status is not AdmissionStatus.ADMITTED:
        raise ValueError(
            "only admitted observations can be converted to EvidenceItem; "
            f"got {observation.admission_status.value}"
        )
    if artifact is not None and artifact.artifact_id != observation.artifact_id:
        raise ValueError("artifact does not belong to observation")
    if observation.artifact_id is not None and artifact is None:
        raise ValueError("artifact is required to preserve artifact provenance")
    admission = observation.metadata.get("admission")
    if not isinstance(admission, Mapping):
        raise ValueError("admitted observation is missing admission audit metadata")
    return ExternalEvidenceItem(
        evidence_id="",
        observation_id=observation.observation_id,
        run_id=observation.run_id,
        artifact_id=observation.artifact_id,
        artifact_content_hash=None if artifact is None else artifact.content_hash,
        observed_at=observation.observed_at,
        as_of=observation.as_of,
        source_uri=observation.source_uri,
        producer=observation.producer,
        payload=observation.payload,
        admission=dict(admission),
        content_hash="",
    )


@dataclass(frozen=True, slots=True)
class AdmissionVerification:
    """Server-side verification facts used to decide observation admission."""

    identity_ok: bool
    freshness_ok: bool
    unit_ok: bool
    internal_cross_check_ok: bool | None
    conflict_detected: bool = False
    rules_version: str = "observation-admission/1.0"
    decided_by: str = "system"
    reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.rules_version, "rules_version")
        _text(self.decided_by, "decided_by")


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    observation_id: UUID
    status: AdmissionStatus
    reason: str
    verification: AdmissionVerification

    def __post_init__(self) -> None:
        _uuid(self.observation_id, "observation_id")
        if not isinstance(self.status, AdmissionStatus):
            raise TypeError("status must be AdmissionStatus")
        _text(self.reason, "reason")

    def to_metadata(self) -> dict[str, Any]:
        verification = self.verification
        return {
            "status": self.status.value,
            "reason": self.reason,
            "rules_version": verification.rules_version,
            "decided_by": verification.decided_by,
            "checks": {
                "identity_ok": verification.identity_ok,
                "freshness_ok": verification.freshness_ok,
                "unit_ok": verification.unit_ok,
                "internal_cross_check_ok": verification.internal_cross_check_ok,
                "conflict_detected": verification.conflict_detected,
            },
        }


def evaluate_admission(
    observation: ExternalObservation,
    verification: AdmissionVerification,
) -> AdmissionDecision:
    """Evaluate a verification result without treating it as Evidence."""
    if verification.conflict_detected:
        status = AdmissionStatus.CONFLICT
        reason = verification.reason or "conflicting verification facts"
    elif not (
        verification.identity_ok
        and verification.freshness_ok
        and verification.unit_ok
    ):
        status = AdmissionStatus.REJECTED
        reason = verification.reason or "identity, freshness, or unit check failed"
    elif verification.internal_cross_check_ok is None:
        status = AdmissionStatus.CORROBORATED
        reason = verification.reason or "external observation corroborated; internal check pending"
    elif verification.internal_cross_check_ok:
        status = AdmissionStatus.ADMITTED
        reason = verification.reason or "all admission checks passed"
    else:
        status = AdmissionStatus.REJECTED
        reason = verification.reason or "internal cross-check failed"
    return AdmissionDecision(observation.observation_id, status, reason, verification)


__all__ = [
    "AdmissionDecision", "AdmissionStatus", "AdmissionVerification",
    "ExternalArtifact", "ExternalObservation", "ExternalWorkflowRun",
    "IntakeStatus", "ProducerStatus", "evaluate_admission",
]
