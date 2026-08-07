"""JiuwenSwarm adapter runner implementing :class:`ResearchRunner` (PR-6 Slice 1).

This module is the *only* layer that wires the domain port to the
JiuwenSwarm gateway transport. It enforces three contracts:

- The runner/playbook/pack trio must be bound (case / run IDs match
  the pack, the run is ``RUNNING``, the playbook's key matches the
  run's ``playbook_key``).
- The adapter version declared by the gateway completion must match
  the runner's ``adapter_version`` so a re-deploy that ships a new
  adapter cannot masquerade as the previous version's results.
- The transport is called exactly once per ``runner.run`` invocation;
  the runner does not retry inside the Slice 1 boundary because
  lifecycle-level retry policy belongs to PR-6 Slice 3 (orchestration).

The runner preserves the request / session IDs on the transport
result but never persists them: the
:class:`invest_domain.research.runner.ResearchRunner` port has no
Unit-of-Work seam, so persisting identity values would leak storage
concerns into the domain port.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from invest_domain.research import (
    EvidencePack,
    ResearchPlaybook,
    ResearchRunnerDraft,
)
from invest_domain.research.research_case import ResearchCase
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus

from invest_pipeline.adapters.jiuwenswarm.codec import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmAcceptance,
    JiuwenSwarmGatewayRequest,
    coerce_completion,
)
from invest_pipeline.adapters.jiuwenswarm.errors import (
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmRemoteFailureError,
    JiuwenSwarmTimeoutUncertainError,
    JiuwenSwarmTransportError,
)
from invest_pipeline.adapters.jiuwenswarm.mapping import build_draft, build_request
from invest_pipeline.adapters.jiuwenswarm.transport import (
    JiuwenSwarmGatewayTransport,
    JiuwenSwarmTransportResult,
)

_RUNNER_KEY = "jiuwenswarm-runner-v1"


class JiuwenSwarmResearchRunner:
    """Adapter-side :class:`ResearchRunner` for the JiuwenSwarm gateway.

    The runner is intentionally a plain class (not a dataclass) so the
    only attribute surface is the two protocol-mandated fields
    (``runner_key`` / ``adapter_version``) plus the injected
    transport. Domain construction is not involved.
    """

    def __init__(
        self,
        *,
        transport: JiuwenSwarmGatewayTransport,
        adapter_version: str,
    ) -> None:
        if not isinstance(adapter_version, str) or not adapter_version.strip():
            raise ValueError("JiuwenSwarmResearchRunner.adapter_version must be non-blank")
        self._transport = transport
        self._adapter_version = adapter_version.strip()

    @property
    def runner_key(self) -> str:
        return _RUNNER_KEY

    @property
    def adapter_version(self) -> str:
        return self._adapter_version

    def run(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
        started_at: datetime,
    ) -> ResearchRunnerDraft:
        """Submit one gateway request and return a :class:`ResearchRunnerDraft`."""

        self._validate_binding(
            case=case, run=run, evidence_pack=evidence_pack, playbook=playbook
        )

        request = build_request(
            case=case,
            run=run,
            evidence_pack=evidence_pack,
            playbook=playbook,
            adapter_version=self._adapter_version,
        )

        try:
            transport_result = self._transport.submit(request)
        except JiuwenSwarmTransportError:
            raise
        except Exception as exc:  # pragma: no cover - defensive surface
            raise JiuwenSwarmTransportError(
                "JiuwenSwarmGatewayTransport.submit raised an unexpected error"
            ) from exc

        if not isinstance(transport_result, JiuwenSwarmTransportResult):
            raise JiuwenSwarmTransportError(
                "JiuwenSwarmGatewayTransport.submit must return a "
                "JiuwenSwarmTransportResult"
            )

        return self._map_transport_result(
            request=request,
            playbook=playbook,
            evidence_pack=evidence_pack,
            transport_result=transport_result,
            started_at=started_at,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_binding(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
    ) -> None:
        if run.status is not ResearchRunStatus.RUNNING:
            raise JiuwenSwarmTransportError(
                f"JiuwenSwarmResearchRunner.run requires a RUNNING ResearchRun, "
                f"got {run.status.value!r}"
            )
        if run.runner_key != _RUNNER_KEY:
            raise JiuwenSwarmTransportError(
                f"ResearchRun.runner_key {run.runner_key!r} must be {_RUNNER_KEY!r}"
            )
        if run.playbook_key != playbook.playbook_key:
            raise JiuwenSwarmTransportError(
                "ResearchRun.playbook_key must equal playbook.playbook_key"
            )
        if run.evidence_pack_id != evidence_pack.pack_id:
            raise JiuwenSwarmTransportError(
                "ResearchRun.evidence_pack_id must equal EvidencePack.pack_id"
            )
        if run.case_id != case.case_id:
            raise JiuwenSwarmTransportError(
                "ResearchRun.case_id must equal ResearchCase.case_id"
            )
        if case.case_id != evidence_pack.case.case_id:
            raise JiuwenSwarmTransportError(
                "ResearchCase.case_id must equal EvidencePack.case.case_id"
            )
        for label, lhs, rhs in (
            ("instrument_id", case.instrument_id, evidence_pack.case.instrument_id),
            ("as_of_date", case.as_of_date, evidence_pack.case.as_of_date),
            ("question", case.question, evidence_pack.case.question),
            ("horizon", case.horizon, evidence_pack.case.horizon),
        ):
            if lhs != rhs:
                raise JiuwenSwarmTransportError(
                    f"ResearchCase.{label} must match EvidencePack.{label}"
                )

    def _map_transport_result(
        self,
        *,
        request: JiuwenSwarmGatewayRequest,
        playbook: ResearchPlaybook,
        evidence_pack: EvidencePack,
        transport_result: JiuwenSwarmTransportResult,
        started_at: datetime,
    ) -> ResearchRunnerDraft:
        self._validate_transport_result(request, transport_result)

        acceptance = transport_result.acceptance
        if acceptance is JiuwenSwarmAcceptance.REJECTED:
            raise JiuwenSwarmRemoteFailureError(
                f"JiuwenSwarm gateway rejected request {transport_result.request_id!r} "
                f"on session {transport_result.session_id!r}"
            )
        if acceptance is JiuwenSwarmAcceptance.UNCERTAIN_TIMEOUT:
            raise JiuwenSwarmTimeoutUncertainError(
                f"JiuwenSwarm gateway accepted request {transport_result.request_id!r} "
                f"on session {transport_result.session_id!r} but local timeout fired; "
                "outcome is uncertain until a duplicate callback arrives"
            )
        if acceptance is not JiuwenSwarmAcceptance.ACCEPTED:
            raise JiuwenSwarmRemoteFailureError(
                f"JiuwenSwarm gateway returned unknown acceptance "
                f"{acceptance.value!r}"
            )

        if not isinstance(transport_result.raw_payload, Mapping):
            raise JiuwenSwarmMalformedResultError(
                "JiuwenSwarm gateway completion payload must be a mapping"
            )

        completion = coerce_completion(transport_result.raw_payload)

        # Slice 1 enforces the schema version pin here so a future
        # backwards-incompatible gateway payload is rejected before the
        # mapper reaches the domain layer.
        if completion.schema_version != JIUWENSWARM_SCHEMA_VERSION:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmCompletion.schema_version must be "
                f"{JIUWENSWARM_SCHEMA_VERSION!r}, got {completion.schema_version!r}"
            )

        # The adapter version declared by the gateway completion must
        # match the runner's version so a re-deploy that ships a new
        # adapter cannot masquerade as the previous version's results.
        if completion.adapter_version != self._adapter_version:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmCompletion.adapter_version must be "
                f"{self._adapter_version!r}, got {completion.adapter_version!r}"
            )

        whitelist = tuple(
            sorted(
                {
                    item.evidence_id
                    for item in evidence_pack.factors
                    if item.evidence_id is not None
                }
            )
        )
        unknown = tuple(item for item in completion.evidence_ids if item not in whitelist)
        if unknown:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmCompletion.evidence_ids must be a subset of the "
                f"EvidencePack whitelist; unknown: {unknown}"
            )

        return build_draft(
            completion=completion,
            playbook=playbook,
            adapter_version=self._adapter_version,
            now=started_at,
        )

    @staticmethod
    def _validate_transport_result(
        request: JiuwenSwarmGatewayRequest,
        transport_result: JiuwenSwarmTransportResult,
    ) -> None:
        """Reject transport results whose identity pair is broken.

        The request ID the gateway echoes back must match the one the
        adapter submitted so PR-6 Slice 3 can reconcile duplicate
        callbacks deterministically; the session ID must be a non-blank
        string so the orchestrator can later route the rejection /
        timeout to the same audit row.
        """

        request_id = transport_result.request_id
        if not isinstance(request_id, str) or not request_id.strip():
            raise JiuwenSwarmMalformedResultError(
                "JiuwenSwarmTransportResult.request_id must be a non-blank string"
            )
        if request_id != request.request_id:
            raise JiuwenSwarmMalformedResultError(
                f"JiuwenSwarmTransportResult.request_id "
                f"{request_id!r} must match the submitted "
                f"request_id {request.request_id!r}"
            )
        session_id = transport_result.session_id
        if not isinstance(session_id, str) or not session_id.strip():
            raise JiuwenSwarmMalformedResultError(
                "JiuwenSwarmTransportResult.session_id must be a non-blank string"
            )


__all__ = ["JiuwenSwarmResearchRunner"]