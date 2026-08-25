"""Deterministic in-process :class:`ResearchRunner` adapter.

The Slice D boundary replaces the retired JiuwenSwarm runner as the
default path for queued :class:`ResearchRun` rows. The runner
constructs a :class:`ResearchRunnerDraft` from the supplied
:class:`EvidencePack` only — no gateway, subprocess, file, or network
I/O is touched — so the orchestrator can be exercised end-to-end in
tests and offline environments.

The runner satisfies the structural
:class:`invest_pipeline.research_orchestration_service.ResearchRunnerWithIdentity`
protocol by exposing ``runner_key`` / ``adapter_version`` attributes
and a ``run_with_identity`` method that returns a
:class:`JiuwenSwarmRunOutcome` carrying the constructed draft and a
deterministic ``(request_id, session_id)`` identity pair derived
from the :class:`ResearchRun` row. The slice intentionally keeps the
existing orchestrator-facing contract so the historical JiuwenSwarm
compatibility boundary (see :mod:`invest_pipeline.jiuwenswarm_runtime`)
is unaffected.

Failure injection is supported through the ``raise_exc`` constructor
argument: when set, the supplied exception is re-raised on every
invocation so focused tests can simulate deterministic failure modes
without mocking the runner out wholesale.

By default ``raise_exc`` is a fresh :class:`JiuwenSwarmRemoteFailureError`
instance — a subtype of :class:`JiuwenSwarmError` that the
:class:`ResearchOrchestrationService` already knows how to classify as
a permanent failure. Tests that want the happy path must opt out
explicitly with ``raise_exc=None`` (which the
:func:`build_fake_research_runner` factory does by default).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from invest_domain.research import (
    ContextProjection,
    EvidencePack,
    ResearchPlaybook,
    ResearchRunnerDraft,
)
from invest_domain.research.research_case import ResearchCase
from invest_domain.research.research_run import ResearchRun

from invest_pipeline.adapters.jiuwenswarm import (
    JiuwenSwarmAcceptance,
    JiuwenSwarmRemoteFailureError,
    JiuwenSwarmRunOutcome,
)

__all__ = [
    "DEFAULT_FAKE_RUNNER_ADAPTER_VERSION",
    "FAKE_RUNNER_KEY",
    "FakeResearchRunner",
    "build_fake_research_runner",
]


FAKE_RUNNER_KEY = "fake-runner-v1"
"""Deterministic runner key for :class:`FakeResearchRunner`.

