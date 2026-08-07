"""JiuwenSwarm gateway transport port (PR-6 Slice 1).

The transport seam is intentionally a synchronous
:class:`typing.Protocol` so unit tests can inject an in-memory fake
without touching the network. PR-6 Slice 2 will provide the real
WebSocket transport behind the same protocol.

The transport contract:

- :meth:`JiuwenSwarmGatewayTransport.submit` consumes a validated
  :class:`JiuwenSwarmGatewayRequest` and returns a
  :class:`JiuwenSwarmTransportResult` preserving the request and
  session IDs so PR-6 Slice 3 can reconcile duplicates. **The adapter
  does not persist these IDs** because the
  :class:`invest_domain.research.runner.ResearchRunner` port has no
  Unit-of-Work seam; the IDs live only on the transport result and on
  the request the runner builds.
- The transport raises :class:`JiuwenSwarmTransportError` on
  unrecoverable transport failures (network reset, encoding error).
  The runner maps that exception into
  :class:`JiuwenSwarmRemoteFailureError` so callers see a stable
  taxonomy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from invest_pipeline.adapters.jiuwenswarm.codec import (
    JiuwenSwarmAcceptance,
    JiuwenSwarmGatewayRequest,
)


@dataclass(frozen=True, slots=True)
class JiuwenSwarmTransportResult:
    """Raw outcome of a single gateway submission.

    The transport surface only carries the identity pair
    (``request_id``, ``session_id``) and the classification. Slice 1
    keeps ``raw_payload`` for tests so the runner can map it; Slice 2
    will switch to streaming callbacks and the payload field will move
    onto the ``JiuwenSwarmCompletion`` carrier instead.
    """

    request_id: str
    session_id: str
    acceptance: JiuwenSwarmAcceptance
    raw_payload: Mapping[str, Any] | None = None


@runtime_checkable
class JiuwenSwarmGatewayTransport(Protocol):
    """Structural port for the JiuwenSwarm transport (Slice 2 implementation)."""

    def submit(
        self, request: JiuwenSwarmGatewayRequest
    ) -> JiuwenSwarmTransportResult:
        ...


__all__ = [
    "JiuwenSwarmGatewayTransport",
    "JiuwenSwarmTransportResult",
]