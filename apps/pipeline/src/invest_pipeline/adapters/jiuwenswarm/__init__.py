"""JiuwenSwarm adapter package (PR-6 Slice 1).

Slice 1 owns the deterministic boundary between the domain
:class:`invest_domain.research.runner.ResearchRunner` port and the
JiuwenSwarm gateway. Slice 2 will provide the real WebSocket
transport; Slice 3 will wire the orchestrator that persists the
external request / session IDs.

Public symbols are re-exported here so callers import through the
package entry point:

    from invest_pipeline.adapters.jiuwenswarm import (
        JiuwenSwarmResearchRunner,
        JiuwenSwarmGatewayTransport,
        JiuwenSwarmGatewayRequest,
        JiuwenSwarmTransportResult,
        JiuwenSwarmCompletion,
        JiuwenSwarmAcceptance,
        build_request,
        build_draft,
        coerce_completion,
    )
"""

from __future__ import annotations

from invest_pipeline.adapters.jiuwenswarm.codec import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmAcceptance,
    JiuwenSwarmCompletion,
    JiuwenSwarmGatewayRequest,
    coerce_completion,
    to_json,
)
from invest_pipeline.adapters.jiuwenswarm.errors import (
    JiuwenSwarmError,
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmRemoteFailureError,
    JiuwenSwarmSchemaError,
    JiuwenSwarmTimeoutUncertainError,
    JiuwenSwarmTransportError,
)
from invest_pipeline.adapters.jiuwenswarm.mapping import build_draft, build_request
from invest_pipeline.adapters.jiuwenswarm.runner import JiuwenSwarmResearchRunner
from invest_pipeline.adapters.jiuwenswarm.transport import (
    JiuwenSwarmGatewayTransport,
    JiuwenSwarmTransportResult,
)

__all__ = [
    "JIUWENSWARM_SCHEMA_VERSION",
    "JiuwenSwarmAcceptance",
    "JiuwenSwarmCompletion",
    "JiuwenSwarmError",
    "JiuwenSwarmGatewayRequest",
    "JiuwenSwarmGatewayTransport",
    "JiuwenSwarmMalformedResultError",
    "JiuwenSwarmRemoteFailureError",
    "JiuwenSwarmResearchRunner",
    "JiuwenSwarmSchemaError",
    "JiuwenSwarmTimeoutUncertainError",
    "JiuwenSwarmTransportError",
    "JiuwenSwarmTransportResult",
    "build_draft",
    "build_request",
    "coerce_completion",
    "to_json",
]