"""JiuwenSwarm codec DTOs and validation (PR-6 Slice 1).

This module owns the wire-level dataclasses that flow between the
adapter and the gateway transport:

- :class:`JiuwenSwarmGatewayRequest` — versioned request envelope that
  pins the case / run / pack identity trio and forwards the
  playbook-driven whitelist of evidence IDs together with the factor
  values, source references, and case question the gateway needs to
  ground every citation. No workspace path, no credentials, and no
  runtime lineage metadata (``pipeline_run_id``,
  ``e2a_request_id``, ``e2a_session_id``, ``generated_at``) — those
  fields belong to the ingestion pipeline and must not be echoed back
  to the domain completion gate.
- :class:`JiuwenSwarmAcceptance` — three-valued enum used to classify
  the gateway's response so the orchestrator can drive retry / fail
  policies deterministically.
- :class:`JiuwenSwarmCompletion` — the validated shape the result
  mapper consumes. Construction is the only path that may raise
  :class:`JiuwenSwarmMalformedResultError`; once built, the dataclass
  is immutable and safe to hand to the domain.

The codec is intentionally a pure stdlib module: no networking, no
JSON library requirement, no logging. Validation is enforced on the
constructor (``__post_init__``) so a misuse is detected as early as
possible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from invest_domain import canonical_json

from invest_pipeline.adapters.jiuwenswarm.errors import (
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmSchemaError,
)

JIUWENSWARM_SCHEMA_VERSION = "1.0.0"
_RUNNER_KEY = "jiuwenswarm-runner-v1"


def _freeze_payload(value: Any) -> Any:
    """Recursively freeze ``value`` into a ``MappingProxyType`` + tuple tree.

    The request envelope exposes the wire payload to loggers and
    audit pipelines; freezing prevents a downstream consumer from
    mutating a shared mapping and silently drifting the canonical
    representation. ``tuple`` instances are converted to ``tuple``
    so their inner values can also be frozen.
    """

    if isinstance(value, Mapping):
        frozen_items: dict[Any, Any] = {}
        for key, item in value.items():
            frozen_items[key] = _freeze_payload(item)
        return MappingProxyType(frozen_items)
    if isinstance(value, tuple):
        return tuple(_freeze_payload(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze_payload(item) for item in value)
    return value


def _dataclass_to_jsonable(value: Any) -> Any:
    """Coerce a codec dataclass into a JSON-friendly mapping.

    ``canonical_json`` does not understand domain wrappers such as
    :class:`InstrumentId`; ``dataclasses.asdict`` is unsuitable here
    because it deep-copies through ``copy.deepcopy`` which cannot
    serialize :class:`types.MappingProxyType`. The custom walk below
    expands dataclass fields into plain mappings while leaving frozen
    mapping proxies untouched.
    """

    if hasattr(value, "__dataclass_fields__"):
        return {
            field_name: _dataclass_to_jsonable(getattr(value, field_name))
            for field_name in value.__dataclass_fields__
        }
    if isinstance(value, MappingProxyType) or (
        isinstance(value, Mapping)
        and not hasattr(value, "__dataclass_fields__")
    ):
        return {key: _dataclass_to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_dataclass_to_jsonable(item) for item in value)
    if isinstance(value, list):
        return [_dataclass_to_jsonable(item) for item in value]
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JiuwenSwarmSchemaError(
            f"JiuwenSwarm payload field {field_name!r} must be a non-blank string"
        )
    return value.strip()


def _require_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    candidate = getattr(value, "value", None)
    if isinstance(candidate, UUID):
        return candidate
    raise JiuwenSwarmSchemaError(
        f"JiuwenSwarm payload field {field_name!r} must be a UUID, "
        f"got {type(value).__name__}"
    )


def _require_str_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise JiuwenSwarmSchemaError(
            f"JiuwenSwarm payload field {field_name!r} must be a list/tuple of strings"
        )
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise JiuwenSwarmSchemaError(
                f"JiuwenSwarm payload field {field_name!r}[{index}] must be a "
                f"non-blank string"
            )
        out.append(item.strip())
    return tuple(sorted(set(out)))


class JiuwenSwarmAcceptance(StrEnum):
    """Three-valued acceptance classification for a gateway response.

    Values are part of the public contract — Slice 2+ persists the
    acceptance on the research run audit row.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNCERTAIN_TIMEOUT = "uncertain_timeout"