Matches :data:`invest_api.application.research_run_command.FAKE_RUNNER_KEY`
so the API default queue path and the orchestrator's runner
validation agree on a single runner identity.
"""

DEFAULT_FAKE_RUNNER_ADAPTER_VERSION = "fake-runner-adapter-v1"
"""Adapter version string surfaced on every draft the Fake runner emits."""


def _pack_evidence_ids(evidence_pack: EvidencePack) -> tuple[str, ...]:
    """Return the sorted ``evidence_id`` tuple declared on ``evidence_pack.factors``."""

    ids = tuple(
        factor.evidence_id for factor in evidence_pack.factors if factor.evidence_id
    )
    return tuple(sorted(set(ids)))


def _build_risks(evidence_pack: EvidencePack) -> tuple[str, ...]:
    """Return deterministic risks derived from ``evidence_pack.data_quality``.

    The list intentionally stays small and stable so the resulting
    :class:`ResearchRunnerDraft` is reproducible across runs.
    """

    quality = evidence_pack.data_quality.quality_status.value
    freshness = evidence_pack.data_quality.freshness_status.value
    out: list[str] = []
    if quality != "complete":
        out.append(f"data_quality:{quality}")
    if freshness != "fresh":
        out.append(f"data_freshness:{freshness}")
    if evidence_pack.warnings:
        for warning in evidence_pack.warnings:
            out.append(f"pack_warning:{warning}")
    return tuple(sorted(set(out)))


def _build_conclusion(*, case: ResearchCase, evidence_pack: EvidencePack) -> str:
    """Return a deterministic conclusion string summarising the pack contents.

    The text is generated only from the supplied pack / case fields so
    the runner never depends on external state, and the same inputs
    always produce the same conclusion (a prerequisite for replay).
    """

    quality = evidence_pack.data_quality.quality_status.value
    freshness = evidence_pack.data_quality.freshness_status.value
    return (
        f"Deterministic fake conclusion for {evidence_pack.instrument.symbol} "
        f"as of {evidence_pack.case.as_of_date.isoformat()}: "
        f"quality={quality}, freshness={freshness}, "
        f"factors={len(evidence_pack.factors)}"
    )


def _build_report_markdown(
    *, evidence_pack: EvidencePack, evidence_ids: tuple[str, ...]
) -> str:
    """Return a deterministic Markdown report string for the draft."""

    lines = [
        f"# Fake Research Report ({evidence_pack.instrument.symbol})",
        "",
        f"- as_of_date: {evidence_pack.case.as_of_date.isoformat()}",
        f"- horizon: {evidence_pack.case.horizon}",
        f"- quality: {evidence_pack.data_quality.quality_status.value}",
        f"- freshness: {evidence_pack.data_quality.freshness_status.value}",
        f"- evidence_count: {len(evidence_ids)}",
        "",
        "## Evidence",
        "",
    ]
    lines.extend(f"- {evidence_id}" for evidence_id in evidence_ids)
    return "\n".join(lines)


def _build_draft(
    *,
    evidence_pack: EvidencePack,
    playbook: ResearchPlaybook,
    case: ResearchCase,
    adapter_version: str,
    created_at: datetime,
) -> ResearchRunnerDraft:
    """Return a :class:`ResearchRunnerDraft` whose evidence IDs come from ``pack``."""

    evidence_ids = _pack_evidence_ids(evidence_pack)
    if not evidence_ids:
        raise ValueError(
            "FakeResearchRunner requires an EvidencePack with at least one "
            "evidence_id on its factors"
        )
    return ResearchRunnerDraft(
        conclusion=_build_conclusion(case=case, evidence_pack=evidence_pack),
        risks=_build_risks(evidence_pack),
        evidence_ids=evidence_ids,
        report_markdown=_build_report_markdown(
            evidence_pack=evidence_pack, evidence_ids=evidence_ids
        ),
        model_key="fake-model",
        model_version="fake-model-v1",
        playbook_version=playbook.playbook_version,
        adapter_version=adapter_version,
        created_at=created_at,
    )


def _deterministic_identity(run_id: UUID) -> tuple[str, str]:
    """Return ``(request_id, session_id)`` derived deterministically from ``run_id``."""

    return f"fake-req-{run_id!s}", f"fake-sess-{run_id!s}"


@dataclass(slots=True)
class FakeResearchRunner:
    """Deterministic, no-I/O :class:`ResearchRunner` implementation.

    The runner satisfies the structural
    :class:`ResearchRunnerWithIdentity` protocol used by
    :class:`ResearchOrchestrationService` — the orchestrator does not
    care that the underlying outcome type is named after the retired
    JiuwenSwarm adapter; only the ``runner_key`` / ``adapter_version``
    fields and the ``run_with_identity`` signature matter.

    When ``raise_exc`` is set it is re-raised on every invocation,
    unchanged, so tests can drive deterministic failure paths through
    the same orchestration seam as the happy path without resorting
    to monkey-patching internals.

    The default ``raise_exc`` is a fresh
    :class:`JiuwenSwarmRemoteFailureError` instance so an otherwise
    unconfigured :class:`FakeResearchRunner` fails in a way the
    :class:`ResearchOrchestrationService` already classifies as a
    permanent failure — pass ``raise_exc=None`` to opt into the
    happy path.
    """

    runner_key: str = FAKE_RUNNER_KEY
    adapter_version: str = DEFAULT_FAKE_RUNNER_ADAPTER_VERSION
    raise_exc: Exception | None = field(
        default_factory=lambda: JiuwenSwarmRemoteFailureError(
            "FakeResearchRunner default injected failure"
        )
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    def run_with_identity(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
        started_at: datetime,
        projection: ContextProjection | None = None,
    ) -> JiuwenSwarmRunOutcome:
        """Return an accepted outcome whose draft is built from ``evidence_pack``."""

        self.calls.append(
            {
                "case_id": case.case_id,
                "run_id": run.run_id,
                "pack_id": evidence_pack.pack_id,
                "playbook_key": playbook.playbook_key,
                "started_at": started_at,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        request_id, session_id = _deterministic_identity(run.run_id)
        draft = _build_draft(
            evidence_pack=evidence_pack,
            playbook=playbook,
            case=case,
            adapter_version=self.adapter_version,
            created_at=started_at,
        )
        return JiuwenSwarmRunOutcome(
            request_id=request_id,
            session_id=session_id,
            acceptance=JiuwenSwarmAcceptance.ACCEPTED,
            draft=draft,
        )


def build_fake_research_runner(
    *,
    adapter_version: str = DEFAULT_FAKE_RUNNER_ADAPTER_VERSION,
    raise_exc: Exception | None = None,
) -> FakeResearchRunner:
    """Build a configured :class:`FakeResearchRunner` for production or test wiring."""

    if not isinstance(adapter_version, str) or not adapter_version.strip():
        raise ValueError("adapter_version must be a non-blank string")
    if raise_exc is not None and not isinstance(raise_exc, BaseException):
        raise TypeError(
            "raise_exc must be an Exception instance, got "
            f"{type(raise_exc).__name__}"
        )
    return FakeResearchRunner(
        adapter_version=adapter_version.strip(),
        raise_exc=raise_exc,
    )