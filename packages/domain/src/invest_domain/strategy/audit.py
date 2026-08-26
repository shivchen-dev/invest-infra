"""Pure-domain immutable audit record for a strategy draft."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

_HEX64 = re.compile(r"[0-9a-f]{64}")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_NIL_UUID = UUID(int=0)


class StrategyAuditVerdict(StrEnum):
    PASS = "pass"
    CHANGES_REQUIRED = "changes_required"
    REJECT = "reject"


def _uuid(value: Any, name: str) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value == _NIL_UUID:
        raise ValueError(f"{name} must not be the nil UUID")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{name} must be non-blank")
    return result


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a SHA-256 string")
    if _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _opaque_id(value: Any, name: str) -> str:
    result = _text(value, name)
    if _OPAQUE_ID.fullmatch(result) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return result


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _relative_ref(value: Any) -> str:
    ref = _text(value, "StrategyAudit.report_ref")
    if "\\" in ref:
        raise ValueError("StrategyAudit.report_ref must use a safe relative path")
    path = PurePosixPath(ref)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("StrategyAudit.report_ref must use a safe relative path")
    return ref


def _freeze_json(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} object keys must be strings")
            frozen[key] = _freeze_json(item, name)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item, name) for item in value)
    raise TypeError(f"{name} must contain only JSON-compatible values")


def _findings(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("StrategyAudit.findings must be a sequence of JSON objects")
    result = tuple(_freeze_json(item, "StrategyAudit.findings") for item in value)
    if any(not isinstance(item, Mapping) for item in result):
        raise TypeError("StrategyAudit.findings entries must be JSON objects")
    return result


def _limitations(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("StrategyAudit.limitations must be a sequence of strings")
    return tuple(_text(item, "StrategyAudit.limitations item") for item in value)


@dataclass(frozen=True, slots=True)
class StrategyAudit:
    audit_id: UUID
    draft_id: UUID
    artifact_hash: str
    agentoa_task_id: str
    auditor_agent_id: str
    verdict: StrategyAuditVerdict
    findings: tuple[Mapping[str, Any], ...]
    limitations: tuple[str, ...]
    report_ref: str
    report_hash: str
    audited_at: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_id", _uuid(self.audit_id, "StrategyAudit.audit_id"))
        object.__setattr__(self, "draft_id", _uuid(self.draft_id, "StrategyAudit.draft_id"))
        object.__setattr__(
            self, "artifact_hash", _hash(self.artifact_hash, "StrategyAudit.artifact_hash")
        )
        object.__setattr__(
            self,
            "agentoa_task_id",
            _opaque_id(self.agentoa_task_id, "StrategyAudit.agentoa_task_id"),
        )
        object.__setattr__(
            self,
            "auditor_agent_id",
            _opaque_id(self.auditor_agent_id, "StrategyAudit.auditor_agent_id"),
        )
        try:
            verdict = StrategyAuditVerdict(self.verdict)
        except (TypeError, ValueError) as exc:
            raise ValueError("StrategyAudit.verdict is invalid") from exc
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "findings", _findings(self.findings))
        object.__setattr__(self, "limitations", _limitations(self.limitations))
        object.__setattr__(self, "report_ref", _relative_ref(self.report_ref))
        object.__setattr__(
            self, "report_hash", _hash(self.report_hash, "StrategyAudit.report_hash")
        )
        object.__setattr__(self, "audited_at", _aware(self.audited_at, "StrategyAudit.audited_at"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "StrategyAudit.created_at"))

    @classmethod
    def create(
        cls,
        *,
        draft_id: UUID,
        artifact_hash: str,
        agentoa_task_id: str,
        auditor_agent_id: str,
        verdict: StrategyAuditVerdict | str,
        findings: Sequence[Mapping[str, Any]],
        limitations: Sequence[str],
        report_ref: str,
        report_hash: str,
        audited_at: datetime | None = None,
        audit_id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> StrategyAudit:
        now = clock()
        return cls(
            audit_id=audit_id_factory(),
            draft_id=draft_id,
            artifact_hash=artifact_hash,
            agentoa_task_id=agentoa_task_id,
            auditor_agent_id=auditor_agent_id,
            verdict=StrategyAuditVerdict(verdict),
            findings=tuple(findings),
            limitations=tuple(limitations),
            report_ref=report_ref,
            report_hash=report_hash,
            audited_at=audited_at if audited_at is not None else now,
            created_at=now,
        )


__all__ = ["StrategyAudit", "StrategyAuditVerdict"]