def _mapping_equal(left: Any, right: Any) -> bool:
    """Structural equality that works across ``Mapping`` and ``MappingProxyType``.

    ``dataclasses.asdict`` deep-copies through ``copy.deepcopy`` which
    cannot pickle :class:`types.MappingProxyType`. Comparing the
    payload directly keeps the equality contract stable while still
    distinguishing any drift in nested values.
    """

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if left.keys() != right.keys():
            return False
        return all(_mapping_equal(left[key], right[key]) for key in left)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        if type(left) is not type(right) or len(left) != len(right):
            return False
        return all(
            _mapping_equal(lhs, rhs) for lhs, rhs in zip(left, right, strict=True)
        )
    return left == right


@dataclass(frozen=True, slots=True)
class JiuwenSwarmGatewayRequest:
    """Versioned, deterministic wire payload sent to the gateway.

    Fields are immutable and validated on construction. ``request_id``
    is the caller-supplied identifier the gateway will echo in every
    callback so PR-6 Slice 3 can reconcile duplicate notifications
    against the original submission. ``evidence_ids`` is the whitelist
    forwarded to the gateway; the gateway must never echo evidence
    IDs outside this set in an ``ACCEPTED`` result.

    ``payload`` is the deterministic JSON body forwarded to the
    gateway. The dataclass freezes the mapping recursively so
    downstream consumers cannot mutate it. The full binding invariants
    (case identity + case business facts + pack identity) are
    re-asserted on construction so a misuse between the mapper and
    the transport is detected as a :class:`JiuwenSwarmSchemaError`.
    """

    schema_version: str
    request_id: str
    case_id: UUID
    case_instrument_id: UUID
    case_as_of_date: str
    case_question: str
    case_horizon: str
    run_id: UUID
    evidence_pack_id: UUID
    playbook_key: str
    playbook_version: str
    adapter_version: str
    evidence_ids: tuple[str, ...]
    runner_key: str = _RUNNER_KEY
    payload: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.schema_version != JIUWENSWARM_SCHEMA_VERSION:
            raise JiuwenSwarmSchemaError(
                f"JiuwenSwarmGatewayRequest.schema_version must be "
                f"{JIUWENSWARM_SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        object.__setattr__(
            self, "schema_version", _require_str(self.schema_version, "schema_version")
        )
        object.__setattr__(self, "request_id", _require_str(self.request_id, "request_id"))
        object.__setattr__(self, "case_id", _require_uuid(self.case_id, "case_id"))
        object.__setattr__(
            self, "case_instrument_id",
            _require_uuid(self.case_instrument_id, "case_instrument_id"),
        )
        object.__setattr__(
            self, "case_as_of_date",
            _require_str(self.case_as_of_date, "case_as_of_date"),
        )
        object.__setattr__(
            self, "case_question", _require_str(self.case_question, "case_question")
        )
        object.__setattr__(
            self, "case_horizon", _require_str(self.case_horizon, "case_horizon")
        )
        object.__setattr__(self, "run_id", _require_uuid(self.run_id, "run_id"))
        object.__setattr__(
            self, "evidence_pack_id", _require_uuid(self.evidence_pack_id, "evidence_pack_id")
        )
        object.__setattr__(
            self, "playbook_key", _require_str(self.playbook_key, "playbook_key")
        )
        object.__setattr__(
            self, "playbook_version",
            _require_str(self.playbook_version, "playbook_version"),
        )
        object.__setattr__(
            self, "adapter_version", _require_str(self.adapter_version, "adapter_version")
        )
        object.__setattr__(
            self, "runner_key", _require_str(self.runner_key, "runner_key")
        )
        normalized = _require_str_tuple(self.evidence_ids, "evidence_ids")
        if not normalized:
            raise JiuwenSwarmSchemaError(
                "JiuwenSwarmGatewayRequest.evidence_ids must be non-empty"
            )
        object.__setattr__(self, "evidence_ids", normalized)
        if not isinstance(self.payload, Mapping):
            raise JiuwenSwarmSchemaError(
                "JiuwenSwarmGatewayRequest.payload must be a mapping"
            )
        object.__setattr__(self, "payload", _freeze_payload(self.payload))

    def to_json(self) -> str:
        """Return the deterministic JSON representation of the request.

        UUID / MappingProxyType / tuple values are routed through the
        domain :func:`canonical_json` so two requests with the same
        logical content produce byte-identical wire bytes.
        """

        return canonical_json(_dataclass_to_jsonable(self))


