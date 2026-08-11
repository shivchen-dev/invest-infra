"""Pipeline application service for PR-6 Slice 3 research orchestration.

Slice 3 wires the deterministic :class:`JiuwenSwarmResearchRunner`
(Slice 1) and the slice-2 subprocess transport together with the PR-5.5
Unit-of-Work repositories so a queued :class:`ResearchRun` can be driven
to a terminal state without leaking transport-layer vocabulary into the
domain port.

The service has a single public entry point,
:meth:`ResearchOrchestrationService.execute`, that takes a
``run_id`` UUID and returns a :class:`ResearchOrchestrationOutcome`.

Transaction boundaries (mirroring the plan):

- **Tx1 — load + queued→running:** the case, run, and immutable
  evidence pack are loaded together; the case is advanced
  ``ready → running`` and the run ``queued → running`` in one
  UoW that commits. A persisted result for the ``run_id`` is
  surfaced as an idempotent replay with no gateway call.
- **External call:** the runner's ``run_with_identity`` is invoked
  *outside* the transaction so a long-running gateway submission
  never holds a database lock.
- **Tx2 — succeed/fail:** on acceptance, the run / case are
  advanced to ``succeeded`` / ``completed``, the
  :class:`ResearchResult` is persisted, and the external identity
  pair is bound. On uncertain timeout the external identity is
  bound but the run / case stay ``running`` so a duplicate
  callback can reconcile. On other adapter failures the run / case
  are transitioned to ``failed`` with a safe summary.

Every failure mode that crosses the transaction boundary is mapped
to a deterministic exception so the calling Dagster asset / API
can drive retry or fail-closed policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from invest_domain.research import (
    ContextProjection,
    EvidencePack,
    ResearchCase,
    ResearchPlaybook,
    ResearchResult,
    ResearchRunnerDraft,
    complete_research_attempt,
    fail_research_attempt,
)
from invest_domain.research.research_case import ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_storage.unit_of_work import UnitOfWork

from invest_pipeline.adapters.jiuwenswarm.errors import (
    JiuwenSwarmError,
    JiuwenSwarmTimeoutUncertainError,
)
from invest_pipeline.adapters.jiuwenswarm.runner import JiuwenSwarmRunOutcome
from invest_pipeline.research_context_projection import (
    ContextProjectionLoadError,
    load_context_projection,
)

__all__ = [
    "ClockFactory",
    "ResearchOrchestrationConflictError",
    "ResearchOrchestrationFailedError",
    "ResearchOrchestrationInputError",
    "ResearchOrchestrationOutcome",
    "ResearchOrchestrationReconciliationRequiredError",
    "ResearchOrchestrationService",
    "ResearchOrchestrationUncertainError",
    "ResearchRunnerWithIdentity",
    "UnitOfWorkFactory",
]


UnitOfWorkFactory = Callable[[], UnitOfWork]
ClockFactory = Callable[[], datetime]


class ResearchRunnerWithIdentity(Protocol):
    """Structural port the orchestrator needs from a :class:`ResearchRunner`.

    The Slice 3 seam is :meth:`JiuwenSwarmResearchRunner.run_with_identity`;
    a structural protocol keeps the orchestrator free of the
    JiuwenSwarm-specific import while still allowing the existing
    :class:`JiuwenSwarmResearchRunner` to satisfy it (a runtime
    ``isinstance`` check is intentionally avoided so unit tests can
    inject a hand-rolled double).
    """

    runner_key: str
    adapter_version: str

    def run_with_identity(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        playbook: ResearchPlaybook,
        started_at: datetime,
        projection: ContextProjection | None = None,
    ) -> JiuwenSwarmRunOutcome: ...


# ---------------------------------------------------------------------------
# Outcome + error taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResearchOrchestrationOutcome:
    """Return shape of :meth:`ResearchOrchestrationService.execute`.

    ``result`` is set on the success and replay paths; ``replay`` is
    ``True`` when the existing :class:`ResearchResult` was returned
    without invoking the gateway. ``case`` / ``run`` always carry the
    terminal or in-flight state observed after the call (replay may
    surface a ``completed`` case / ``succeeded`` run).
    """

    case: ResearchCase
    run: ResearchRun
    result: ResearchResult | None
    replay: bool = False


class ResearchOrchestrationInputError(ValueError):
    """Raised when the run / case / pack trio cannot be loaded or aligned."""


class ResearchOrchestrationConflictError(RuntimeError):
    """Raised when a CAS-aware transition fails because the row moved concurrently.

    Also raised when the gateway returns a different payload than the
    row that already has a persisted result (i.e. a duplicate callback
    with a divergent draft).
    """


class ResearchOrchestrationUncertainError(RuntimeError):
    """Raised when the gateway accepted the request but the local timeout fired.

    Carries the structured ``request_id`` / ``session_id`` identity pair
    the gateway echoed back so a duplicate-callback reconciliation
    worker can find the in-flight run by either field. The run / case
    remain in ``running`` (no terminal transition applied).
    """

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None,
        session_id: str | None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.session_id = session_id


class ResearchOrchestrationReconciliationRequiredError(RuntimeError):
    """Raised when the run is already ``running`` but has a bound external session.

    The orchestrator refuses to contact the gateway a second time on
    the same run because doing so would risk a duplicate result; the
    caller is expected to wait for the existing gateway callback or to
    reconcile the run via an operator-driven tool.
    """

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None,
        session_id: str | None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.session_id = session_id


class ResearchOrchestrationFailedError(RuntimeError):
    """Raised when the gateway reported a non-uncertain, non-replay failure."""


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------


_MAX_ERROR_SUMMARY_LEN = 500


def _truncate_summary(message: str, *, limit: int = _MAX_ERROR_SUMMARY_LEN) -> str:
    """Return ``message`` trimmed to <= ``limit`` characters.

    The run row carries a non-blank ``error_summary``; we coerce long
    transport-layer messages down to a safe length so a runaway helper
    trace cannot blow the database column budget.
    """

    stripped = message.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _coerce_outcome_identities(
    outcome: JiuwenSwarmRunOutcome,
) -> tuple[str, str]:
    """Return the ``(request_id, session_id)`` pair from ``outcome``."""

    return outcome.request_id, outcome.session_id


def _extract_identity_from_error(
    exc: JiuwenSwarmError,
) -> tuple[str | None, str | None]:
    """Return the structured ``(request_id, session_id)`` pair on ``exc``.

    The Slice 1 errors carry the identity pair as attributes; the
    helper centralises the read so the orchestrator code paths stay
    branch-free.
    """

    request_id = getattr(exc, "request_id", None)
    session_id = getattr(exc, "session_id", None)
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = None
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = None
    return request_id, session_id


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ResearchOrchestrationService:
    """Pipeline application service coordinating one research attempt lifecycle.

    The constructor takes the four collaborators needed to drive one
    slice-3 orchestration step:

    - ``runner``: the deterministic Slice-1 runner. The orchestrator
      uses the structural ``run_with_identity`` seam so any
      adapter-specific identities stay on the runner side.
    - ``playbook``: the :class:`ResearchPlaybook` the runner expects;
      the orchestrator does not mutate it.
    - ``uow_factory``: callable returning a fresh UoW. The factory is
      invoked once for each transaction the orchestrator needs.
    - ``clock``: callable returning a timezone-aware UTC datetime the
      orchestrator stamps on the lifecycle transitions.
    """

    def __init__(
        self,
        *,
        runner: ResearchRunnerWithIdentity,
        playbook: ResearchPlaybook,
        uow_factory: UnitOfWorkFactory,
        clock: ClockFactory,
    ) -> None:
        self._runner = runner
        self._playbook = playbook
        self._uow_factory = uow_factory
        self._clock = clock

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(self, run_id: UUID) -> ResearchOrchestrationOutcome:
        """Drive ``run_id`` through the ``queued|running → terminal`` lifecycle.

        Returns a :class:`ResearchOrchestrationOutcome` describing the
        terminal or in-flight state observed after the call. Raises
        a deterministic exception on every failure mode that crosses
        the transaction boundary.
        """

        started_at = self._require_aware_utc(self._clock())

        case, run, evidence_pack, projection = self._load_trio_tx1(run_id)
        self._validate_runner_playbook(run)

        if run.status is ResearchRunStatus.SUCCEEDED:
            existing_result = self._fetch_existing_result_tx1(run_id)
            if existing_result is None:
                raise ResearchOrchestrationConflictError(
                    f"ResearchRun {run.run_id!s} is in succeeded state but has "
                    "no persisted ResearchResult; this is an inconsistent "
                    "state that must be reconciled"
                )
            return ResearchOrchestrationOutcome(
                case=case, run=run, result=existing_result, replay=True
            )

        if run.status is ResearchRunStatus.RUNNING:
            existing_result = self._fetch_existing_result_tx1(run_id)
            if existing_result is not None:
                return ResearchOrchestrationOutcome(
                    case=case, run=run, result=existing_result, replay=True
                )
            raise self._reconciliation_required(
                run=run,
                message=(
                    f"ResearchRun {run.run_id!s} is already RUNNING without a "
                    "persisted result; refusing to contact the gateway a "
                    "second time on the same run"
                ),
            )

        queued_started = self._start_trio_tx1(
            case=case, run=run, started_at=started_at
        )

        try:
            outcome = self._runner.run_with_identity(
                case=queued_started.case,
                run=queued_started.run,
                evidence_pack=evidence_pack,
                playbook=self._playbook,
                started_at=started_at,
                projection=projection,
            )
        except JiuwenSwarmTimeoutUncertainError as exc:
            raise self._handle_uncertain_timeout(
                running_run=queued_started.run,
                exc=exc,
            ) from exc
        except JiuwenSwarmError as exc:
            raise self._handle_adapter_failure(
                running_case=queued_started.case,
                running_run=queued_started.run,
                exc=exc,
                finished_at=self._require_aware_utc(self._clock()),
            ) from exc

        request_id, session_id = _coerce_outcome_identities(outcome)
        draft = outcome.draft
        if draft is None:
            raise ResearchOrchestrationFailedError(
                f"Runner returned {outcome.acceptance.value!r} without a draft; "
                "this is an inconsistent adapter contract"
            )

        finished_at = self._require_aware_utc(self._clock())
        return self._succeed_trio_tx2(
            run=queued_started.run,
            evidence_pack=evidence_pack,
            draft=draft,
            request_id=request_id,
            session_id=session_id,
            finished_at=finished_at,
        )

    # ------------------------------------------------------------------
    # Tx1 — load / start
    # ------------------------------------------------------------------

    def _load_trio_tx1(
        self,
        run_id: UUID,
    ) -> tuple[ResearchCase, ResearchRun, EvidencePack, ContextProjection | None]:
        """Load the case/run/pack trio and optional projection in Tx1."""

        with self._uow_factory() as uow:
            run = uow.research_runs.get(run_id)
            if run is None:
                raise ResearchOrchestrationInputError(
                    f"ResearchRun {run_id!s} not found"
                )
            case = uow.research_cases.get(run.case_id)
            if case is None:
                raise ResearchOrchestrationInputError(
                    f"ResearchCase {run.case_id!s} referenced by run "
                    f"{run.run_id!s} not found"
                )
            evidence_pack = uow.research_evidence_packs.get_by_id(run.evidence_pack_id)
            if evidence_pack is None:
                raise ResearchOrchestrationInputError(
                    f"EvidencePack {run.evidence_pack_id!s} referenced by run "
                    f"{run.run_id!s} not found"
                )
            if evidence_pack.case.case_id != case.case_id:
                raise ResearchOrchestrationInputError(
                    f"EvidencePack {evidence_pack.pack_id!s} case.case_id "
                    f"{evidence_pack.case.case_id!s} does not match "
                    f"ResearchCase {case.case_id!s}"
                )
            projection = None
            if run.evidence_bundle_id is not None:
                bundle = uow.research_evidence_bundles.get_by_id(
                    run.evidence_bundle_id
                )
                if bundle is None:
                    raise ResearchOrchestrationInputError(
                        f"ResearchEvidenceBundle {run.evidence_bundle_id!s} "
                        f"referenced by run {run.run_id!s} not found"
                    )
                if bundle.research_case_id != case.case_id:
                    raise ResearchOrchestrationInputError(
                        f"ResearchEvidenceBundle {bundle.bundle_id!s} "
                        f"research_case_id {bundle.research_case_id!s} does "
                        f"not match ResearchCase {case.case_id!s}"
                    )
                if bundle.evidence_pack_id != evidence_pack.pack_id:
                    raise ResearchOrchestrationInputError(
                        f"ResearchEvidenceBundle {bundle.bundle_id!s} "
                        f"evidence_pack_id {bundle.evidence_pack_id!s} does "
                        f"not match EvidencePack {evidence_pack.pack_id!s}"
                    )
                try:
                    projection = load_context_projection(
                        uow,
                        case=case,
                        run=run,
                        evidence_pack=evidence_pack,
                    )
                except (ContextProjectionLoadError, ValueError) as exc:
                    raise ResearchOrchestrationInputError(
                        f"Could not load ContextProjection for ResearchRun "
                        f"{run.run_id!s}: {exc}"
                    ) from exc
            ctx = case.to_case_context()
            for label, lhs, rhs in (
                ("instrument_id", ctx.instrument_id, evidence_pack.case.instrument_id),
                ("as_of_date", ctx.as_of_date, evidence_pack.case.as_of_date),
                ("question", ctx.question, evidence_pack.case.question),
                ("horizon", ctx.horizon, evidence_pack.case.horizon),
            ):
                if lhs != rhs:
                    raise ResearchOrchestrationInputError(
                        f"ResearchCase.{label} must match EvidencePack.{label}"
                    )
            uow.commit()
            return case, run, evidence_pack, projection

    def _validate_runner_playbook(
        self,
        run: ResearchRun,
    ) -> None:
        """Reject mismatched runner / playbook before touching the database."""

        if run.runner_key != self._runner.runner_key:
            raise ResearchOrchestrationInputError(
                f"ResearchRun.runner_key {run.runner_key!r} does not match the "
                f"configured runner {self._runner.runner_key!r}"
            )
        if run.playbook_key != self._playbook.playbook_key:
            raise ResearchOrchestrationInputError(
                f"ResearchRun.playbook_key {run.playbook_key!r} does not match "
                f"the configured playbook {self._playbook.playbook_key!r}"
            )

    def _fetch_existing_result_tx1(
        self, run_id: UUID
    ) -> ResearchResult | None:
        """Return the persisted result for ``run_id`` if one already exists."""

        with self._uow_factory() as uow:
            result = uow.research_results.get_by_run_id(run_id)
            uow.commit()
            return result

    def _start_trio_tx1(
        self,
        *,
        case: ResearchCase,
        run: ResearchRun,
        started_at: datetime,
    ) -> _StartedTrio:
        """Persist the ``ready→running`` / ``queued→running`` transitions.

        The orchestrator drives the transitions through the domain
        ``transition`` methods and the repository ``save_transition``
        CAS path. A concurrent worker that already advanced the row
        is surfaced as :class:`ResearchOrchestrationConflictError`.
        """

        if case.status is ResearchCaseStatus.READY:
            running_case = case.transition(
                ResearchCaseStatus.RUNNING, occurred_at=started_at
            )
        elif case.status is ResearchCaseStatus.RUNNING:
            running_case = case
        else:
            raise ResearchOrchestrationInputError(
                f"ResearchCase {case.case_id!s} status {case.status.value!r} "
                "must be 'ready' or 'running' to start the gateway submission"
            )
        if run.status is ResearchRunStatus.QUEUED:
            running_run = run.start(occurred_at=started_at)
        elif run.status is ResearchRunStatus.RUNNING:
            running_run = run
        else:
            raise ResearchOrchestrationInputError(
                f"ResearchRun {run.run_id!s} status {run.status.value!r} "
                "must be 'queued' or 'running' to start the gateway submission"
            )

        with self._uow_factory() as uow:
            try:
                if case.status is ResearchCaseStatus.READY:
                    saved_case = uow.research_cases.save_transition(
                        ResearchCaseStatus.READY, running_case
                    )
                else:
                    saved_case = running_case
                if run.status is ResearchRunStatus.QUEUED:
                    saved_run = uow.research_runs.save_transition(
                        ResearchRunStatus.QUEUED, running_run
                    )
                else:
                    saved_run = running_run
            except Exception as exc:
                uow.rollback()
                raise ResearchOrchestrationConflictError(
                    f"ResearchRun {run.run_id!s} could not be advanced to "
                    f"running (status was {run.status.value!r}): {exc}"
                ) from exc
            uow.commit()
            return _StartedTrio(case=saved_case, run=saved_run)

    # ------------------------------------------------------------------
    # Tx2 — succeed / fail
    # ------------------------------------------------------------------

    def _succeed_trio_tx2(
        self,
        *,
        run: ResearchRun,
        evidence_pack: EvidencePack,
        draft: ResearchRunnerDraft,
        request_id: str,
        session_id: str,
        finished_at: datetime,
    ) -> ResearchOrchestrationOutcome:
        """Persist the running→succeeded lifecycle and the ResearchResult.

        The function performs a defensive reload before the CAS-aware
        ``save_transition`` so a duplicate callback that already
        succeeded the same ``run_id`` is rejected as a conflict and
        the previously persisted result is returned instead of
        producing a second result row.
        """

        with self._uow_factory() as uow:
            reloaded_run = uow.research_runs.get(run.run_id)
            if reloaded_run is None:
                raise ResearchOrchestrationInputError(
                    f"ResearchRun {run.run_id!s} disappeared between "
                    "gateway submission and Tx2"
                )
            reloaded_case = uow.research_cases.get(reloaded_run.case_id)
            if reloaded_case is None:
                raise ResearchOrchestrationInputError(
                    f"ResearchCase {reloaded_run.case_id!s} disappeared "
                    "between gateway submission and Tx2"
                )
            if (
                reloaded_run.status is not ResearchRunStatus.RUNNING
                or reloaded_case.status.value != "running"
            ):
                existing = uow.research_results.get_by_run_id(run.run_id)
                if existing is not None:
                    uow.commit()
                    return ResearchOrchestrationOutcome(
                        case=reloaded_case,
                        run=reloaded_run,
                        result=existing,
                        replay=True,
                    )
                raise ResearchOrchestrationConflictError(
                    f"ResearchRun {run.run_id!s} cannot be succeeded: "
                    f"reloaded status {reloaded_run.status.value!r} / "
                    f"case {reloaded_case.status.value!r} without an "
                    "existing ResearchResult"
                )

            duplicate = uow.research_runs.lookup_by_external_session_id(session_id)
            if duplicate is not None and duplicate.run_id != run.run_id:
                raise ResearchOrchestrationConflictError(
                    f"External session_id {session_id!r} is already bound "
                    f"to ResearchRun {duplicate.run_id!s}; refusing to "
                    f"succeed a second run {run.run_id!s} on the same session"
                )

            try:
                completed_case, succeeded_run, result = complete_research_attempt(
                    case=reloaded_case,
                    run=reloaded_run,
                    draft=draft,
                    evidence_pack=evidence_pack,
                    finished_at=finished_at,
                )
            except Exception as exc:
                uow.rollback()
                raise ResearchOrchestrationFailedError(
                    f"complete_research_attempt rejected the gateway draft "
                    f"for run {run.run_id!s}: {exc}"
                ) from exc

            saved_run = uow.research_runs.save_transition(
                ResearchRunStatus.RUNNING, succeeded_run
            )
            saved_case = uow.research_cases.save_transition(
                ResearchCaseStatus.RUNNING, completed_case
            )

            try:
                stored_result = uow.research_results.add(result)
            except Exception as exc:
                uow.rollback()
                raise ResearchOrchestrationConflictError(
                    f"ResearchResult persistence conflicted for run "
                    f"{run.run_id!s}: {exc}"
                ) from exc

            uow.research_runs.bind_external_identity(
                run.run_id,
                external_request_id=request_id,
                external_session_id=session_id,
            )

            uow.commit()
            return ResearchOrchestrationOutcome(
                case=saved_case, run=saved_run, result=stored_result
            )

    # ------------------------------------------------------------------
    # Failure handling
    # ------------------------------------------------------------------

    def _handle_uncertain_timeout(
        self,
        *,
        running_run: ResearchRun,
        exc: JiuwenSwarmTimeoutUncertainError,
    ) -> ResearchOrchestrationUncertainError:
        """Bind the identity pair but leave the run / case in ``running``."""

        request_id, session_id = _extract_identity_from_error(exc)
        with self._uow_factory() as uow:
            if request_id is not None or session_id is not None:
                uow.research_runs.bind_external_identity(
                    running_run.run_id,
                    external_request_id=request_id,
                    external_session_id=session_id,
                )
            uow.commit()
        return ResearchOrchestrationUncertainError(
            str(exc) or "JiuwenSwarm gateway timed out locally",
            request_id=request_id,
            session_id=session_id,
        )

    def _handle_adapter_failure(
        self,
        *,
        running_case: ResearchCase,
        running_run: ResearchRun,
        exc: JiuwenSwarmError,
        finished_at: datetime,
    ) -> ResearchOrchestrationFailedError:
        """Mark the run / case failed with a safe summary and surface the error."""

        request_id, session_id = _extract_identity_from_error(exc)
        summary = _truncate_summary(
            f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        )
        try:
            failed_case, failed_run = fail_research_attempt(
                case=running_case,
                run=running_run,
                error_summary=summary,
                failed_at=finished_at,
            )
        except Exception as domain_exc:
            raise ResearchOrchestrationFailedError(
                f"Could not transition ResearchRun {running_run.run_id!s} to "
                f"failed after adapter error: {domain_exc}"
            ) from domain_exc

        with self._uow_factory() as uow:
            try:
                uow.research_runs.save_transition(
                    ResearchRunStatus.RUNNING, failed_run
                )
                uow.research_cases.save_transition(
                    ResearchCaseStatus.RUNNING, failed_case
                )
                if request_id is not None or session_id is not None:
                    uow.research_runs.bind_external_identity(
                        running_run.run_id,
                        external_request_id=request_id,
                        external_session_id=session_id,
                    )
            except Exception as persist_exc:
                uow.rollback()
                raise ResearchOrchestrationFailedError(
                    f"Could not persist failed transition for "
                    f"ResearchRun {running_run.run_id!s}: {persist_exc}"
                ) from persist_exc
            uow.commit()

        message = (
            f"JiuwenSwarm adapter raised {type(exc).__name__} for run "
            f"{running_run.run_id!s}: {exc}"
        )
        return ResearchOrchestrationFailedError(message)

    # ------------------------------------------------------------------
    # Reconciliation / replay guards
    # ------------------------------------------------------------------

    def _reconciliation_required(
        self,
        *,
        run: ResearchRun,
        message: str,
    ) -> ResearchOrchestrationReconciliationRequiredError:
        return ResearchOrchestrationReconciliationRequiredError(
            message,
            request_id=None,
            session_id=None,
        )

    # ------------------------------------------------------------------
    # Clock validation
    # ------------------------------------------------------------------

    @staticmethod
    def _require_aware_utc(value: datetime) -> datetime:
        if not isinstance(value, datetime):
            raise ResearchOrchestrationInputError(
                f"clock must return a datetime, got {type(value).__name__}"
            )
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ResearchOrchestrationInputError(
                "clock must return a timezone-aware datetime"
            )
        return value


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StartedTrio:
    """The case / run after the queued→running CAS transition succeeded."""

    case: ResearchCase
    run: ResearchRun
