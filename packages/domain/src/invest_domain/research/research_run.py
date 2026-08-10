"""Pure domain aggregate for one research execution lifecycle.

Phase 1 of the evidence-driven Research lifecycle (ADR-0012 /
``docs/plan/invest-infra-evidence-driven-research-lifecycle-implementation-plan.md``)
introduces :class:`ResearchRun` as the execution owner for one attempt of
running a playbook against one evidence pack, and :class:`ResearchResult`
as the immutable conclusion record produced by a successful run.

The aggregate is intentionally infrastructure-free (no SQLAlchemy, no
Alembic, no FastAPI, no Dagster, no Provider SDK) so the application
layer can construct and evolve :class:`ResearchRun` /
:class:`ResearchResult` values without importing the storage layer.

State machine:

    queued -> running -> succeeded
               \\-> failed (retry -> queued, attempt++)
               \\-> cancelled
    queued -> cancelled

Terminal states are ``succeeded`` and ``cancelled`` — neither can
transition further. ``failed`` is resettable via :meth:`ResearchRun.retry`
which produces a fresh ``queued`` run with ``attempt += 1`` and all
execution timestamps/error cleared.

The aggregate deliberately does **not** store AI report bodies or
rankings — those belong to :class:`ResearchResult` (produced only after
the run's ``succeed`` method).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from invest_domain.research.models import EvidencePack


class ResearchRunStatus(StrEnum):
    """Lifecycle states for a :class:`ResearchRun`.

    Values and ordering are part of the public contract — adding new
    states requires a new ADR and a focused migration.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_LEGAL_TRANSITIONS: dict[ResearchRunStatus, frozenset[ResearchRunStatus]] = {
    ResearchRunStatus.QUEUED: frozenset(
        {ResearchRunStatus.RUNNING, ResearchRunStatus.CANCELLED}
    ),
    ResearchRunStatus.RUNNING: frozenset(
        {
            ResearchRunStatus.SUCCEEDED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        }
    ),
    ResearchRunStatus.FAILED: frozenset({ResearchRunStatus.QUEUED}),
    ResearchRunStatus.SUCCEEDED: frozenset(),
    ResearchRunStatus.CANCELLED: frozenset(),
}


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(
            f"ResearchRun.{field_name} must be a datetime, "
            f"got {type(value).__name__}"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"ResearchRun.{field_name} must be timezone-aware")
    return value


def _require_aware_optional(value: datetime | None, field_name: str) -> None:
    if value is None:
        return
    _require_aware(value, field_name)


