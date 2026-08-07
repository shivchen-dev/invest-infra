"""ResearchRunner port and minimal lifecycle orchestration (Phase 3 / Task 3.3).

The domain owns:

- :class:`ResearchPlaybook`: versioned configuration that drives a runner.
- :class:`ResearchRunner`: structural :class:`typing.Protocol` adapters satisfy.
- :class:`ResearchRunnerDraft`: runner output, validated and bound to a succeeded run.
- :func:`start_research_attempt` / :func:`complete_research_attempt` /
  :func:`fail_research_attempt` / :func:`execute_research_attempt`: helpers
  driving the ``ready -> running -> draft -> succeeded -> completed`` lifecycle.

The domain owns no concrete runner; test doubles live in
:mod:`test_research_runner`. ``complete_research_attempt`` validates
the draft's evidence IDs against the pack **before** transitioning the
run to ``succeeded`` so a succeeded run is never stranded without a
publishable :class:`ResearchResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from invest_domain.research.models import EvidencePack
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"{field_name} must be a datetime, got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _stripped_sorted(items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item.strip() for item in items if item.strip()}))


def _non_blank_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _non_blank_strings(
    items: tuple[str, ...], field_name: str
) -> None:
    if not isinstance(items, tuple) or any(
        not isinstance(item, str) or not item.strip() for item in items
    ):
        raise ValueError(
            f"{field_name} must be a tuple of non-blank strings"
        )


@dataclass(frozen=True, slots=True)
class ResearchPlaybook:
    """Versioned configuration that drives a :class:`ResearchRunner`."""

    playbook_key: str
    playbook_version: str
    description: str = ""
    cited_factor_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("playbook_key", "playbook_version"):
            object.__setattr__(
                self,
                name,
                _non_blank_str(getattr(self, name), f"ResearchPlaybook.{name}"),
            )
        if not isinstance(self.description, str):
            raise TypeError("ResearchPlaybook.description must be a string")
        _non_blank_strings(
            self.cited_factor_keys, "ResearchPlaybook.cited_factor_keys"
        )
        object.__setattr__(
            self, "cited_factor_keys", _stripped_sorted(self.cited_factor_keys)
        )


@dataclass(frozen=True, slots=True)
class ResearchRunnerDraft:
    """Content output of a :class:`ResearchRunner` before binding to a succeeded run."""

    conclusion: str
    risks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    report_markdown: str
    model_key: str
    model_version: str
    playbook_version: str
    adapter_version: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "conclusion",
            "report_markdown",
            "model_key",
            "model_version",
            "playbook_version",
            "adapter_version",
        ):
            object.__setattr__(
                self,
                name,
                _non_blank_str(getattr(self, name), f"ResearchRunnerDraft.{name}"),
            )
        _non_blank_strings(self.risks, "ResearchRunnerDraft.risks")
        _non_blank_strings(self.evidence_ids, "ResearchRunnerDraft.evidence_ids")
        if not self.evidence_ids:
            raise ValueError("ResearchRunnerDraft requires at least one evidence_id")
        _require_aware(self.created_at, "ResearchRunnerDraft.created_at")
        object.__setattr__(self, "risks", _stripped_sorted(self.risks))
        object.__setattr__(
            self, "evidence_ids", _stripped_sorted(self.evidence_ids)
        )

    def to_result(
        self, *, run: ResearchRun, evidence_pack: EvidencePack
    ) -> ResearchResult:
        return ResearchResult.create(
            run=run,
            evidence_pack=evidence_pack,
            conclusion=self.conclusion,
            risks=self.risks,
            evidence_ids=self.evidence_ids,
            report_markdown=self.report_markdown,
            model_key=self.model_key,
            model_version=self.model_version,
            playbook_version=self.playbook_version,
            adapter_version=self.adapter_version,
            created_at=self.created_at,
        )


class ResearchRunnerFailure(RuntimeError):
    """Raised by a :class:`ResearchRunner` when it cannot produce a result."""


@runtime_checkable
class ResearchRunner(Protocol):
    """Structural port for runner adapters (PR-6 JiuwenSwarm, PR-7 API)."""

    runner_key: str
    adapter_version: str

    def run(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
        started_at: datetime,
    ) -> ResearchRunnerDraft:
        ...


def _validate_case_pack_alignment(case: ResearchCase, pack: EvidencePack) -> None:
    """Reject case/pack pairs whose identity keys do not match.

    ``EvidencePack.case.case_id`` must be a real :class:`UUID` (not
    ``None`` and not a free-form string) and must equal
    ``ResearchCase.case_id`` so the bound run/pack cannot drift away
    from the lifecycle aggregate. The shared business facts on
    :class:`CaseContext` (``instrument_id``, ``as_of_date``,
    ``question``, ``horizon``) are also re-checked here.
    """

    if not isinstance(case.case_id, UUID):
        raise ValueError(
            "ResearchCase.case_id must be a UUID, "
            f"got {type(case.case_id).__name__}"
        )
    pack_case_id = pack.case.case_id
    if not isinstance(pack_case_id, UUID):
        raise ValueError(
            "EvidencePack.case.case_id must be a UUID, "
            f"got {type(pack_case_id).__name__}"
        )
    if case.case_id != pack_case_id:
        raise ValueError(
            f"ResearchCase.case_id {case.case_id!s} must match "
            f"EvidencePack.case.case_id {pack_case_id!s}"
        )
    if pack.pack_id is None:
        raise ValueError("EvidencePack.pack_id must not be None")
    ctx = case.to_case_context()
    for label, lhs, rhs in (
        ("instrument_id", ctx.instrument_id, pack.case.instrument_id),
        ("as_of_date", ctx.as_of_date, pack.case.as_of_date),
        ("question", ctx.question, pack.case.question),
        ("horizon", ctx.horizon, pack.case.horizon),
    ):
        if lhs != rhs:
            raise ValueError(
                f"ResearchCase.{label} must match EvidencePack.{label}"
            )


def _validate_draft_evidence_refs(
    draft: ResearchRunnerDraft, pack: EvidencePack
) -> None:
    """Reject drafts that cite evidence IDs not present in ``pack``."""

    pack_ids = {
        item.evidence_id for item in pack.factors if item.evidence_id is not None
    }
    missing = tuple(item for item in draft.evidence_ids if item not in pack_ids)
    if missing:
        raise ValueError(
            f"ResearchRunnerDraft.evidence_ids not present in EvidencePack: {missing}"
        )


def _validate_completion_binding(
    *,
    case: ResearchCase,
    run: ResearchRun,
    pack: EvidencePack,
) -> None:
    """Re-bind the case/run/pack trio before the run is allowed to succeed.

    The :class:`ResearchRunner` may carry the trio forward with
    detached identifiers after a failed attempt; this gate fails closed
    if the trio has drifted apart or if the case/run is not in the
    active state ``complete_research_attempt`` requires.
    """

    if case.status is not ResearchCaseStatus.RUNNING:
        raise ValueError(
            "complete_research_attempt requires case in RUNNING, "
            f"got {case.status.value!r}"
        )
    if run.status is not ResearchRunStatus.RUNNING:
        raise ValueError(
            "complete_research_attempt requires run in RUNNING, "
            f"got {run.status.value!r}"
        )
    if run.case_id != case.case_id:
        raise ValueError(
            f"ResearchRun.case_id {run.case_id!s} must match "
            f"ResearchCase.case_id {case.case_id!s}"
        )
    if run.evidence_pack_id != pack.pack_id:
        raise ValueError(
            f"ResearchRun.evidence_pack_id {run.evidence_pack_id!s} "
            f"must match EvidencePack.pack_id {pack.pack_id!s}"
        )
    _validate_case_pack_alignment(case, pack)


def start_research_attempt(
    *,
    case: ResearchCase,
    evidence_pack: EvidencePack,
    playbook: ResearchPlaybook,
    runner: ResearchRunner,
    started_at: datetime,
) -> tuple[ResearchCase, ResearchRun]:
    """Drive ``ready -> running`` for the case and ``queued -> running`` for the run."""

    _require_aware(started_at, "started_at")
    _validate_case_pack_alignment(case, evidence_pack)
    if case.status is not ResearchCaseStatus.READY:
        raise ValueError(
            f"start_research_attempt requires case in READY, "
            f"got {case.status.value!r}"
        )
    running_case = case.transition(
        ResearchCaseStatus.RUNNING, occurred_at=started_at
    )
    run = ResearchRun.create(
        case_id=running_case.case_id,
        evidence_pack_id=evidence_pack.pack_id,
        runner_key=runner.runner_key,
        playbook_key=playbook.playbook_key,
    )
    started_run = run.start(occurred_at=started_at)
    return running_case, started_run


def complete_research_attempt(
    *,
    case: ResearchCase,
    run: ResearchRun,
    draft: ResearchRunnerDraft,
    evidence_pack: EvidencePack,
    finished_at: datetime,
) -> tuple[ResearchCase, ResearchRun, ResearchResult]:
    """Re-bind the case/run/pack trio, validate draft refs, succeed the run.

    The case/run/pack binding is revalidated **before** the draft is
    validated and **before** the run transitions to ``succeeded``: a
    succeeded run is never allowed to refer to a run/case/pack trio
    that does not line up. :meth:`ResearchRunnerDraft.to_result` still
    re-asserts the pack/run match inside :class:`ResearchResult`
    construction as a second line of defence.
    """

    _require_aware(finished_at, "finished_at")
    _validate_completion_binding(case=case, run=run, pack=evidence_pack)
    _validate_draft_evidence_refs(draft, evidence_pack)
    succeeded_run = run.succeed(occurred_at=finished_at)
    result = draft.to_result(run=succeeded_run, evidence_pack=evidence_pack)
    completed_case = case.transition(
        ResearchCaseStatus.COMPLETED, occurred_at=finished_at
    )
    return completed_case, succeeded_run, result


def fail_research_attempt(
    *,
    case: ResearchCase,
    run: ResearchRun,
    error_summary: str,
    failed_at: datetime,
) -> tuple[ResearchCase, ResearchRun]:
    """Transition ``running -> failed`` on the run and the case."""

    _require_aware(failed_at, "failed_at")
    failed_run = run.fail(error_summary=error_summary, occurred_at=failed_at)
    failed_case = case.transition(
        ResearchCaseStatus.FAILED, occurred_at=failed_at
    )
    return failed_case, failed_run


def execute_research_attempt(
    *,
    case: ResearchCase,
    evidence_pack: EvidencePack,
    playbook: ResearchPlaybook,
    runner: ResearchRunner,
    started_at: datetime,
    finished_at: datetime,
) -> tuple[ResearchCase, ResearchRun, ResearchResult]:
    """Walk ``ready -> running -> draft -> succeeded -> completed``."""

    _require_aware(started_at, "started_at")
    _require_aware(finished_at, "finished_at")
    if finished_at < started_at:
        raise ValueError("finished_at must be on or after started_at")
    running_case, started_run = start_research_attempt(
        case=case,
        evidence_pack=evidence_pack,
        playbook=playbook,
        runner=runner,
        started_at=started_at,
    )
    draft = runner.run(
        case=running_case,
        run=started_run,
        evidence_pack=evidence_pack,
        playbook=playbook,
        started_at=started_at,
    )
    completed_case, succeeded_run, result = complete_research_attempt(
        case=running_case,
        run=started_run,
        draft=draft,
        evidence_pack=evidence_pack,
        finished_at=finished_at,
    )
    return completed_case, succeeded_run, result


__all__ = [
    "ResearchPlaybook",
    "ResearchRunner",
    "ResearchRunnerDraft",
    "ResearchRunnerFailure",
    "complete_research_attempt",
    "execute_research_attempt",
    "fail_research_attempt",
    "start_research_attempt",
]