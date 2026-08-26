"""Pure-domain tracer for one pending strategy registration.

This module is intentionally infrastructure-free. It introduces the
:class:`SourceRef` and :class:`StrategyDraft` aggregates from Slice 0 of
``docs/plan/invest-infra-candidate-strategies-mvp-plan-v1.0.md``:

- ``StrategyDraft`` is the immutable envelope of a pending strategy
  registration: stable identity, target key/version, immutable
  ``strategy.json`` reference and SHA-256, original source-material
  references, deterministic validation result, and registration
  timestamp.
- ``SourceRef`` captures one upstream business-material reference and its
  SHA-256.

Both objects are frozen and slotted. ``StrategyDraft.create`` exposes
``draft_id_factory`` and ``clock`` hooks so tests can register drafts
deterministically without monkey-patching module-level state.

No storage, migration, API, CLI, StrategyAudit, StrategyVersion,
AgentOA, extraction, or source file machinery is imported here; the
tracer only depends on the Python standard library and the shared
domain types already in use across ``invest_domain``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

_HEX64 = re.compile(r"[0-9a-f]{64}")
_NIL_UUID = UUID(int=0)


def _require_uuid(value: Any, name: str) -> UUID:
    if not isinstance(value, UUID) or isinstance(value, bool):
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


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a 64-character lowercase hex string")
    if _HEX64.fullmatch(value) is None:
        raise ValueError(
            f"{name} must be exactly 64 lowercase hexadecimal characters, got {value!r}"
        )
    return value


def _require_aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _require_source_refs(value: Any, name: str) -> tuple[SourceRef, ...]:
    if not isinstance(value, tuple):
        raise TypeError(
            f"{name} must be a tuple of SourceRef, got {type(value).__name__}"
        )
    if not value:
        raise ValueError(f"{name} must be a non-empty tuple of SourceRef")
    for index, item in enumerate(value):
        if not isinstance(item, SourceRef):
            raise TypeError(
                f"{name}[{index}] must be a SourceRef, got {type(item).__name__}"
            )
    return value


def _freeze_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{name} must be a Mapping[str, Any], got {type(value).__name__}"
        )
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Immutable reference to one original business material.

    The reference is the canonical locator of an upstream strategy
    source document (article URL, archive path, OCR snapshot, etc.);
    ``content_hash`` is the lowercase SHA-256 of the referenced
    content and is used by the system to verify the draft and audit
    record point at the same source bytes.
    """

    ref: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", _require_text(self.ref, "SourceRef.ref"))
        object.__setattr__(
            self, "content_hash", _require_sha256(self.content_hash, "SourceRef.content_hash")
        )


@dataclass(frozen=True, slots=True)
class StrategyDraft:
    """Immutable envelope for one pending strategy registration.

    The draft is the only mutable-seeming stage of a strategy's
    lifecycle: once it is published as a :class:`StrategyVersion` the
    business content freezes. The aggregate therefore rejects any
    in-place mutation at the dataclass level and stores every
    field as an immutable value (frozen slots, immutable tuple,
    ``MappingProxyType``).
    """

    draft_id: UUID
    strategy_key: str
    proposed_version: str
    artifact_ref: str
    artifact_hash: str
    source_refs: tuple[SourceRef, ...]
    validation_result: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "draft_id", _require_uuid(self.draft_id, "StrategyDraft.draft_id"))
        object.__setattr__(
            self,
            "strategy_key",
            _require_text(self.strategy_key, "StrategyDraft.strategy_key"),
        )
        object.__setattr__(
            self,
            "proposed_version",
            _require_text(self.proposed_version, "StrategyDraft.proposed_version"),
        )
        object.__setattr__(
            self,
            "artifact_ref",
            _require_text(self.artifact_ref, "StrategyDraft.artifact_ref"),
        )
        object.__setattr__(
            self,
            "artifact_hash",
            _require_sha256(self.artifact_hash, "StrategyDraft.artifact_hash"),
        )
        object.__setattr__(
            self,
            "source_refs",
            _require_source_refs(self.source_refs, "StrategyDraft.source_refs"),
        )
        object.__setattr__(
            self,
            "validation_result",
            _freeze_mapping(self.validation_result, "StrategyDraft.validation_result"),
        )
        object.__setattr__(
            self,
            "created_at",
            _require_aware(self.created_at, "StrategyDraft.created_at"),
        )

    @classmethod
    def create(
        cls,
        *,
        strategy_key: str,
        proposed_version: str,
        artifact_ref: str,
        artifact_hash: str,
        source_refs: SourceRef | Iterable[SourceRef],
        validation_result: Mapping[str, Any],
        draft_id: UUID | None = None,
        created_at: datetime | None = None,
        draft_id_factory: Callable[[], UUID] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> StrategyDraft:
        """Return a fresh :class:`StrategyDraft` with deterministic hooks.

        ``draft_id_factory`` and ``clock`` are injected so tests can
        pin the identity and registration timestamp without monkey
        patching module state. When left as ``None`` the factory
        defaults are ``uuid.uuid4`` and ``datetime.now(UTC)``.
        """

        resolved_draft_id = (
            draft_id
            if draft_id is not None
            else (draft_id_factory() if draft_id_factory is not None else uuid4())
        )
        resolved_created_at = (
            created_at
            if created_at is not None
            else (clock() if clock is not None else datetime.now(UTC))
        )
        resolved_source_refs = (
            source_refs if isinstance(source_refs, tuple) else tuple(source_refs)
        )
        return cls(
            draft_id=resolved_draft_id,
            strategy_key=strategy_key,
            proposed_version=proposed_version,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            source_refs=resolved_source_refs,
            validation_result=validation_result,
            created_at=resolved_created_at,
        )


__all__ = ["SourceRef", "StrategyDraft"]