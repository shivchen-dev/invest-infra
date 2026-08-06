"""Pure domain aggregate for one research question lifecycle.

Phase 1 of the evidence-driven Research lifecycle (ADR-0012 /
``docs/plan/invest-infra-evidence-driven-research-lifecycle-implementation-plan.md``)
introduces :class:`ResearchCase` as the lifecycle owner for one question on
one instrument and as-of date. The aggregate is intentionally
infrastructure-free (no SQLAlchemy, no Alembic, no FastAPI, no Dagster, no
JiuwenSwarm SDK) so the application layer can construct and evolve
:class:`ResearchCase` values without importing the storage layer.

State machine:

    draft -> ready -> running -> completed
                        \\-> failed
                draft|ready -> cancelled

Terminal states (``completed`` / ``failed`` / ``cancelled``) are
irreversible; the only way to revisit a finished case is to create a new
one. Same-state transitions are rejected so that the audit log of
``occurred_at`` timestamps always records a real change.

The aggregate deliberately does **not** store AI report bodies, theses,
rankings, or factor values — those belong to :class:`EvidencePack`
(Research) and to the forthcoming ResearchRun/ResearchResult slices (AI).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from invest_domain.instruments.models import InstrumentId
from invest_domain.research.models import CaseContext


class ResearchCaseStatus(StrEnum):
    """Lifecycle states for a :class:`ResearchCase`.

    Mirrors the ``ResearchCase`` state machine frozen by ADR-0012 §"State
    ownership" and Phase 1 / Task 1.1 of the approved plan. Values and
    ordering are part of the public contract — adding new states requires
    a new ADR and a focused migration.
    """

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES: frozenset[ResearchCaseStatus] = frozenset(
    {
        ResearchCaseStatus.COMPLETED,
        ResearchCaseStatus.FAILED,
        ResearchCaseStatus.CANCELLED,
    }
)


_LEGAL_TRANSITIONS: dict[ResearchCaseStatus, frozenset[ResearchCaseStatus]] = {
    ResearchCaseStatus.DRAFT: frozenset(
        {ResearchCaseStatus.READY, ResearchCaseStatus.CANCELLED}
    ),
    ResearchCaseStatus.READY: frozenset(
        {ResearchCaseStatus.RUNNING, ResearchCaseStatus.CANCELLED}
    ),
    ResearchCaseStatus.RUNNING: frozenset(
        {ResearchCaseStatus.COMPLETED, ResearchCaseStatus.FAILED}
    ),
    ResearchCaseStatus.COMPLETED: frozenset(),
    ResearchCaseStatus.FAILED: frozenset(),
    ResearchCaseStatus.CANCELLED: frozenset(),
}


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"ResearchCase.{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class ResearchCase:
    """Immutable aggregate that owns one research question's lifecycle.

    Construction invariants:

    - ``case_id`` is a UUID.
    - ``instrument_id`` is an :class:`InstrumentId`.
    - ``as_of_date`` is a :class:`date`.
    - ``question`` / ``horizon`` are non-blank strings.
    - ``status`` is one of the six :class:`ResearchCaseStatus` values.
    - ``created_at`` is a timezone-aware datetime.
    - ``closed_at`` is either ``None`` (active states) or a
      timezone-aware datetime (terminal states); when set, it must
      not predate ``created_at`` so the snapshot represents a feasible
      lifecycle.
    - Terminal states (``completed``/``failed``/``cancelled``) require
      ``closed_at``; active states forbid it.
    - ``candidate_pool_run_id``, if provided, is a UUID.
    """

    case_id: UUID
    instrument_id: InstrumentId
    as_of_date: date
    question: str
    horizon: str
    status: ResearchCaseStatus
    created_at: datetime
    closed_at: datetime | None = None
    candidate_pool_run_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, UUID):
            raise TypeError(
                f"ResearchCase.case_id must be a UUID, got {type(self.case_id).__name__}"
            )
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError(
                "ResearchCase.instrument_id must be an InstrumentId, "
                f"got {type(self.instrument_id).__name__}"
            )
        if not isinstance(self.as_of_date, date):
            raise TypeError(
                "ResearchCase.as_of_date must be a date, "
                f"got {type(self.as_of_date).__name__}"
            )
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("ResearchCase.question must be a non-blank string")
        if not isinstance(self.horizon, str) or not self.horizon.strip():
            raise ValueError("ResearchCase.horizon must be a non-blank string")
        if not isinstance(self.status, ResearchCaseStatus):
            raise TypeError(
                "ResearchCase.status must be a ResearchCaseStatus, "
                f"got {type(self.status).__name__}"
            )
        if not isinstance(self.created_at, datetime):
            raise TypeError(
                "ResearchCase.created_at must be a datetime, "
                f"got {type(self.created_at).__name__}"
            )
        if (
            self.created_at.tzinfo is None
            or self.created_at.tzinfo.utcoffset(self.created_at) is None
        ):
            raise ValueError("ResearchCase.created_at must be timezone-aware")
        if self.closed_at is not None:
            if not isinstance(self.closed_at, datetime):
                raise TypeError(
                    "ResearchCase.closed_at must be a datetime or None, "
                    f"got {type(self.closed_at).__name__}"
                )
            if (
                self.closed_at.tzinfo is None
                or self.closed_at.tzinfo.utcoffset(self.closed_at) is None
            ):
                raise ValueError("ResearchCase.closed_at must be timezone-aware")
            if self.closed_at < self.created_at:
                raise ValueError(
                    "ResearchCase.closed_at "
                    f"{self.closed_at.isoformat()} must be on or after created_at "
                    f"{self.created_at.isoformat()}"
                )
        if (
            self.candidate_pool_run_id is not None
            and not isinstance(self.candidate_pool_run_id, UUID)
        ):
            raise TypeError(
                "ResearchCase.candidate_pool_run_id must be a UUID or None, "
                f"got {type(self.candidate_pool_run_id).__name__}"
            )
        if self.status in _TERMINAL_STATUSES:
            if self.closed_at is None:
                raise ValueError(
                    f"ResearchCase in terminal status {self.status.value!r} must set closed_at"
                )
        elif self.closed_at is not None:
            raise ValueError(
                f"ResearchCase in active status {self.status.value!r} must not set closed_at"
            )

    @classmethod
    def create(
        cls,
        *,
        instrument_id: InstrumentId,
        as_of_date: date,
        question: str,
        horizon: str,
        candidate_pool_run_id: UUID | None = None,
        created_at: datetime | None = None,
    ) -> ResearchCase:
        """Return a fresh draft :class:`ResearchCase`.

        A new ``case_id`` UUID is generated at construction; ``created_at``
        defaults to the current UTC time unless an explicit
        timezone-aware ``created_at`` is supplied (tests use the explicit
        form to keep the transition-time semantics deterministic).
        """

        timestamp = created_at if created_at is not None else datetime.now(UTC)
        return cls(
            case_id=uuid4(),
            instrument_id=instrument_id,
            as_of_date=as_of_date,
            question=question,
            horizon=horizon,
            status=ResearchCaseStatus.DRAFT,
            created_at=timestamp,
            closed_at=None,
            candidate_pool_run_id=candidate_pool_run_id,
        )

    def transition(
        self,
        target: ResearchCaseStatus,
        *,
        occurred_at: datetime,
    ) -> ResearchCase:
        """Return a new :class:`ResearchCase` reflecting the requested transition.

        The transition is governed by ADR-0012: ``draft -> ready``,
        ``ready -> running``, ``running -> completed|failed``,
        ``draft|ready -> cancelled``. Terminal states cannot transition.
        Same-state transitions are rejected so that ``occurred_at``
        always corresponds to a real change in the audit log.

        ``occurred_at`` must be a timezone-aware ``datetime`` and must
        not predate :attr:`created_at`. ``closed_at`` is stamped
        automatically on entry into ``completed``/``failed``/``cancelled``;
        active transitions keep ``closed_at`` cleared.

        Raises ``ValueError`` for illegal transitions, same-state
        transitions, naive ``occurred_at``, and ``occurred_at`` before
        ``created_at``.
        """

        _require_aware(occurred_at, "occurred_at")
        if target is self.status:
            raise ValueError(
                f"ResearchCase transition to the same state {target.value!r} is not allowed"
            )
        legal = _LEGAL_TRANSITIONS[self.status]
        if target not in legal:
            raise ValueError(
                f"illegal ResearchCase status transition: {self.status.value!r} -> {target.value!r}"
            )
        if occurred_at < self.created_at:
            raise ValueError(
                "ResearchCase transition occurred_at "
                f"{occurred_at.isoformat()} must be on or after created_at "
                f"{self.created_at.isoformat()}"
            )
        closed_at: datetime | None = (
            occurred_at if target in _TERMINAL_STATUSES else None
        )
        return replace(self, status=target, closed_at=closed_at)

    def to_case_context(self) -> CaseContext:
        """Return an existing :class:`CaseContext` snapshot for this case.

        ``CaseContext`` is the immutable snapshot embedded in
        :class:`EvidencePack`; the projection carries the same
        instrument/date/question/horizon together with the case's
        ``case_id`` so downstream evidence can be traced back to the
        lifecycle aggregate. Lifecycle state itself is intentionally
        not represented on :class:`CaseContext`.
        """

        return CaseContext(
            instrument_id=self.instrument_id,
            as_of_date=self.as_of_date,
            question=self.question,
            horizon=self.horizon,
            case_id=self.case_id,
        )


__all__ = ["ResearchCase", "ResearchCaseStatus"]
