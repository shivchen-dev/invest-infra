"""Regression tests for the :class:`ResearchRunner` port and orchestration helpers.

The :class:`FakeResearchRunner` test fake lives here because the domain
package owns no concrete runner; production adapters (PR-6 / PR-7)
satisfy the :class:`ResearchRunner` protocol directly. The tests
cover only behaviour that catches regressions:

- dataclass validation / normalization for :class:`ResearchPlaybook`
  and :class:`ResearchRunnerDraft`,
- :class:`FakeResearchRunner` contract: protocol satisfaction,
  determinism, whitelist filtering, refusal of mis-bound runs,
  ``fail_with`` propagation, no-mutate invariant on the supplied pack,
- alignment gate: ``EvidencePack.case.case_id`` must be a UUID that
  equals ``ResearchCase.case_id``; string or ``None`` ``case_id``
  values are rejected before the state-machine guard runs,
- orchestration order: ``complete_research_attempt`` rebinds the
  case/run/pack trio (states + identity keys) before validating the
  draft and before the run transitions to ``succeeded``,
- legal-state rejection: terminal cases refuse a fresh start, and
  ``start_research_attempt`` rejects anything but a ``READY`` case,
- idempotency scope: terminal state refuses double completion and
  same inputs produce byte-stable content; persistence dedup is out
  of scope.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from invest_domain import (
    CaseContext,
    EvidencePack,
    ResearchCase,
    ResearchCaseStatus,
    ResearchPlaybook,
    ResearchResult,
    ResearchRun,
    ResearchRunner,
    ResearchRunnerDraft,
    ResearchRunnerFailure,
    ResearchRunStatus,
    complete_research_attempt,
    execute_research_attempt,
    fail_research_attempt,
    start_research_attempt,
)
from invest_domain.research.canonical import compute_pack_hash
from packages.domain.tests.test_research_evidence import _pack

_BASE = datetime(2026, 3, 6, 7, 0, tzinfo=UTC)
_READY_AT = _BASE + timedelta(minutes=5)
_STARTED = _BASE + timedelta(minutes=10)
_SUCCEEDED_AT = _BASE + timedelta(minutes=12)
_FAILED_AT = _BASE + timedelta(minutes=14)
_PLAYBOOK_KEY = "etf_medium_term_assessment"
_PLAYBOOK_VERSION = "v0.1.0"
_RUNNER_CASE_ID = UUID("11111111-1114-4118-9111-111111111111")
_OTHER_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_OTHER_PACK_ID = UUID("33333333-3334-4338-9333-333333333333")


@dataclass
class FakeResearchRunner:
    """Deterministic in-process :class:`ResearchRunner` test fake."""

    runner_key: str = "fake-runner-v1"
    adapter_version: str = "fake-adapter-v1"
    model_key: str = "fake-model-v1"
    model_version: str = "fake-model-v1"
    conclusion: str = "Evidence-backed assessment under the Fake Runner."
    risks: tuple[str, ...] = ("execution_risk",)
    fail_with: Exception | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def run(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
        started_at: datetime,
    ) -> ResearchRunnerDraft:
        if run.status is not ResearchRunStatus.RUNNING:
            raise ResearchRunnerFailure(
                f"FakeResearchRunner requires a running run, got {run.status.value!r}"
            )
        if run.evidence_pack_id != evidence_pack.pack_id:
            raise ResearchRunnerFailure(
                "run.evidence_pack_id does not match evidence_pack.pack_id"
            )
        if self.fail_with is not None:
            raise self.fail_with
        available = {item.factor_key for item in evidence_pack.factors}
        if playbook.cited_factor_keys:
            requested = tuple(
                key for key in playbook.cited_factor_keys if key in available
            )
            if not requested:
                raise ResearchRunnerFailure(
                    "playbook.cited_factor_keys contains no factor present "
                    "in the supplied EvidencePack"
                )
            factors = tuple(
                item for item in evidence_pack.factors if item.factor_key in requested
            )
        else:
            factors = evidence_pack.factors
        return ResearchRunnerDraft(
            conclusion=self.conclusion,
            risks=self.risks,
            evidence_ids=tuple(
                item.evidence_id for item in factors if item.evidence_id is not None
            ),
            report_markdown=(
                f"# {playbook.playbook_key}@{playbook.playbook_version}\n"
                f"pack_hash: {evidence_pack.pack_hash}\n"
            ),
            model_key=self.model_key,
            model_version=self.model_version,
            playbook_version=playbook.playbook_version,
            adapter_version=self.adapter_version,
            created_at=self.clock(),
        )


def _runner_pack(case_id: UUID | None = None) -> EvidencePack:
    """Return an :class:`EvidencePack` bound to a known :class:`UUID` ``case_id``.

    The shared ``_pack`` helper from :mod:`test_research_evidence` defaults
    ``CaseContext.case_id`` to a free-form string. The runner contract
    requires the pack's ``case.case_id`` to be a real :class:`UUID` that
    matches the :class:`ResearchCase`'s, so every runner test goes
    through this local helper.
    """

    return _pack(case_id=case_id or _RUNNER_CASE_ID)


def _ready_case(pack: EvidencePack) -> ResearchCase:
    """Return a ``READY`` :class:`ResearchCase` aligned to ``pack.case.case_id``."""

    case_id = pack.case.case_id
    if not isinstance(case_id, UUID):
        raise ValueError(
            "test fixture requires pack.case.case_id to be a UUID; "
            "construct the pack via _runner_pack()"
        )
    draft = ResearchCase(
        case_id=case_id,
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.DRAFT,
        created_at=_BASE,
        closed_at=None,
    )
    return draft.transition(ResearchCaseStatus.READY, occurred_at=_READY_AT)


def _started_run(case: ResearchCase, pack: EvidencePack) -> ResearchRun:
    return ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack.pack_id,
        runner_key="fake-runner-v1",
        playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=_STARTED)


def _playbook(cited_factor_keys: tuple[str, ...] = ()) -> ResearchPlaybook:
    return ResearchPlaybook(
        playbook_key=_PLAYBOOK_KEY,
        playbook_version=_PLAYBOOK_VERSION,
        cited_factor_keys=cited_factor_keys,
    )


def _frozen_clock(value: datetime) -> Callable[[], datetime]:
    return lambda: value


def _full_run(
    *, pack: EvidencePack, case: ResearchCase, runner: FakeResearchRunner
) -> tuple[ResearchCase, ResearchRun, ResearchResult]:
    return execute_research_attempt(
        case=case,
        evidence_pack=pack,
        playbook=_playbook(),
        runner=runner,
        started_at=_STARTED,
        finished_at=_SUCCEEDED_AT,
    )


def test_playbook_validates_and_normalizes_fields() -> None:
    playbook = ResearchPlaybook(
        playbook_key=" etf_medium_term_assessment ",
        playbook_version=" v0.1.0 ",
        cited_factor_keys=("return_20d", "distance_ma20", "return_20d"),
    )
    assert playbook.playbook_key == "etf_medium_term_assessment"
    assert playbook.playbook_version == "v0.1.0"
    assert playbook.cited_factor_keys == ("distance_ma20", "return_20d")
    with pytest.raises(ValueError, match="non-blank"):
        ResearchPlaybook(playbook_key=" ", playbook_version="v0.1.0")
    with pytest.raises(ValueError, match="non-blank"):
        ResearchPlaybook(playbook_key="ok", playbook_version=" ")


def test_runner_draft_validates_and_normalizes_fields() -> None:
    pack = _runner_pack()
    draft = ResearchRunnerDraft(
        conclusion=" conclusion ",
        risks=(" valuation ", "liquidity", "valuation"),
        evidence_ids=tuple(
            item.evidence_id for item in reversed(pack.factors) if item.evidence_id
        ),
        report_markdown=" report ",
        model_key="k",
        model_version="m",
        playbook_version="p",
        adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    assert draft.conclusion == "conclusion"
    assert draft.report_markdown == "report"
    assert draft.risks == ("liquidity", "valuation")
    assert draft.evidence_ids == tuple(
        sorted(item.evidence_id for item in pack.factors if item.evidence_id)
    )
    with pytest.raises(ValueError, match="at least one"):
        ResearchRunnerDraft(
            conclusion="c",
            risks=(),
            evidence_ids=(),
            report_markdown="r",
            model_key="k",
            model_version="m",
            playbook_version="p",
            adapter_version="a",
            created_at=_SUCCEEDED_AT,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchRunnerDraft(
            conclusion="c",
            risks=(),
            evidence_ids=("evi:a:factor.a:aaaaaaaaaaaa",),
            report_markdown="r",
            model_key="k",
            model_version="m",
            playbook_version="p",
            adapter_version="a",
            created_at=_SUCCEEDED_AT.replace(tzinfo=None),
        )


def test_fake_runner_satisfies_protocol() -> None:
    runner: ResearchRunner = FakeResearchRunner()
    assert isinstance(runner, ResearchRunner)
    assert runner.runner_key == "fake-runner-v1"
    assert runner.adapter_version == "fake-adapter-v1"


def test_fake_runner_is_deterministic_under_same_inputs() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(clock=_frozen_clock(_SUCCEEDED_AT))
    started_run = _started_run(case, pack)
    draft_a = runner.run(
        case=case, run=started_run, evidence_pack=pack,
        playbook=_playbook(), started_at=_STARTED,
    )
    draft_b = runner.run(
        case=case, run=started_run, evidence_pack=pack,
        playbook=_playbook(), started_at=_STARTED,
    )
    assert draft_a.conclusion == draft_b.conclusion
    assert draft_a.risks == draft_b.risks
    assert draft_a.evidence_ids == draft_b.evidence_ids
    assert draft_a.report_markdown == draft_b.report_markdown
    assert draft_a.created_at == draft_b.created_at == _SUCCEEDED_AT


def test_fake_runner_filters_by_playbook_whitelist() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    started_run = _started_run(case, pack)
    draft = FakeResearchRunner().run(
        case=case, run=started_run, evidence_pack=pack,
        playbook=_playbook(cited_factor_keys=("return_20d", "distance_ma20")),
        started_at=_STARTED,
    )
    expected = tuple(
        sorted(
            item.evidence_id for item in pack.factors
            if item.factor_key in ("distance_ma20", "return_20d") and item.evidence_id
        )
    )
    assert draft.evidence_ids == expected


def test_fake_runner_rejects_misalignment() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    started_run = _started_run(case, pack)
    with pytest.raises(ResearchRunnerFailure, match="cited_factor_keys"):
        FakeResearchRunner().run(
            case=case, run=started_run, evidence_pack=pack,
            playbook=_playbook(cited_factor_keys=("not-a-factor",)),
            started_at=_STARTED,
        )
    mismatched_run = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
        runner_key="fake-runner-v1",
        playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=_STARTED)
    with pytest.raises(ResearchRunnerFailure, match="evidence_pack_id"):
        FakeResearchRunner().run(
            case=case, run=mismatched_run, evidence_pack=pack,
            playbook=_playbook(), started_at=_STARTED,
        )
    queued = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack.pack_id,
        runner_key="fake-runner-v1",
        playbook_key=_PLAYBOOK_KEY,
    )
    with pytest.raises(ResearchRunnerFailure, match="running"):
        FakeResearchRunner().run(
            case=case, run=queued, evidence_pack=pack,
            playbook=_playbook(), started_at=_STARTED,
        )


def test_fake_runner_does_not_mutate_evidence_pack() -> None:
    pack = _runner_pack()
    snapshot_hash = compute_pack_hash(pack)
    snapshot_factors = pack.factors
    case = _ready_case(pack)
    started_run = _started_run(case, pack)
    FakeResearchRunner().run(
        case=case, run=started_run, evidence_pack=pack,
        playbook=_playbook(), started_at=_STARTED,
    )
    assert pack.factors is snapshot_factors
    assert compute_pack_hash(pack) == snapshot_hash


def test_start_research_attempt_aligns_identity_keys() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner()
    running_case, started_run = start_research_attempt(
        case=case, evidence_pack=pack, playbook=_playbook(),
        runner=runner, started_at=_STARTED,
    )
    assert running_case.status is ResearchCaseStatus.RUNNING
    assert started_run.status is ResearchRunStatus.RUNNING
    assert started_run.case_id == case.case_id
    assert started_run.evidence_pack_id == pack.pack_id
    assert started_run.runner_key == runner.runner_key
    assert started_run.playbook_key == _PLAYBOOK_KEY


def test_start_research_attempt_rejects_case_not_in_ready() -> None:
    pack = _runner_pack()
    draft_case = ResearchCase(
        case_id=pack.case.case_id,
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.DRAFT,
        created_at=_BASE,
        closed_at=None,
    )
    with pytest.raises(ValueError, match="READY"):
        start_research_attempt(
            case=draft_case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(), started_at=_STARTED,
        )


def test_start_research_attempt_rejects_mismatched_case_context() -> None:
    pack = _runner_pack()
    wrong_question = CaseContext(
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question="a different question",
        horizon=pack.case.horizon,
        case_id=pack.case.case_id,
    )
    mismatched_case = ResearchCase(
        case_id=pack.case.case_id,
        instrument_id=wrong_question.instrument_id,
        as_of_date=wrong_question.as_of_date,
        question=wrong_question.question,
        horizon=wrong_question.horizon,
        status=ResearchCaseStatus.READY,
        created_at=_BASE,
        closed_at=None,
    )
    with pytest.raises(ValueError, match="question"):
        start_research_attempt(
            case=mismatched_case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(), started_at=_STARTED,
        )


def test_complete_research_attempt_validates_draft_before_succeed() -> None:
    """Draft with foreign evidence IDs fails closed *before* the run succeeds."""

    pack = _runner_pack()
    case = _ready_case(pack)
    running_case, started_run = start_research_attempt(
        case=case, evidence_pack=pack, playbook=_playbook(),
        runner=FakeResearchRunner(), started_at=_STARTED,
    )
    forged = ResearchRunnerDraft(
        conclusion="ok", risks=(),
        evidence_ids=("evi:000000000000:factor.forged:000000000000",),
        report_markdown="r", model_key="k", model_version="m",
        playbook_version="p", adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    with pytest.raises(ValueError, match="not present in EvidencePack"):
        complete_research_attempt(
            case=running_case, run=started_run, draft=forged,
            evidence_pack=pack, finished_at=_SUCCEEDED_AT,
        )
    assert started_run.status is ResearchRunStatus.RUNNING


def test_complete_research_attempt_binds_immutable_result() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(clock=_frozen_clock(_SUCCEEDED_AT))
    running_case, started_run = start_research_attempt(
        case=case, evidence_pack=pack, playbook=_playbook(),
        runner=runner, started_at=_STARTED,
    )
    draft = runner.run(
        case=running_case, run=started_run, evidence_pack=pack,
        playbook=_playbook(), started_at=_STARTED,
    )
    completed_case, succeeded_run, result = complete_research_attempt(
        case=running_case, run=started_run, draft=draft,
        evidence_pack=pack, finished_at=_SUCCEEDED_AT,
    )
    assert isinstance(result, ResearchResult)
    assert completed_case.status is ResearchCaseStatus.COMPLETED
    assert completed_case.closed_at == _SUCCEEDED_AT
    assert succeeded_run.status is ResearchRunStatus.SUCCEEDED
    assert result.run_id == started_run.run_id
    assert result.evidence_pack_id == pack.pack_id
    assert result.evidence_ids == draft.evidence_ids


def test_fail_research_attempt_closes_case_and_run() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    running_case, started_run = start_research_attempt(
        case=case, evidence_pack=pack, playbook=_playbook(),
        runner=FakeResearchRunner(), started_at=_STARTED,
    )
    failed_case, failed_run = fail_research_attempt(
        case=running_case, run=started_run,
        error_summary=" provider timeout ", failed_at=_FAILED_AT,
    )
    assert failed_run.status is ResearchRunStatus.FAILED
    assert failed_run.error_summary == "provider timeout"
    assert failed_case.status is ResearchCaseStatus.FAILED
    assert failed_case.closed_at == _FAILED_AT


def test_execute_research_attempt_walks_happy_path() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(clock=_frozen_clock(_SUCCEEDED_AT))
    completed_case, succeeded_run, result = _full_run(
        pack=pack, case=case, runner=runner
    )
    assert completed_case.status is ResearchCaseStatus.COMPLETED
    assert succeeded_run.status is ResearchRunStatus.SUCCEEDED
    assert result.run_id == succeeded_run.run_id
    assert result.evidence_pack_id == pack.pack_id
    assert result.evidence_ids == tuple(
        sorted(item.evidence_id for item in pack.factors if item.evidence_id)
    )


def test_execute_research_attempt_rejects_invalid_timestamps() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    with pytest.raises(ValueError, match="finished_at"):
        execute_research_attempt(
            case=case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(),
            started_at=_SUCCEEDED_AT, finished_at=_STARTED,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        execute_research_attempt(
            case=case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(),
            started_at=_STARTED.replace(tzinfo=None), finished_at=_SUCCEEDED_AT,
        )


def test_execute_research_attempt_propagates_runner_failure() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(fail_with=ResearchRunnerFailure("provider timeout"))
    with pytest.raises(ResearchRunnerFailure, match="provider timeout"):
        execute_research_attempt(
            case=case, evidence_pack=pack, playbook=_playbook(),
            runner=runner, started_at=_STARTED, finished_at=_SUCCEEDED_AT,
        )


def test_terminal_case_rejects_double_lifecycle_advance() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(clock=_frozen_clock(_SUCCEEDED_AT))
    completed_case, succeeded_run, _ = _full_run(
        pack=pack, case=case, runner=runner
    )
    assert completed_case.status is ResearchCaseStatus.COMPLETED
    with pytest.raises(ValueError, match="READY"):
        start_research_attempt(
            case=completed_case, evidence_pack=pack, playbook=_playbook(),
            runner=runner, started_at=_STARTED + timedelta(minutes=30),
        )
    with pytest.raises(ValueError, match="illegal"):
        succeeded_run.succeed(occurred_at=_SUCCEEDED_AT + timedelta(minutes=1))


def test_same_inputs_produce_byte_stable_content() -> None:
    pack = _runner_pack()
    case = _ready_case(pack)
    runner = FakeResearchRunner(clock=_frozen_clock(_SUCCEEDED_AT))
    _, _, first = _full_run(pack=pack, case=case, runner=runner)
    _, _, second = _full_run(pack=pack, case=case, runner=runner)
    assert first.evidence_ids == second.evidence_ids
    assert first.conclusion == second.conclusion
    assert first.model_version == second.model_version
    assert first.adapter_version == second.adapter_version
    assert first.playbook_version == second.playbook_version


def _running_case_and_run(pack: EvidencePack) -> tuple[ResearchCase, ResearchRun]:
    case = _ready_case(pack)
    return start_research_attempt(
        case=case, evidence_pack=pack, playbook=_playbook(),
        runner=FakeResearchRunner(), started_at=_STARTED,
    )


def test_start_research_attempt_rejects_pack_with_non_uuid_case_id() -> None:
    """Pack constructed with a string ``case_id`` cannot be aligned with any case.

    The alignment gate runs *before* the state-machine guard, so even a
    perfectly-shaped :class:`ResearchCase` with a matching UUID raises
    when the pack carries a free-form string ``case_id``.
    """

    pack = _pack(case_id="case-runtime-string")
    case = ResearchCase(
        case_id=pack.case.case_id if isinstance(pack.case.case_id, UUID) else uuid4(),
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.READY,
        created_at=_BASE,
        closed_at=None,
    )
    with pytest.raises(ValueError, match="EvidencePack.case.case_id must be a UUID"):
        start_research_attempt(
            case=case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(), started_at=_STARTED,
        )


def test_start_research_attempt_rejects_pack_with_none_case_id() -> None:
    """Pack constructed with ``case_id=None`` cannot be aligned with any case."""

    pack = _pack(case_id=None)
    case = ResearchCase(
        case_id=uuid4(),
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.READY,
        created_at=_BASE,
        closed_at=None,
    )
    with pytest.raises(ValueError, match="EvidencePack.case.case_id must be a UUID"):
        start_research_attempt(
            case=case, evidence_pack=pack, playbook=_playbook(),
            runner=FakeResearchRunner(), started_at=_STARTED,
        )


def test_complete_research_attempt_rejects_mismatched_case_id() -> None:
    """``case.case_id != pack.case.case_id`` blocks the succeed transition."""

    pack = _runner_pack()
    running_case, started_run = _running_case_and_run(pack)
    mismatched_pack = _pack(case_id=_OTHER_CASE_ID)
    forged = ResearchRunnerDraft(
        conclusion="ok", risks=(),
        evidence_ids=tuple(
            item.evidence_id for item in mismatched_pack.factors
            if item.evidence_id
        ),
        report_markdown="r", model_key="k", model_version="m",
        playbook_version="p", adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    with pytest.raises(ValueError, match="must match"):
        complete_research_attempt(
            case=running_case, run=started_run, draft=forged,
            evidence_pack=mismatched_pack, finished_at=_SUCCEEDED_AT,
        )
    assert started_run.status is ResearchRunStatus.RUNNING


def test_complete_research_attempt_rejects_mismatched_run_case_id() -> None:
    """``run.case_id != case.case_id`` blocks the succeed transition."""

    pack = _runner_pack()
    running_case, _ = _running_case_and_run(pack)
    mismatched_run = ResearchRun.create(
        case_id=_OTHER_CASE_ID, evidence_pack_id=pack.pack_id,
        runner_key="fake-runner-v1", playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=_STARTED)
    forged = ResearchRunnerDraft(
        conclusion="ok", risks=(),
        evidence_ids=tuple(
            item.evidence_id for item in pack.factors if item.evidence_id
        ),
        report_markdown="r", model_key="k", model_version="m",
        playbook_version="p", adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    with pytest.raises(ValueError, match="ResearchRun.case_id"):
        complete_research_attempt(
            case=running_case, run=mismatched_run, draft=forged,
            evidence_pack=pack, finished_at=_SUCCEEDED_AT,
        )
    assert mismatched_run.status is ResearchRunStatus.RUNNING


def test_complete_research_attempt_rejects_mismatched_run_pack_id() -> None:
    """``run.evidence_pack_id != pack.pack_id`` blocks the succeed transition."""

    pack = _runner_pack()
    running_case, started_run = _running_case_and_run(pack)
    mismatched_run = ResearchRun.create(
        case_id=pack.case.case_id, evidence_pack_id=_OTHER_PACK_ID,
        runner_key="fake-runner-v1", playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=_STARTED)
    forged = ResearchRunnerDraft(
        conclusion="ok", risks=(),
        evidence_ids=tuple(
            item.evidence_id for item in pack.factors if item.evidence_id
        ),
        report_markdown="r", model_key="k", model_version="m",
        playbook_version="p", adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    with pytest.raises(ValueError, match="evidence_pack_id"):
        complete_research_attempt(
            case=running_case, run=mismatched_run, draft=forged,
            evidence_pack=pack, finished_at=_SUCCEEDED_AT,
        )
    assert mismatched_run.status is ResearchRunStatus.RUNNING


def test_complete_research_attempt_rejects_non_running_case() -> None:
    """``case.status`` must be ``RUNNING`` for completion."""

    pack = _runner_pack()
    _running_case, started_run = _running_case_and_run(pack)
    ready_case = _ready_case(pack)
    forged = ResearchRunnerDraft(
        conclusion="ok", risks=(),
        evidence_ids=tuple(
            item.evidence_id for item in pack.factors if item.evidence_id
        ),
        report_markdown="r", model_key="k", model_version="m",
        playbook_version="p", adapter_version="a",
        created_at=_SUCCEEDED_AT,
    )
    with pytest.raises(ValueError, match="RUNNING"):
        complete_research_attempt(
            case=ready_case, run=started_run, draft=forged,
            evidence_pack=pack, finished_at=_SUCCEEDED_AT,
        )