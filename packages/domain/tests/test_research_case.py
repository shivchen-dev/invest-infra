"""Public-domain tests for :mod:`invest_domain.research.research_case`.

The slice is the Phase 1 ResearchCase aggregate from
``docs/plan/invest-infra-evidence-driven-research-lifecycle-implementation-plan.md``
and ADR-0012. Tests exercise only the publicly exported
:class:`ResearchCase` interface; private helpers and internal
representation are intentionally out of scope.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from invest_domain import CaseContext, ResearchCase, ResearchCaseStatus
from invest_domain.instruments import InstrumentId

_INSTRUMENT_ID = InstrumentId(
    UUID("12345678-1234-5678-9234-567812345678")
)
_AS_OF_DATE = date(2026, 3, 6)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
_HORIZON = "20-60d"
_FROZEN_CREATED_AT = datetime(2026, 3, 6, 7, 0, tzinfo=UTC)


def _new_case(
    *,
    candidate_pool_run_id: UUID | None = None,
    created_at: datetime | None = _FROZEN_CREATED_AT,
) -> ResearchCase:
    """Build a draft :class:`ResearchCase` with stable inputs for tests."""

    return ResearchCase.create(
        instrument_id=_INSTRUMENT_ID,
        as_of_date=_AS_OF_DATE,
        question=_QUESTION,
        horizon=_HORIZON,
        candidate_pool_run_id=candidate_pool_run_id,
        created_at=created_at,
    )


def test_draft_creation_requires_nonblank_question() -> None:
    with pytest.raises(ValueError, match="question"):
        ResearchCase.create(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF_DATE,
            question="   ",
            horizon=_HORIZON,
            created_at=_FROZEN_CREATED_AT,
        )


def test_draft_creation_requires_nonblank_horizon() -> None:
    with pytest.raises(ValueError, match="horizon"):
        ResearchCase.create(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF_DATE,
            question=_QUESTION,
            horizon=" ",
            created_at=_FROZEN_CREATED_AT,
        )


def test_draft_creation_rejects_raw_uuid_for_instrument_id() -> None:
    with pytest.raises(TypeError, match="instrument_id"):
        ResearchCase.create(
            instrument_id=_INSTRUMENT_ID.value,
            as_of_date=_AS_OF_DATE,
            question=_QUESTION,
            horizon=_HORIZON,
            created_at=_FROZEN_CREATED_AT,
        )


def test_direct_construction_rejects_closed_at_before_created_at() -> None:
    earlier = _FROZEN_CREATED_AT - timedelta(minutes=1)
    with pytest.raises(ValueError, match="closed_at"):
        ResearchCase(
            case_id=UUID("11111111-2222-3333-4444-555555555555"),
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF_DATE,
            question=_QUESTION,
            horizon=_HORIZON,
            status=ResearchCaseStatus.COMPLETED,
            created_at=_FROZEN_CREATED_AT,
            closed_at=earlier,
        )


def test_draft_creation_field_surface_matches_contract() -> None:
    case = _new_case()
    assert isinstance(case.case_id, UUID)
    assert case.instrument_id == _INSTRUMENT_ID
    assert case.as_of_date == _AS_OF_DATE
    assert case.question == _QUESTION
    assert case.horizon == _HORIZON
    assert case.status is ResearchCaseStatus.DRAFT
    assert case.created_at == _FROZEN_CREATED_AT
    assert case.closed_at is None
    assert case.candidate_pool_run_id is None


def test_draft_to_ready_transition_returns_new_aggregate() -> None:
    occurred_at = _FROZEN_CREATED_AT + timedelta(minutes=10)
    case = _new_case()
    ready = case.transition(ResearchCaseStatus.READY, occurred_at=occurred_at)
    assert ready is not case
    assert ready.case_id == case.case_id
    assert ready.status is ResearchCaseStatus.READY
    assert ready.closed_at is None
    assert case.status is ResearchCaseStatus.DRAFT


def _transition_full(case: ResearchCase) -> ResearchCase:
    """Walk draft -> ready -> running -> completed."""

    t = _FROZEN_CREATED_AT
    case = case.transition(ResearchCaseStatus.READY, occurred_at=t + timedelta(minutes=5))
    case = case.transition(
        ResearchCaseStatus.RUNNING, occurred_at=t + timedelta(minutes=10)
    )
    case = case.transition(
        ResearchCaseStatus.COMPLETED, occurred_at=t + timedelta(minutes=15)
    )
    return case


def test_full_happy_path_stamps_closed_at_on_completed() -> None:
    completed_at = _FROZEN_CREATED_AT + timedelta(minutes=15)
    case = _transition_full(_new_case())
    assert case.status is ResearchCaseStatus.COMPLETED
    assert case.closed_at == completed_at


def test_running_to_failed_stamps_closed_at() -> None:
    t = _FROZEN_CREATED_AT
    case = _new_case().transition(ResearchCaseStatus.READY, occurred_at=t + timedelta(minutes=1))
    case = case.transition(
        ResearchCaseStatus.RUNNING, occurred_at=t + timedelta(minutes=2)
    )
    failed_at = t + timedelta(minutes=3)
    failed = case.transition(ResearchCaseStatus.FAILED, occurred_at=failed_at)
    assert failed.status is ResearchCaseStatus.FAILED
    assert failed.closed_at == failed_at


def test_draft_to_cancelled_stamps_closed_at() -> None:
    cancelled_at = _FROZEN_CREATED_AT + timedelta(minutes=1)
    case = _new_case().transition(ResearchCaseStatus.CANCELLED, occurred_at=cancelled_at)
    assert case.status is ResearchCaseStatus.CANCELLED
    assert case.closed_at == cancelled_at


def test_ready_to_cancelled_stamps_closed_at() -> None:
    t = _FROZEN_CREATED_AT
    case = _new_case().transition(ResearchCaseStatus.READY, occurred_at=t + timedelta(minutes=1))
    cancelled_at = t + timedelta(minutes=5)
    cancelled = case.transition(
        ResearchCaseStatus.CANCELLED, occurred_at=cancelled_at
    )
    assert cancelled.status is ResearchCaseStatus.CANCELLED
    assert cancelled.closed_at == cancelled_at


def test_active_transition_keeps_closed_at_none() -> None:
    t = _FROZEN_CREATED_AT
    case = _new_case()
    ready = case.transition(ResearchCaseStatus.READY, occurred_at=t + timedelta(minutes=1))
    running = ready.transition(
        ResearchCaseStatus.RUNNING, occurred_at=t + timedelta(minutes=2)
    )
    assert ready.closed_at is None
    assert running.closed_at is None


def test_terminal_states_cannot_transition() -> None:
    completed = _transition_full(_new_case())
    for target in (
        ResearchCaseStatus.READY,
        ResearchCaseStatus.RUNNING,
        ResearchCaseStatus.CANCELLED,
    ):
        with pytest.raises(ValueError, match="illegal ResearchCase status transition"):
            completed.transition(target, occurred_at=completed.closed_at)


def test_same_state_transition_is_rejected() -> None:
    case = _new_case()
    with pytest.raises(ValueError, match="same state"):
        case.transition(
            ResearchCaseStatus.DRAFT, occurred_at=_FROZEN_CREATED_AT + timedelta(minutes=1)
        )


def test_illegal_skip_transition_is_rejected() -> None:
    case = _new_case()
    with pytest.raises(ValueError, match="illegal ResearchCase status transition"):
        case.transition(
            ResearchCaseStatus.RUNNING, occurred_at=_FROZEN_CREATED_AT + timedelta(minutes=1)
        )


def test_transition_rejects_naive_occurred_at() -> None:
    case = _new_case()
    naive_dt = (_FROZEN_CREATED_AT + timedelta(minutes=1)).replace(tzinfo=None)
    with pytest.raises(ValueError, match="occurred_at"):
        case.transition(ResearchCaseStatus.READY, occurred_at=naive_dt)


def test_transition_rejects_occurred_at_before_created_at() -> None:
    case = _new_case()
    earlier = _FROZEN_CREATED_AT - timedelta(minutes=1)
    with pytest.raises(ValueError, match="created_at"):
        case.transition(ResearchCaseStatus.READY, occurred_at=earlier)


def test_transition_rejects_backward_completed_to_running() -> None:
    completed = _transition_full(_new_case())
    with pytest.raises(ValueError, match="illegal"):
        completed.transition(
            ResearchCaseStatus.RUNNING, occurred_at=completed.closed_at
        )


def test_to_case_context_returns_equivalent_context() -> None:
    case = _new_case()
    projected = case.to_case_context()
    assert isinstance(projected, CaseContext)
    assert projected.instrument_id == case.instrument_id
    assert projected.as_of_date == case.as_of_date
    assert projected.question == case.question
    assert projected.horizon == case.horizon
    assert projected.case_id == case.case_id
    assert isinstance(projected.case_id, UUID)


def test_to_case_context_works_after_transition() -> None:
    case = _transition_full(_new_case())
    projected = case.to_case_context()
    assert projected.case_id == case.case_id
    assert isinstance(projected.case_id, UUID)
    assert projected.question == _QUESTION


def test_create_accepts_optional_candidate_pool_run_id() -> None:
    pool_uuid = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    case = _new_case(candidate_pool_run_id=pool_uuid)
    assert case.candidate_pool_run_id == pool_uuid


def test_create_rejects_non_uuid_candidate_pool_run_id() -> None:
    with pytest.raises(TypeError, match="candidate_pool_run_id"):
        _new_case(candidate_pool_run_id="not-a-uuid")
