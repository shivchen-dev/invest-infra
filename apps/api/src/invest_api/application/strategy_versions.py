"""Read-side service backing the public active StrategyVersion endpoint (Slice 1A).

Owns the verified read pipeline: resolve the unique active
StrategyVersion for a ``strategy_key``, fetch artifact bytes, hash
them, decode strict UTF-8 JSON, surface bounded sanitised
exceptions. Returns the public envelope plus the complete verified
strategy JSON exactly as authored inside the artifact. Its public envelope
never returns ``artifact_ref``, storage host paths, decision or audit fields, approver
identity, credentials, or database structure.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from invest_domain.strategy import StrategyVersion

from invest_api.application.strategy_drafts import StrategyArtifactReader
from invest_api.strategy_artifacts import READ_ERROR

HASH_MISMATCH: str = "strategy artifact hash does not match the registered version"
DECODE_ERROR: str = "strategy artifact is not a valid UTF-8 JSON object"


class StrategyVersionRepository(Protocol):
    def get_active(self, strategy_key: str) -> StrategyVersion | None: ...


class StrategyVersionNotFoundError(LookupError):
    """No active StrategyVersion is registered for the requested key."""

    def __init__(self, strategy_key: str) -> None:
        self.strategy_key = strategy_key
        super().__init__(
            f"StrategyVersion {strategy_key!r} has no active row"
        )


class StrategyVersionArtifactReadError(RuntimeError):
    """Sanitised: original reader exception is on ``__cause__`` only."""


class StrategyVersionArtifactHashMismatchError(RuntimeError):
    """SHA-256 of bytes disagreed with :attr:`StrategyVersion.artifact_hash`."""


class StrategyVersionArtifactDecodeError(RuntimeError):
    """Invalid UTF-8, malformed JSON, or non-object JSON value."""


@dataclass(frozen=True, slots=True)
class StrategyVersionView:
    strategy_key: str
    version: str
    active: bool
    artifact_hash: str
    strategy: Mapping[str, Any]
    approved_at: datetime
    activated_at: datetime


class StrategyVersionQueryService:
    def __init__(
        self,
        *,
        repository: StrategyVersionRepository,
        artifact_reader: StrategyArtifactReader,
    ) -> None:
        self._repository = repository
        self._artifact_reader = artifact_reader

    def get_active(self, strategy_key: str) -> StrategyVersionView:
        version = self._repository.get_active(strategy_key)
        if version is None or version.activated_at is None:
            raise StrategyVersionNotFoundError(strategy_key)
        try:
            raw_bytes = self._artifact_reader.read_bytes(version.artifact_ref)
        except Exception as exc:
            raise StrategyVersionArtifactReadError(READ_ERROR) from exc
        if hashlib.sha256(raw_bytes).hexdigest() != version.artifact_hash:
            raise StrategyVersionArtifactHashMismatchError(HASH_MISMATCH)
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise StrategyVersionArtifactDecodeError(DECODE_ERROR) from exc
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrategyVersionArtifactDecodeError(DECODE_ERROR) from exc
        if not isinstance(parsed, dict):
            raise StrategyVersionArtifactDecodeError(DECODE_ERROR)
        return StrategyVersionView(
            strategy_key=version.strategy_key,
            version=version.version,
            active=True,
            artifact_hash=version.artifact_hash,
            strategy=MappingProxyType(parsed),
            approved_at=version.approved_at,
            activated_at=version.activated_at,
        )


__all__ = [
    "StrategyVersionArtifactDecodeError",
    "StrategyVersionArtifactHashMismatchError",
    "StrategyVersionArtifactReadError",
    "StrategyVersionNotFoundError",
    "StrategyVersionQueryService",
    "StrategyVersionRepository",
    "StrategyVersionView",
]