@dataclass(frozen=True, slots=True)
class ResearchRun:
    """Immutable aggregate that owns one research execution lifecycle.

    Construction invariants:

    - ``run_id`` / ``case_id`` / ``evidence_pack_id`` are :class:`UUID`
      instances.
    - ``runner_key`` / ``playbook_key`` are non-blank strings.
    - ``status`` is one of the five :class:`ResearchRunStatus` values.
    - ``attempt`` is a positive int (``>= 1``).
    - ``started_at`` and ``finished_at`` are either ``None`` or
      timezone-aware :class:`datetime` instances; when both are set,
      ``finished_at >= started_at``.
    - ``error_summary`` is either ``None`` or a non-blank string.
    - ``queued`` runs carry no timestamps and no ``error_summary``.
    - ``running`` runs require ``started_at`` and forbid both
      ``finished_at`` and ``error_summary``.
    - Terminal states (``succeeded`` / ``failed`` / ``cancelled``)
      require ``finished_at``; only ``failed`` permits
      ``error_summary``.
    """

    run_id: UUID
    case_id: UUID
    evidence_pack_id: UUID
    runner_key: str
    playbook_key: str
    status: ResearchRunStatus
    attempt: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_summary: str | None = None
    evidence_bundle_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.evidence_bundle_id is not None and not isinstance(
            self.evidence_bundle_id, UUID
        ):
            raise TypeError(
                "ResearchRun.evidence_bundle_id must be a UUID, "
                f"got {type(self.evidence_bundle_id).__name__}"
            )
        if not isinstance(self.run_id, UUID):
            raise TypeError(
                "ResearchRun.run_id must be a UUID, "
                f"got {type(self.run_id).__name__}"
            )
        if not isinstance(self.case_id, UUID):
            raise TypeError(
                "ResearchRun.case_id must be a UUID, "
                f"got {type(self.case_id).__name__}"
            )
        if not isinstance(self.evidence_pack_id, UUID):
            raise TypeError(
                "ResearchRun.evidence_pack_id must be a UUID, "
                f"got {type(self.evidence_pack_id).__name__}"
            )
        if not isinstance(self.runner_key, str) or not self.runner_key.strip():
            raise ValueError("ResearchRun.runner_key must be a non-blank string")
        if not isinstance(self.playbook_key, str) or not self.playbook_key.strip():
            raise ValueError("ResearchRun.playbook_key must be a non-blank string")
        if not isinstance(self.status, ResearchRunStatus):
            raise TypeError(
                "ResearchRun.status must be a ResearchRunStatus, "
                f"got {type(self.status).__name__}"
            )
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise TypeError(
                "ResearchRun.attempt must be a positive int, "
                f"got {type(self.attempt).__name__}"
            )
        normalized_runner_key = self.runner_key.strip()
        normalized_playbook_key = self.playbook_key.strip()
        object.__setattr__(self, "runner_key", normalized_runner_key)
        object.__setattr__(self, "playbook_key", normalized_playbook_key)
        _require_aware_optional(self.started_at, "started_at")
        _require_aware_optional(self.finished_at, "finished_at")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError(
                f"ResearchRun.finished_at {self.finished_at.isoformat()} must be on or "
                f"after started_at {self.started_at.isoformat()}"
            )
        if self.error_summary is not None and (
            not isinstance(self.error_summary, str) or not self.error_summary.strip()
        ):
            raise ValueError(
                "ResearchRun.error_summary must be a non-blank string when set"
            )
        if self.status is ResearchRunStatus.QUEUED:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError(
                    "queued ResearchRun must not have timestamps"
                )
            if self.error_summary is not None:
                raise ValueError(
                    "queued ResearchRun must not have error_summary"
                )
        elif self.status is ResearchRunStatus.RUNNING:
            if self.started_at is None:
                raise ValueError(
                    "running ResearchRun requires started_at"
                )
            if self.finished_at is not None:
                raise ValueError(
                    "running ResearchRun must not have finished_at"
                )
            if self.error_summary is not None:
                raise ValueError(
                    "running ResearchRun must not have error_summary"
                )
        else:
            if self.finished_at is None:
                raise ValueError(
                    f"ResearchRun in status {self.status.value!r} requires finished_at"
                )
            if self.status is ResearchRunStatus.FAILED:
                if self.error_summary is None:
                    raise ValueError(
                        "failed ResearchRun requires error_summary"
                    )
            elif self.error_summary is not None:
                raise ValueError(
                    f"ResearchRun in status {self.status.value!r} must not have "
                    "error_summary"
                )

    @classmethod
    def create(
        cls,
        *,
        case_id: UUID,
        evidence_pack_id: UUID,
        runner_key: str,
        playbook_key: str,
        evidence_bundle_id: UUID | None = None,
    ) -> ResearchRun:
        """Return a fresh queued :class:`ResearchRun` with ``attempt=1``.

        A new ``run_id`` UUID is generated at construction; the run
        starts with no execution timestamps and no ``error_summary``.
        """

        return cls(
            run_id=uuid4(),
            case_id=case_id,
            evidence_pack_id=evidence_pack_id,
            runner_key=runner_key,
            playbook_key=playbook_key,
            status=ResearchRunStatus.QUEUED,
            attempt=1,
            evidence_bundle_id=evidence_bundle_id,
        )

    def _transition(
        self,
        target: ResearchRunStatus,
        *,
        occurred_at: datetime,
        error_summary: str | None = None,
    ) -> ResearchRun:
        """Return a new :class:`ResearchRun` reflecting the requested transition.

        ``occurred_at`` must be a timezone-aware ``datetime``. When
        ``target`` is ``running``, ``occurred_at`` becomes
        ``started_at`` and ``finished_at`` is cleared. When ``target``
        is a terminal state (``succeeded``/``failed``/``cancelled``),
        ``occurred_at`` becomes ``finished_at`` and must not predate
        ``started_at``.

        Raises ``ValueError`` for illegal transitions, naive
        ``occurred_at``, ``finished_at < started_at``, and invalid
        ``error_summary`` payloads.
        """

        _require_aware(occurred_at, "occurred_at")
        legal = _LEGAL_TRANSITIONS[self.status]
        if target not in legal:
            raise ValueError(
                f"illegal ResearchRun status transition: "
                f"{self.status.value!r} -> {target.value!r}"
            )
        normalized_error: str | None = None
        if target is ResearchRunStatus.FAILED:
            if not isinstance(error_summary, str) or not error_summary.strip():
                raise ValueError("fail requires a non-blank error_summary")
            normalized_error = error_summary.strip()
        elif error_summary is not None:
            raise ValueError("error_summary may only be supplied when failing")

        if target is ResearchRunStatus.RUNNING:
            new_started_at: datetime | None = occurred_at
            new_finished_at: datetime | None = None
        else:
            new_started_at = self.started_at
            new_finished_at = occurred_at
            if new_started_at is not None and new_finished_at < new_started_at:
                raise ValueError(
                    f"ResearchRun.finished_at {new_finished_at.isoformat()} must be on or "
                    f"after started_at {new_started_at.isoformat()}"
                )
        return replace(
            self,
            status=target,
            started_at=new_started_at,
            finished_at=new_finished_at,
            error_summary=normalized_error,
        )

    def start(self, *, occurred_at: datetime) -> ResearchRun:
        """Transition ``queued`` → ``running`` stamping ``started_at``."""

        return self._transition(ResearchRunStatus.RUNNING, occurred_at=occurred_at)

    def succeed(self, *, occurred_at: datetime) -> ResearchRun:
        """Transition ``running`` → ``succeeded`` stamping ``finished_at``."""

        return self._transition(ResearchRunStatus.SUCCEEDED, occurred_at=occurred_at)

    def fail(
        self, *, error_summary: str, occurred_at: datetime
    ) -> ResearchRun:
        """Transition ``running`` → ``failed`` stamping ``finished_at`` and ``error_summary``."""

        return self._transition(
            ResearchRunStatus.FAILED,
            occurred_at=occurred_at,
            error_summary=error_summary,
        )

    def cancel(self, *, occurred_at: datetime) -> ResearchRun:
        """Transition ``queued`` or ``running`` → ``cancelled`` stamping ``finished_at``."""

        return self._transition(
            ResearchRunStatus.CANCELLED, occurred_at=occurred_at
        )

    def retry(self) -> ResearchRun:
        """Return a new ``queued`` :class:`ResearchRun` with ``attempt += 1``.

        Only ``failed`` runs may retry; ``succeeded``/``cancelled``
        are terminal. All execution timestamps and ``error_summary``
        are cleared so the next attempt starts from a clean slate.
        """

        if self.status is not ResearchRunStatus.FAILED:
            raise ValueError(
                "retry is only allowed for failed ResearchRun, "
                f"got {self.status.value!r}"
            )
        return replace(
            self,
            status=ResearchRunStatus.QUEUED,
            attempt=self.attempt + 1,
            started_at=None,
            finished_at=None,
            error_summary=None,
        )


