"""Infrastructure-free CIA decision and immutable strategy aggregates.

``StrategyDecision`` strictly parses the human-authored approval envelope.
Controlled ingestion references and hashes live on ``StrategyVersion``.
The published version binds an artifact, its sources, an audit, and approval
metadata while allowing a single optional activation timestamp.

Both aggregates are frozen and slotted. Validation is local to their fields;
cross-aggregate binding belongs to governance. The shared error vocabulary is
used by the storage and application layers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

_HEX64 = re.compile(r"[0-9a-f]{64}")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_NIL_UUID = UUID(int=0)

DECISION_SCHEMA_VERSION: int = 1
DECISION_APPROVE: str = "approve"

_DECISION_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "draft_id",
        "artifact_hash",
        "audit_id",
        "decision",
        "decided_by",
        "decided_by_agent_id",
        "decided_at",
        "limitations",
        "statement",
    }
)


def _require_uuid(value: Any, name: str) -> UUID:
    if isinstance(value, bool) or not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID, got {type(value).__name__}")
    if value == _NIL_UUID:
        raise ValueError(f"{name} must not be the nil UUID")
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a non-blank string, got {type(value).__name__}")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be a non-blank string")
    return normalized


def _require_hash(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a 64-character lowercase hex string")
    if _HEX64.fullmatch(value) is None:
        raise ValueError(
            f"{name} must be exactly 64 lowercase hexadecimal characters, got {value!r}"
        )
    return value


def _require_opaque_id(value: Any, name: str) -> str:
    text = _require_text(value, name)
    if _OPAQUE_ID.fullmatch(text) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return text


def _require_aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _require_schema_version(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return value


def _require_hash_sequence(
    value: Any, name: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of SHA-256 strings")
    result = tuple(_require_hash(item, f"{name} item") for item in value)
    if not allow_empty and not result:
        raise ValueError(f"{name} must be a non-empty sequence of SHA-256 strings")
    return result


def _require_nonblank_text_sequence(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of non-blank strings")
    return tuple(_require_text(item, f"{name} item") for item in value)


class StrategyDecisionError(ValueError):
    """Raised when a CIA decision envelope fails local shape validation."""


class StrategyApprovalError(ValueError):
    """Raised when a CIA approval binding fails local shape validation."""


class StrategyVersionConflictError(RuntimeError):
    """Raised when a StrategyVersion conflicts with an existing record."""


class StrategyVersionNotFoundError(LookupError):
    """Raised when a StrategyVersion lookup misses."""


class StrategyVersionAlreadyActiveError(RuntimeError):
    """Raised when a StrategyVersion is already active for its strategy."""


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    """Strict CIA decision envelope.

    Decision references and hashes are controlled ingestion metadata and live
    on :class:`StrategyVersion` rather than in the CIA JSON.
    """

    schema_version: int
    draft_id: UUID
    artifact_hash: str
    audit_id: UUID
    decision: str
    decided_by: str
    decided_by_agent_id: str
    decided_at: datetime
    limitations: tuple[str, ...]
    statement: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_schema_version(self.schema_version, "StrategyDecision.schema_version"),
        )
        if self.schema_version != DECISION_SCHEMA_VERSION:
            raise StrategyDecisionError(
                f"StrategyDecision.schema_version must be {DECISION_SCHEMA_VERSION}, "
                f"got {self.schema_version}"
            )
        object.__setattr__(
            self, "draft_id", _require_uuid(self.draft_id, "StrategyDecision.draft_id")
        )
        object.__setattr__(
            self,
            "artifact_hash",
            _require_hash(self.artifact_hash, "StrategyDecision.artifact_hash"),
        )
        object.__setattr__(
            self, "audit_id", _require_uuid(self.audit_id, "StrategyDecision.audit_id")
        )
        if not isinstance(self.decision, str):
            raise StrategyDecisionError(
                f"StrategyDecision.decision must be a string, got {type(self.decision).__name__}"
            )
        if self.decision != DECISION_APPROVE:
            raise StrategyDecisionError(
                f"StrategyDecision.decision must be exactly {DECISION_APPROVE!r}, "
                f"got {self.decision!r}"
            )
        object.__setattr__(self, "decision", DECISION_APPROVE)
        object.__setattr__(
            self,
            "decided_by",
            _require_text(self.decided_by, "StrategyDecision.decided_by"),
        )
        object.__setattr__(
            self,
            "decided_by_agent_id",
            _require_opaque_id(
                self.decided_by_agent_id, "StrategyDecision.decided_by_agent_id"
            ),
        )
        object.__setattr__(
            self,
            "decided_at",
            _require_aware(self.decided_at, "StrategyDecision.decided_at"),
        )
        object.__setattr__(
            self,
            "limitations",
            _require_nonblank_text_sequence(
                self.limitations, "StrategyDecision.limitations"
            ),
        )
        object.__setattr__(
            self,
            "statement",
            _require_text(self.statement, "StrategyDecision.statement"),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> StrategyDecision:
        """Parse a mapping, rejecting unknown, missing, or invalid fields."""

        if not isinstance(payload, Mapping):
            raise StrategyDecisionError(
                "StrategyDecision JSON payload must be a mapping of string keys"
            )
        unknown = set(payload) - _DECISION_REQUIRED_FIELDS
        if unknown:
            unknown_sorted = ", ".join(sorted(unknown))
            raise StrategyDecisionError(
                f"StrategyDecision JSON payload contains unknown fields: {unknown_sorted}"
            )
        missing = _DECISION_REQUIRED_FIELDS - set(payload)
        if missing:
            missing_sorted = ", ".join(sorted(missing))
            raise StrategyDecisionError(
                f"StrategyDecision JSON payload is missing required fields: {missing_sorted}"
            )
        draft_id = payload["draft_id"]
        if isinstance(draft_id, str):
            draft_id = UUID(draft_id)
        audit_id = payload["audit_id"]
        if isinstance(audit_id, str):
            audit_id = UUID(audit_id)
        decided_at = payload["decided_at"]
        if isinstance(decided_at, str):
            decided_at = datetime.fromisoformat(decided_at)
        return cls(
            schema_version=payload["schema_version"],
            draft_id=draft_id,
            artifact_hash=payload["artifact_hash"],
            audit_id=audit_id,
            decision=payload["decision"],
            decided_by=payload["decided_by"],
            decided_by_agent_id=payload["decided_by_agent_id"],
            decided_at=decided_at,
            limitations=payload["limitations"],
            statement=payload["statement"],
        )


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    """Immutable published artifact bound to CIA approval and RAA audit."""

    strategy_id: UUID
    strategy_key: str
    version: str
    artifact_ref: str
    artifact_hash: str
    source_hashes: tuple[str, ...]
    decision_ref: str
    decision_hash: str
    decided_by_agent_id: str
    audit_id: UUID
    approved_at: datetime
    activated_at: datetime | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "strategy_id", _require_uuid(self.strategy_id, "StrategyVersion.strategy_id")
        )
        object.__setattr__(
            self,
            "strategy_key",
            _require_text(self.strategy_key, "StrategyVersion.strategy_key"),
        )
        object.__setattr__(
            self, "version", _require_text(self.version, "StrategyVersion.version")
        )
        object.__setattr__(
            self,
            "artifact_ref",
            _require_text(self.artifact_ref, "StrategyVersion.artifact_ref"),
        )
        object.__setattr__(
            self,
            "artifact_hash",
            _require_hash(self.artifact_hash, "StrategyVersion.artifact_hash"),
        )
        object.__setattr__(
            self,
            "source_hashes",
            _require_hash_sequence(
                self.source_hashes, "StrategyVersion.source_hashes", allow_empty=False
            ),
        )
        object.__setattr__(
            self,
            "decision_ref",
            _require_text(self.decision_ref, "StrategyVersion.decision_ref"),
        )
        object.__setattr__(
            self,
            "decision_hash",
            _require_hash(self.decision_hash, "StrategyVersion.decision_hash"),
        )
        object.__setattr__(
            self,
            "decided_by_agent_id",
            _require_opaque_id(
                self.decided_by_agent_id, "StrategyVersion.decided_by_agent_id"
            ),
        )
        object.__setattr__(
            self, "audit_id", _require_uuid(self.audit_id, "StrategyVersion.audit_id")
        )
        approved_at = _require_aware(self.approved_at, "StrategyVersion.approved_at")
        if self.activated_at is None:
            activated_at: datetime | None = None
        else:
            activated_at = _require_aware(self.activated_at, "StrategyVersion.activated_at")
            if activated_at < approved_at:
                raise StrategyApprovalError(
                    "StrategyVersion.activated_at must not be earlier than approved_at"
                )
        object.__setattr__(self, "approved_at", approved_at)
        object.__setattr__(self, "activated_at", activated_at)
        object.__setattr__(
            self,
            "created_at",
            _require_aware(self.created_at, "StrategyVersion.created_at"),
        )

    @classmethod
    def create(
        cls,
        *,
        strategy_key: str,
        version: str,
        artifact_ref: str,
        artifact_hash: str,
        source_hashes: Sequence[str] | Iterable[str],
        decision_ref: str,
        decision_hash: str,
        decided_by_agent_id: str,
        audit_id: UUID,
        approved_at: datetime,
        activated_at: datetime | None = None,
        strategy_id: UUID | None = None,
        created_at: datetime | None = None,
        strategy_id_factory: Callable[[], UUID] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> StrategyVersion:
        """Create a version, with optional identity and clock hooks."""

        resolved_strategy_id = (
            strategy_id
            if strategy_id is not None
            else (strategy_id_factory() if strategy_id_factory is not None else uuid4())
        )
        resolved_created_at = (
            created_at
            if created_at is not None
            else (clock() if clock is not None else datetime.now(UTC))
        )
        resolved_source_hashes = (
            source_hashes if isinstance(source_hashes, tuple) else tuple(source_hashes)
        )
        return cls(
            strategy_id=resolved_strategy_id,
            strategy_key=strategy_key,
            version=version,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            source_hashes=resolved_source_hashes,
            decision_ref=decision_ref,
            decision_hash=decision_hash,
            decided_by_agent_id=decided_by_agent_id,
            audit_id=audit_id,
            approved_at=approved_at,
            activated_at=activated_at,
            created_at=resolved_created_at,
        )


__all__ = [
    "DECISION_APPROVE",
    "DECISION_SCHEMA_VERSION",
    "StrategyApprovalError",
    "StrategyDecision",
    "StrategyDecisionError",
    "StrategyVersion",
    "StrategyVersionAlreadyActiveError",
    "StrategyVersionConflictError",
    "StrategyVersionNotFoundError",
]
