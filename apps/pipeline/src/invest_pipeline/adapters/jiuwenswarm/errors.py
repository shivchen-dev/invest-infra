"""Adapter-specific error taxonomy for the JiuwenSwarm gateway (PR-6 Slice 1).

These exceptions are the stable contract the application layer uses to
classify a JiuwenSwarm failure into a known category. The mapping keeps
the domain port free of JiuwenSwarm-specific vocabulary while giving the
orchestration layer (PR-6 Slice 2/3) deterministic signals to drive
retry / fail-policy decisions.
"""

from __future__ import annotations


class JiuwenSwarmError(RuntimeError):
    """Base class for all JiuwenSwarm adapter failures."""


class JiuwenSwarmTransportError(JiuwenSwarmError):
    """The transport layer raised (network / deserialisation / cancellation).

    Maps to the *retryable* category in the lifecycle orchestrator.
    """


class JiuwenSwarmRemoteFailureError(JiuwenSwarmError):
    """The gateway accepted the request and later returned a rejection.

    Carries the gateway-reported reason so the orchestrator can surface
    a meaningful audit row. Does **not** indicate a transient failure;
    PR-6 §4.3 mandates retry only with operator opt-in.
    """


class JiuwenSwarmTimeoutUncertainError(JiuwenSwarmError):
    """The gateway accepted the request but the local timeout fired.

    The orchestrator MUST treat the gateway outcome as *unknown* until
    a duplicate callback arrives (PR-6 §4.3 "uncertain acceptance").
    Slice 1 preserves the request / session IDs for later reconciliation
    but does not persist them.
    """


class JiuwenSwarmSchemaError(ValueError):
    """Codec-level validation failure for an inbound payload.

    Distinct from :class:`JiuwenSwarmMalformedResultError` so adapter
    tests can pin the difference between "the wire bytes look wrong"
    (SchemaError) and "the result we mapped violates the slice
    contract" (MalformedResultError).
    """


class JiuwenSwarmMalformedResultError(JiuwenSwarmError):
    """The gateway completion was accepted but violates the contract.

    Raised by the request mapper when an ``ACCEPTED`` result references
    unknown evidence IDs, mismatches the playbook version, or otherwise
    fails codec-level validation. The orchestrator surfaces this as a
    permanent failure so a future re-run starts a fresh gateway
    session.
    """


__all__ = [
    "JiuwenSwarmError",
    "JiuwenSwarmMalformedResultError",
    "JiuwenSwarmRemoteFailureError",
    "JiuwenSwarmSchemaError",
    "JiuwenSwarmTimeoutUncertainError",
    "JiuwenSwarmTransportError",
]