@dataclass(frozen=True, slots=True)
class ResearchResult:
    """Immutable conclusion record produced by a succeeded :class:`ResearchRun`.

    Construction invariants:

    - ``result_id`` / ``run_id`` / ``evidence_pack_id`` are
      :class:`UUID` instances.
    - ``conclusion``, ``report_markdown``, ``model_key``,
      ``model_version``, ``playbook_version`` and ``adapter_version``
      are non-blank strings.
    - ``risks`` and ``evidence_ids`` are tuples of non-blank strings.
      ``risks`` may be empty; ``evidence_ids`` must contain at least
      one item.
    - Every ``evidence_ids`` entry must match a
      :attr:`FactorObservation.evidence_id` on the supplied
      :class:`EvidencePack`.
    - ``risks`` and ``evidence_ids`` are normalized (stripped),
      de-duplicated and sorted on construction.
    - ``created_at`` is a timezone-aware :class:`datetime`.
    - ``evidence_bundle_id`` is either ``None`` or a :class:`UUID`.
    - Construction never mutates the supplied :class:`EvidencePack`.
    """

    result_id: UUID
    run_id: UUID
    evidence_pack_id: UUID
    conclusion: str
    risks: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    report_markdown: str
    model_key: str
    model_version: str
    playbook_version: str
    adapter_version: str
    created_at: datetime
    evidence_bundle_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, UUID):
            raise TypeError(
                "ResearchResult.result_id must be a UUID, "
                f"got {type(self.result_id).__name__}"
            )
        if not isinstance(self.run_id, UUID):
            raise TypeError(
                "ResearchResult.run_id must be a UUID, "
                f"got {type(self.run_id).__name__}"
            )
        if not isinstance(self.evidence_pack_id, UUID):
            raise TypeError(
                "ResearchResult.evidence_pack_id must be a UUID, "
                f"got {type(self.evidence_pack_id).__name__}"
            )
        for field_name, value in (
            ("conclusion", self.conclusion),
            ("report_markdown", self.report_markdown),
            ("model_key", self.model_key),
            ("model_version", self.model_version),
            ("playbook_version", self.playbook_version),
            ("adapter_version", self.adapter_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"ResearchResult.{field_name} must be a non-blank string"
                )
        if not isinstance(self.risks, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.risks
        ):
            raise ValueError("ResearchResult.risks must be a tuple of non-blank strings")
        if not isinstance(self.evidence_ids, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.evidence_ids
        ):
            raise ValueError(
                "ResearchResult.evidence_ids must be a tuple of non-blank strings"
            )
        if not self.evidence_ids:
            raise ValueError("ResearchResult requires at least one evidence ID")
        _require_aware(self.created_at, "created_at")
        if self.evidence_bundle_id is not None and not isinstance(
            self.evidence_bundle_id, UUID
        ):
            raise TypeError(
                "ResearchResult.evidence_bundle_id must be a UUID, "
                f"got {type(self.evidence_bundle_id).__name__}"
            )

    @classmethod
    def create(
        cls,
        *,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        conclusion: str,
        risks: tuple[str, ...] = (),
        evidence_ids: tuple[str, ...] = (),
        report_markdown: str,
        model_key: str,
        model_version: str,
        playbook_version: str,
        adapter_version: str,
        created_at: datetime | None = None,
        evidence_bundle_id: UUID | None = None,
    ) -> ResearchResult:
        """Build a :class:`ResearchResult` from a succeeded run and its evidence pack.

        The supplied :class:`EvidencePack` is read but never mutated;
        ``risks`` and ``evidence_ids`` are normalized (stripped),
        de-duplicated and sorted. ``created_at`` defaults to the
        current UTC time when omitted.

        Raises ``ValueError`` if the run is not ``succeeded``, the
        evidence pack has no ``pack_id``, the run and pack IDs do not
        match, any string field is blank, ``risks``/``evidence_ids``
        contain non-string or blank entries, ``evidence_ids`` is empty,
        or any cited evidence ID is not present in the pack's factor
        observations.
        """

        if run.status is not ResearchRunStatus.SUCCEEDED:
            raise ValueError(
                "ResearchResult.create requires a succeeded run, "
                f"got {run.status.value!r}"
            )
        if evidence_pack.pack_id is None:
            raise ValueError("EvidencePack.pack_id must not be null")
        if run.evidence_pack_id != evidence_pack.pack_id:
            raise ValueError(
                "run and evidence pack IDs must be matching: "
                f"{run.evidence_pack_id} != {evidence_pack.pack_id}"
            )
        for field_name, value in (
            ("conclusion", conclusion),
            ("report_markdown", report_markdown),
            ("model_key", model_key),
            ("model_version", model_version),
            ("playbook_version", playbook_version),
            ("adapter_version", adapter_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{field_name} must be a non-blank string"
                )
        if any(
            not isinstance(item, str) or not item.strip() for item in risks
        ):
            raise ValueError("risks must be non-blank strings")
        if any(
            not isinstance(item, str) or not item.strip() for item in evidence_ids
        ):
            raise ValueError("evidence_ids must be non-blank strings")
        normalized_risks: tuple[str, ...] = tuple(
            sorted(
                {
                    item.strip()
                    for item in risks
                    if isinstance(item, str) and item.strip()
                }
            )
        )
        normalized_evidence_ids: tuple[str, ...] = tuple(
            sorted(
                {
                    item.strip()
                    for item in evidence_ids
                    if isinstance(item, str) and item.strip()
                }
            )
        )
        if not normalized_evidence_ids:
            raise ValueError("at least one evidence ID is required")
        valid_ids = {item.evidence_id for item in evidence_pack.factors}
        if any(item not in valid_ids for item in normalized_evidence_ids):
            raise ValueError(
                "every citation must exist in factor observations"
            )
        timestamp = created_at if created_at is not None else datetime.now(UTC)
        return cls(
            result_id=uuid4(),
            run_id=run.run_id,
            evidence_pack_id=evidence_pack.pack_id,
            conclusion=conclusion.strip(),
            risks=normalized_risks,
            evidence_ids=normalized_evidence_ids,
            report_markdown=report_markdown.strip(),
            model_key=model_key.strip(),
            model_version=model_version.strip(),
            playbook_version=playbook_version.strip(),
            adapter_version=adapter_version.strip(),
            created_at=timestamp,
            evidence_bundle_id=evidence_bundle_id,
        )


__all__ = ["ResearchResult", "ResearchRun", "ResearchRunStatus"]
