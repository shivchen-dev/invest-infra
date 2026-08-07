"""Pure-function mappers between domain types and JiuwenSwarm codec (PR-6 Slice 1).

Two responsibilities:

- :func:`build_request` derives a :class:`JiuwenSwarmGatewayRequest`
  from a running case / run / evidence pack / playbook quadruple. The
  mapper is deterministic, never mutates its inputs, and never leaks
  workspace paths, credentials, or runtime lineage metadata
  (``pipeline_run_id``, ``e2a_request_id``, ``e2a_session_id``,
  ``generated_at``) into the wire payload. The agent *does* receive
  the factor values, source references, and the case question needed
  to ground every citation, plus the explicit ``pack_id`` /
  ``pack_hash`` and per-factor ``evidence_id`` annotations the
  gateway needs to echo those citations back as a whitelist.
- :func:`build_draft` derives a :class:`ResearchRunnerDraft` from a
  validated :class:`JiuwenSwarmCompletion`. Domain completion
  (``complete_research_attempt``) remains the authoritative gate on
  evidence ID existence — the mapper only carries the IDs the gateway
  returned; the domain ``ResearchResult.create`` revalidates them
  against the supplied pack.

Both mappers are pure stdlib functions (no IO, no logging, no clock
side-effects); they are trivial to unit-test and stable across
re-runs.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from invest_domain import canonical_json
from invest_domain.research import (
    EvidencePack,
    ResearchPlaybook,
    ResearchRunnerDraft,
    pack_content_projection,
)
from invest_domain.research.research_case import ResearchCase
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus

from invest_pipeline.adapters.jiuwenswarm.codec import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmCompletion,
    JiuwenSwarmGatewayRequest,
)


def _evidence_id_whitelist(evidence_pack: EvidencePack) -> tuple[str, ...]:
    """Return the deterministic evidence-ID whitelist from ``evidence_pack``.

    Sort + dedupe is performed so two runs over the same pack produce
    byte-identical wire payloads. ``None`` evidence IDs are dropped
    defensively (a malformed pack should not propagate into the
    gateway).
    """

    ids = sorted(
        {item.evidence_id for item in evidence_pack.factors if item.evidence_id}
    )
    return tuple(ids)


def _case_payload(case: ResearchCase, evidence_pack: EvidencePack) -> dict[str, Any]:
    """Project the case identity onto the wire payload.

    The mapper pins the four shared business facts on
    :class:`CaseContext` so the gateway can reconcile the request with
    the originating case without depending on lifecycle state.
    """

    ctx = evidence_pack.case
    return {
        "instrument_id": str(ctx.instrument_id),
        "as_of_date": ctx.as_of_date,
        "question": ctx.question,
        "horizon": ctx.horizon,
        "case_id": str(case.case_id),
    }


def build_request(
    *,
    case: ResearchCase,
    run: ResearchRun,
    evidence_pack: EvidencePack,
    playbook: ResearchPlaybook,
    adapter_version: str,
) -> JiuwenSwarmGatewayRequest:
    """Build a deterministic gateway request from a running trio.

    The function enforces the same binding invariants the domain
    completion gate enforces — case / run / pack identity keys must
    line up, the run must be in ``RUNNING``, and the shared case
    business facts must match the pack — but it is a strict subset of
    the domain checks. ``complete_research_attempt`` remains the
    authoritative gate.
    """

    if not isinstance(case.case_id, UUID):
        raise ValueError(
            "build_request requires ResearchCase.case_id to be a UUID, "
            f"got {type(case.case_id).__name__}"
        )
    pack_case_id = evidence_pack.case.case_id
    if not isinstance(pack_case_id, UUID):
        raise ValueError(
            "build_request requires EvidencePack.case.case_id to be a UUID, "
            f"got {type(pack_case_id).__name__}"
        )
    if case.case_id != pack_case_id:
        raise ValueError(
            "ResearchCase.case_id must match EvidencePack.case.case_id"
        )
    if run.case_id != case.case_id:
        raise ValueError(
            "ResearchRun.case_id must match ResearchCase.case_id"
        )
    if run.evidence_pack_id != evidence_pack.pack_id:
        raise ValueError(
            "ResearchRun.evidence_pack_id must match EvidencePack.pack_id"
        )
    if run.status is not ResearchRunStatus.RUNNING:
        raise ValueError(
            f"build_request requires a RUNNING ResearchRun, "
            f"got {run.status.value!r}"
        )
    if run.runner_key != "jiuwenswarm-runner-v1":
        raise ValueError(
            "build_request requires the runner to be the JiuwenSwarm adapter "
            f"(runner_key={run.runner_key!r})"
        )
    if playbook.playbook_key != run.playbook_key:
        raise ValueError(
            "playbook.playbook_key must equal ResearchRun.playbook_key"
        )
    pack_ctx = evidence_pack.case
    for label, lhs, rhs in (
        ("instrument_id", case.instrument_id, pack_ctx.instrument_id),
        ("as_of_date", case.as_of_date, pack_ctx.as_of_date),
        ("question", case.question, pack_ctx.question),
        ("horizon", case.horizon, pack_ctx.horizon),
    ):
        if lhs != rhs:
            raise ValueError(
                f"ResearchCase.{label} must match EvidencePack.{label}"
            )

    payload: dict[str, Any] = {
        "compatibility_mode": "evidence_only",
        "context": {"status": "not_bound"},
        "case": _case_payload(case, evidence_pack),
        "evidence_pack": _agent_evidence_pack_payload(evidence_pack),
        "playbook": {
            "key": playbook.playbook_key,
            "version": playbook.playbook_version,
        },
    }

    return JiuwenSwarmGatewayRequest(
        schema_version=JIUWENSWARM_SCHEMA_VERSION,
        request_id=_derive_request_id(
            case_id=case.case_id,
            run_id=run.run_id,
            evidence_pack_id=evidence_pack.pack_id,
        ),
        case_id=case.case_id,
        case_instrument_id=case.instrument_id,
        case_as_of_date=case.as_of_date.isoformat(),
        case_question=case.question,
        case_horizon=case.horizon,
        run_id=run.run_id,
        evidence_pack_id=evidence_pack.pack_id,
        playbook_key=playbook.playbook_key,
        playbook_version=playbook.playbook_version,
        adapter_version=adapter_version,
        evidence_ids=_evidence_id_whitelist(evidence_pack),
        payload=payload,
    )


def _agent_evidence_pack_payload(
    evidence_pack: EvidencePack,
) -> dict[str, Any]:
    """Project the evidence pack for the gateway without runtime lineage.

    Starts from :func:`invest_domain.research.pack_content_projection`
    (the deterministic, *content-only* projection: case business
    facts, instrument, market snapshot, data quality, factor values,
    source references, warnings, schema version) and then explicitly
    layers the three citation keys the gateway needs to echo back the
    whitelist of evidence IDs:

    - ``pack_id`` so the completion can be reconciled against the
      originating pack,
    - ``pack_hash`` so the completion can be cross-checked against
      the canonical content hash,
    - per-factor ``evidence_id`` so each factor carries the stable
      identifier the gateway must cite (and so the completion
      validator can whitelist citations deterministically).

    The mapper deliberately omits the runtime lineage fields
    :class:`EvidencePack` carries for storage / audit
    (``workspace_path``, ``pipeline_run_id``, ``e2a_request_id``,
    ``e2a_session_id``, ``generated_at``): those belong to the
    ingestion pipeline, not to the agent's research context, and
    exposing them would let the gateway echo back identifiers that
    the domain completion gate would then have to reject.
    """

    projection = pack_content_projection(evidence_pack)
    projection["pack_id"] = (
        None if evidence_pack.pack_id is None else str(evidence_pack.pack_id)
    )
    projection["pack_hash"] = evidence_pack.pack_hash
    projection["factors"] = [
        {**factor, "evidence_id": observation.evidence_id}
        for factor, observation in zip(
            projection["factors"], evidence_pack.factors, strict=True
        )
    ]
    return projection


def _derive_request_id(
    *,
    case_id: UUID,
    run_id: UUID,
    evidence_pack_id: UUID,
) -> str:
    """Return a deterministic request id derived from the binding trio.

    The hash is stable across re-runs of the same trio so PR-6 Slice 3
    can reconcile duplicate gateway callbacks deterministically without
    inventing a fresh UUID per attempt.
    """

    digest = sha256()
    for value in (str(case_id), str(run_id), str(evidence_pack_id)):
        digest.update(value.encode("utf-8"))
        digest.update(b"|")
    return digest.hexdigest()


def build_draft(
    *,
    completion: JiuwenSwarmCompletion,
    playbook: ResearchPlaybook,
    adapter_version: str,
    now: datetime,
) -> ResearchRunnerDraft:
    """Build a :class:`ResearchRunnerDraft` from a validated completion.

    The mapper is the *only* step that converts gateway output into a
    domain draft; ``complete_research_attempt`` is then responsible for
    binding the draft to the succeeded run, validating evidence IDs,
    and producing the final :class:`ResearchResult`.

    By the time ``build_draft`` is reached the runner has already
    rejected any citation whose evidence ID is not present in the
    supplied pack whitelist, so the mapper passes the completion's
    IDs through verbatim.
    """

    if completion.playbook_key != playbook.playbook_key:
        raise ValueError(
            "completion.playbook_key must equal playbook.playbook_key"
        )
    if completion.playbook_version != playbook.playbook_version:
        raise ValueError(
            "completion.playbook_version must equal playbook.playbook_version"
        )
    if not isinstance(now, datetime):
        raise TypeError(
            f"build_draft requires a datetime now, got {type(now).__name__}"
        )
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("build_draft requires a timezone-aware now")

    return ResearchRunnerDraft(
        conclusion=completion.conclusion,
        risks=completion.risks,
        evidence_ids=completion.evidence_ids,
        report_markdown=completion.report_markdown,
        model_key=completion.model_key,
        model_version=completion.model_version,
        playbook_version=completion.playbook_version,
        adapter_version=adapter_version,
        created_at=now,
    )


def payload_to_json(payload: Any) -> str:
    """Return the deterministic JSON serialization of a wire payload.

    The codec delegates to :func:`invest_domain.research.canonical_json`
    so the request envelope, completion payload, and any nested
    evidence-pack projection share one ordering, one UUID encoding,
    and one set of normalized primitive rules. ``MappingProxyType``
    wrappers and tuple types are accepted transparently because the
    codec freezes those structures for immutability.
    """

    return canonical_json(payload)


__all__ = ["build_draft", "build_request", "payload_to_json"]