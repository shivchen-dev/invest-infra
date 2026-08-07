"""Adapter-specific error taxonomy for the JiuwenSwarm gateway (PR-6 Slice 1 + Slice 3).

These exceptions are the stable contract the application layer uses to
classify a JiuwenSwarm failure into a known category. The mapping keeps
the domain port free of JiuwenSwarm-specific vocabulary while giving the
orchestration layer (PR-6 Slice 3) deterministic signals to drive
retry / fail-policy decisions.

Slice 3 enrichment: every adapter exception now carries optional
``request_id`` and ``session_id`` structured attributes so the
orchestrator can bind the external identity to the research run
*before* the lifecycle failure transition is applied. The :class:`str`
identifiers are part of the wire envelope and never carry credentials
or workspace paths, so persisting them on the audit row is safe.
Messages remain free-form to preserve the existing logs.
"""

from __future__ import annotations

from typing import Any


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"JiuwenSwarm adapter error attributes must be str or None; "
            f"got {type(value).__name__}"
        )
    stripped = value.strip()
    return stripped if stripped else None


class JiuwenSwarmError(RuntimeError):
    """Base class for all JiuwenSwarm adapter failures.

    Subclasses expose the structured ``request_id`` / ``session_id``
    pair the runner captured during a single submission. The pair is
    ``None`` until the transport layer has had a chance to validate
    the helper's stdout summary; callers must read the attributes
    defensively.
    """

    request_id: str | None = None
    session_id: str | None = None

    def __init__(
        self,
        message: str = "",
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(message)
        normalized_request = _normalize_optional_str(request_id)
        normalized_session = _normalize_optional_str(session_id)
        if normalized_session is not None and normalized_request is None:
            raise ValueError(
                "JiuwenSwarm adapter errors must carry a request_id when a "
                "session_id is provided"
            )
        self.request_id = normalized_request
        self.session_id = normalized_session


class JiuwenSwarmTransportError(JiuwenSwarmError):
    """The transport layer raised (network / deserialisation / cancellation).

    Maps to the *retryable* category in the lifecycle orchestrator.
    Carries the request / session identity pair whenever the helper
    summary was parsed before the failure surfaced; ``request_id`` /
    ``session_id`` stay ``None`` when the helper never produced a
    summary (e.g. the local subprocess watchdog fired).
    """


class JiuwenSwarmRemoteFailureError(JiuwenSwarmError):
    """The gateway accepted the request and later returned a rejection.

    Carries the gateway-reported reason so the orchestrator can surface
    a meaningful audit row. Does **not** indicate a transient failure;
    PR-6 §4.3 mandates retry only with operator opt-in. The structured
    ``request_id`` / ``session_id`` attributes are populated whenever
    the helper summary parsed successfully so the orchestrator can
    bind the exact external identity before transitioning the run /
    case to ``failed``.
    """


class JiuwenSwarmTimeoutUncertainError(JiuwenSwarmError):
    """The gateway accepted the request but the local timeout fired.

    The orchestrator MUST treat the gateway outcome as *unknown* until
    a duplicate callback arrives (PR-6 §4.3 "uncertain acceptance").
    Slice 3 binds the ``request_id`` / ``session_id`` identity pair
    before re-raising so a callback reconciliation worker can find the
    run by either field.
    """


class JiuwenSwarmSchemaError(ValueError):
    """Codec-level validation failure for an inbound payload.

    Distinct from :class:`JiuwenSwarmMalformedResultError` so adapter
    tests can pin the difference between "the wire bytes look wrong"
    (SchemaError) and "the result we mapped violates the slice
    contract" (MalformedResultError). Codec-layer errors never carry
    ``request_id`` / ``session_id`` because the payload itself failed
    validation.
    """

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.request_id = None
        self.session_id = None


class JiuwenSwarmMalformedResultError(JiuwenSwarmError):
    """The gateway completion was accepted but violates the contract.

    Raised by the request mapper when an ``ACCEPTED`` result references
    unknown evidence IDs, mismatches the playbook version, or otherwise
    fails codec-level validation. The orchestrator surfaces this as a
    permanent failure so a future re-run starts a fresh gateway
    session. The structured identity attributes are populated whenever
    the helper summary parsed successfully so the orchestrator can
    bind the exact external identity before transitioning the run /
    case to ``failed``.
    """


__all__ = [
    "JiuwenSwarmError",
    "JiuwenSwarmMalformedResultError",
    "JiuwenSwarmRemoteFailureError",
    "JiuwenSwarmSchemaError",
    "JiuwenSwarmTimeoutUncertainError",
    "JiuwenSwarmTransportError",
]