@dataclass(frozen=True, slots=True)
class JiuwenSwarmCompletion:
    """Validated gateway completion used by the result mapper.

    A :class:`JiuwenSwarmCompletion` carries the ``accepted`` outcome
    payload only. Rejected / uncertain-timeout outcomes are surfaced as
    typed errors (``JiuwenSwarmRemoteFailureError`` /
    ``JiuwenSwarmTimeoutUncertainError``) and never reach this
    dataclass.
    """

    schema_version: str
    playbook_key: str
    playbook_version: str
    adapter_version: str
    model_key: str
    model_version: str
    conclusion: str
    risks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    report_markdown: str
    acceptance: JiuwenSwarmAcceptance

    def __post_init__(self) -> None:
        if self.schema_version != JIUWENSWARM_SCHEMA_VERSION:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmCompletion.schema_version must be "
                f"{JIUWENSWARM_SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        if self.acceptance is not JiuwenSwarmAcceptance.ACCEPTED:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmCompletion must be built from an ACCEPTED result, "
                f"got {self.acceptance.value!r}"
            )
        object.__setattr__(
            self, "playbook_key", _require_str(self.playbook_key, "playbook_key")
        )
        object.__setattr__(
            self, "playbook_version",
            _require_str(self.playbook_version, "playbook_version"),
        )
        object.__setattr__(
            self, "adapter_version",
            _require_str(self.adapter_version, "adapter_version"),
        )
        object.__setattr__(self, "model_key", _require_str(self.model_key, "model_key"))
        object.__setattr__(
            self, "model_version", _require_str(self.model_version, "model_version")
        )
        object.__setattr__(
            self, "conclusion", _require_str(self.conclusion, "conclusion")
        )
        object.__setattr__(
            self, "report_markdown",
            _require_str(self.report_markdown, "report_markdown"),
        )
        object.__setattr__(
            self, "risks", _require_str_tuple(self.risks, "risks")
        )
        normalized_evidence = _require_str_tuple(
            self.evidence_ids, "evidence_ids"
        )
        if not normalized_evidence:
            raise JiuwenSwarmMalformedResultError(
                "JiuwenSwarmCompletion.evidence_ids must be non-empty"
            )
        object.__setattr__(self, "evidence_ids", normalized_evidence)

    def to_json(self) -> str:
        """Return the deterministic JSON representation of the completion."""

        return canonical_json(_dataclass_to_jsonable(self))


def coerce_completion(payload: Mapping[str, Any]) -> JiuwenSwarmCompletion:
    """Build a :class:`JiuwenSwarmCompletion` from a raw gateway payload.

    The validator surfaces :class:`JiuwenSwarmMalformedResultError` on
    any contract violation so the runner can map it to a typed error.
    Unknown extra fields are ignored: the gateway may attach internal
    audit metadata that the adapter must not promote into the
    domain draft.
    """

    if not isinstance(payload, Mapping):
        raise JiuwenSwarmMalformedResultError(
            f"JiuwenSwarm completion must be a mapping, "
            f"got {type(payload).__name__}"
        )
    try:
        try:
            acceptance = JiuwenSwarmAcceptance(payload.get("acceptance", "accepted"))
        except ValueError as exc:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarm completion has unknown acceptance "
                f"{payload.get('acceptance')!r}: {exc}"
            ) from exc
        try:
            return JiuwenSwarmCompletion(
                schema_version=payload["schema_version"],
                playbook_key=payload["playbook_key"],
                playbook_version=payload["playbook_version"],
                adapter_version=payload["adapter_version"],
                model_key=payload["model_key"],
                model_version=payload["model_version"],
                conclusion=payload["conclusion"],
                risks=payload["risks"],
                evidence_ids=payload["evidence_ids"],
                report_markdown=payload["report_markdown"],
                acceptance=acceptance,
            )
        except TypeError as exc:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarm completion has wrong field types: {exc}"
            ) from exc
        except ValueError as exc:
            raise JiuwenSwarmMalformedResultError(str(exc)) from exc
    except KeyError as exc:
        raise JiuwenSwarmMalformedResultError(
            f"JiuwenSwarm completion missing required field {exc.args[0]!r}"
        ) from exc
    except JiuwenSwarmMalformedResultError:
        raise
    except JiuwenSwarmSchemaError as exc:
        raise JiuwenSwarmMalformedResultError(str(exc)) from exc


def to_json(value: Any) -> str:
    """Return the deterministic JSON encoding of ``value``.

    UUID / ``Mapping`` / ``tuple`` containers are routed through the
    domain :func:`canonical_json` so the wire bytes are stable across
    re-runs and across processes. Frozen payloads (already wrapped in
    ``MappingProxyType``) serialize identically to the unfrozen source
    because the canonical encoder normalizes mapping keys.
    """

    return canonical_json(value)


__all__ = [
    "JIUWENSWARM_SCHEMA_VERSION",
    "JiuwenSwarmAcceptance",
    "JiuwenSwarmCompletion",
    "JiuwenSwarmGatewayRequest",
    "coerce_completion",
    "to_json",
]