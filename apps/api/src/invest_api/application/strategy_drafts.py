"""Read-side service behind ``GET /api/v1/strategy-drafts/{draft_id}`` (Slice 0).

Owns the verified read pipeline: resolve draft, fetch bytes, hash
them, decode JSON, surface bounded sanitised exceptions. Never
returns unverified content or the ``artifact_ref``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from invest_domain.strategy import SourceRef, StrategyAudit, StrategyDraft

READ_ERROR: str = "strategy artifact could not be read"
HASH_MISMATCH: str = "strategy artifact hash does not match the registered draft"
DECODE_ERROR: str = "strategy artifact is not a valid UTF-8 JSON object"
_INTERNAL_PATH_KEYS = frozenset(
    {"artifact_ref", "host_path", "local_path", "task_source", "workbuddy_path"}
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_PATH_REDACTION = "[internal path redacted]"


def _is_absolute_host_path(value: str) -> bool:
    return (
        value.startswith("file://")
        or value.startswith("\\\\")
        or (value.startswith("/") and not value.startswith("//"))
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
    )


def _sanitize_public_value(value: Any) -> Any:
    """Copy JSON data while removing internal path fields and values."""
    if isinstance(value, dict):
        return {
            key: _sanitize_public_value(item)
            for key, item in value.items()
            if key not in _INTERNAL_PATH_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, str) and _is_absolute_host_path(value):
        return _PATH_REDACTION
    return value


class StrategyDraftRepository(Protocol):
    def get_by_id(self, draft_id: UUID) -> StrategyDraft | None: ...


class StrategyAuditRepository(Protocol):
    def list_by_draft(self, draft_id: UUID) -> list[StrategyAudit]: ...


class StrategyArtifactReader(Protocol):
    def read_bytes(self, artifact_ref: str) -> bytes: ...


class StrategyDraftNotFoundError(LookupError):
    def __init__(self, draft_id: UUID) -> None:
        self.draft_id = draft_id
        super().__init__(f"StrategyDraft {draft_id} not found")


class StrategyDraftArtifactReadError(RuntimeError):
    """Sanitised: original reader exception is on ``__cause__`` only."""


class StrategyDraftArtifactHashMismatchError(RuntimeError):
    """SHA-256 of bytes disagreed with :attr:`StrategyDraft.artifact_hash`."""


class StrategyDraftArtifactDecodeError(RuntimeError):
    """Invalid UTF-8, malformed JSON, or non-object JSON value."""


@dataclass(frozen=True, slots=True)
class StrategyDraftAuditSummary:
    audit_id: UUID
    artifact_hash: str
    verdict: str
    audited_at: datetime


@dataclass(frozen=True, slots=True)
class StrategyDraftView:
    draft_id: UUID
    strategy_key: str
    proposed_version: str
    artifact_hash: str
    strategy: Mapping[str, Any]
    source_refs: tuple[SourceRef, ...]
    validation_result: Mapping[str, Any]
    created_at: datetime
    audit_summaries: tuple[StrategyDraftAuditSummary, ...] = field(default_factory=tuple)


class StrategyDraftQueryService:
    def __init__(
        self,
        *,
        repository: StrategyDraftRepository,
        audit_repository: StrategyAuditRepository,
        artifact_reader: StrategyArtifactReader,
    ) -> None:
        self._repository = repository
        self._audit_repository = audit_repository
        self._artifact_reader = artifact_reader

    def get_draft(self, draft_id: UUID) -> StrategyDraftView:
        draft = self._repository.get_by_id(draft_id)
        if draft is None:
            raise StrategyDraftNotFoundError(draft_id)
        try:
            raw_bytes = self._artifact_reader.read_bytes(draft.artifact_ref)
        except Exception as exc:
            raise StrategyDraftArtifactReadError(READ_ERROR) from exc
        if hashlib.sha256(raw_bytes).hexdigest() != draft.artifact_hash:
            raise StrategyDraftArtifactHashMismatchError(HASH_MISMATCH)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrategyDraftArtifactDecodeError(DECODE_ERROR) from exc
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrategyDraftArtifactDecodeError(DECODE_ERROR) from exc
        if not isinstance(parsed, dict):
            raise StrategyDraftArtifactDecodeError(DECODE_ERROR)
        return StrategyDraftView(
            draft_id=draft.draft_id,
            strategy_key=draft.strategy_key,
            proposed_version=draft.proposed_version,
            artifact_hash=draft.artifact_hash,
            strategy=MappingProxyType(_sanitize_public_value(parsed)),
            source_refs=draft.source_refs,
            validation_result=MappingProxyType(
                _sanitize_public_value(dict(draft.validation_result))
            ),
            created_at=draft.created_at,
            audit_summaries=tuple(
                StrategyDraftAuditSummary(
                    audit_id=audit.audit_id,
                    artifact_hash=audit.artifact_hash,
                    verdict=audit.verdict.value,
                    audited_at=audit.audited_at,
                )
                for audit in self._audit_repository.list_by_draft(draft_id)
            ),
        )


__all__ = [
    "StrategyArtifactReader",
    "StrategyAuditRepository",
    "StrategyDraftArtifactDecodeError",
    "StrategyDraftArtifactHashMismatchError",
    "StrategyDraftArtifactReadError",
    "StrategyDraftAuditSummary",
    "StrategyDraftNotFoundError",
    "StrategyDraftQueryService",
    "StrategyDraftRepository",
    "StrategyDraftView",
]
