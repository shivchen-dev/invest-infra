"""JiuwenSwarm adapter package (PR-6 Slice 1 + Slice 2 + Slice 3).

Slice 1 owns the deterministic boundary between the domain
:class:`invest_domain.research.runner.ResearchRunner` port and the
JiuwenSwarm gateway.

Slice 2 provides the real subprocess transport
(:class:`JiuwenSwarmCliGatewayTransport`) that invokes the gateway
helper CLI via ``subprocess.run``; the helper is never contacted over
a WebSocket and the runner is constructed explicitly by the
orchestrator with the :class:`JiuwenSwarmCliSettings` configuration.

Slice 3 adds the :class:`JiuwenSwarmRunOutcome` carrier and
:meth:`JiuwenSwarmResearchRunner.run_with_identity` so the
orchestrator can persist the exact external ``request_id`` /
``session_id`` the transport echoed, without leaking transport-layer
vocabulary into the domain port.

Public symbols are re-exported here so callers import through the
package entry point:

    from invest_pipeline.adapters.jiuwenswarm import (
        JiuwenSwarmCliGatewayTransport,
        JiuwenSwarmCliSettings,
        JiuwenSwarmResearchRunner,
        JiuwenSwarmRunOutcome,
        JiuwenSwarmGatewayTransport,
        JiuwenSwarmGatewayRequest,
        JiuwenSwarmTransportResult,
        JiuwenSwarmCompletion,
        JiuwenSwarmAcceptance,
        build_prompt_text,
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
from invest_pipeline.adapters.jiuwenswarm.config import (
    JiuwenSwarmCliSettings,
    default_python_executable,
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
from invest_pipeline.adapters.jiuwenswarm.prompt import (
    JIUWENSWARM_PROMPT_OUTPUT_SCHEMA,
    JIUWENSWARM_PROMPT_RULES,
    build_prompt_text,
)
from invest_pipeline.adapters.jiuwenswarm.runner import (
    JiuwenSwarmResearchRunner,
    JiuwenSwarmRunOutcome,
)
from invest_pipeline.adapters.jiuwenswarm.transport import (
    JiuwenSwarmGatewayTransport,
    JiuwenSwarmTransportResult,
)
from invest_pipeline.adapters.jiuwenswarm.transport_cli import (
    JiuwenSwarmCliGatewayTransport,
)

__all__ = [
    "JIUWENSWARM_PROMPT_OUTPUT_SCHEMA",
    "JIUWENSWARM_PROMPT_RULES",
    "JIUWENSWARM_SCHEMA_VERSION",
    "JiuwenSwarmAcceptance",
    "JiuwenSwarmCliGatewayTransport",
    "JiuwenSwarmCliSettings",
    "JiuwenSwarmCompletion",
    "JiuwenSwarmError",
    "JiuwenSwarmGatewayRequest",
    "JiuwenSwarmGatewayTransport",
    "JiuwenSwarmMalformedResultError",
    "JiuwenSwarmRemoteFailureError",
    "JiuwenSwarmResearchRunner",
    "JiuwenSwarmRunOutcome",
    "JiuwenSwarmSchemaError",
    "JiuwenSwarmTimeoutUncertainError",
    "JiuwenSwarmTransportError",
    "JiuwenSwarmTransportResult",
    "build_draft",
    "build_prompt_text",
    "build_request",
    "coerce_completion",
    "default_python_executable",
    "to_json",
]
