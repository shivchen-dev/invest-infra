"""Bind approved strategy evidence into versions and manage activation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from invest_domain.strategy import (
    StrategyApprovalError,
    StrategyAudit,
    StrategyAuditVerdict,
    StrategyDecision,
    StrategyDraft,
    StrategyVersion,
    StrategyVersionNotFoundError,
)
from invest_storage.unit_of_work import UnitOfWork

UnitOfWorkFactory = Callable[..., UnitOfWork]
Clock = Callable[[], datetime]


def _now_utc() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(UTC)


class StrategyGovernanceService:
    """Bind approved evidence and manage one-shot version activation.

    Each public call owns a fresh Unit-of-Work. Publish and activate commit
    only after their invariant checks pass; active-version lookup is read-only.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        authorized_approver_agent_ids: tuple[str, ...],
        clock: Clock = _now_utc,
    ) -> None:
        self._uow_factory = uow_factory
        self._authorized = tuple(authorized_approver_agent_ids)
        self._clock = clock

    def publish_approved_version(
        self,
        *,
        decision: StrategyDecision,
        decision_ref: str,
        decision_hash: str,
    ) -> StrategyVersion:
        """Validate bindings and authorization, persist, then commit.

        The Draft and Audit records are authoritative: their identities are
        resolved from :attr:`StrategyDecision.draft_id` and
        :attr:`StrategyDecision.audit_id`. Missing evidence, non-pass
        audits, mismatched hashes or identifiers, and unauthorized
        approvers raise :class:`StrategyApprovalError` before the version
        repository is called.
        """

        with self._uow_factory() as uow:
            draft = self._load_draft(uow, decision.draft_id)
            audit = self._load_audit(uow, decision.audit_id)
            self._verify_binding(draft, audit, decision)
            self._verify_verdict(audit)
            self._verify_approver(decision)
            version = self._build_version(
                draft, decision, decision_ref, decision_hash
            )
            stored = uow.strategy_versions.add(version)
            uow.commit()
            return stored

    def activate_version(
        self,
        *,
        strategy_id: UUID,
        version: str,
        at: datetime | None = None,
    ) -> StrategyVersion:
        """Activate by identity with a required version guard and commit."""

        activated_at = at if at is not None else self._clock()
        with self._uow_factory() as uow:
            current = uow.strategy_versions.get_by_id(strategy_id)
            if current is None:
                raise StrategyVersionNotFoundError(
                    f"StrategyVersion {strategy_id!s} not found; cannot activate"
                )
            if current.version != version:
                raise StrategyApprovalError(
                    "StrategyVersion.version mismatch: expected "
                    f"{version!r}, got {current.version!r}"
                )
            stored = uow.strategy_versions.activate(
                strategy_id, at=activated_at
            )
            uow.commit()
            return stored

    def get_active_version(
        self, strategy_key: str
    ) -> StrategyVersion | None:
        """Return the active version without committing."""

        with self._uow_factory() as uow:
            return uow.strategy_versions.get_active(strategy_key)

    @staticmethod
    def _load_draft(uow: UnitOfWork, draft_id: UUID) -> StrategyDraft:
        draft = uow.strategy_drafts.get_by_id(draft_id)
        if draft is None:
            raise StrategyApprovalError(
                f"StrategyDraft {draft_id!s} not found; cannot publish"
            )
        return draft

    @staticmethod
    def _load_audit(uow: UnitOfWork, audit_id: UUID) -> StrategyAudit:
        audit = uow.strategy_audits.get_by_id(audit_id)
        if audit is None:
            raise StrategyApprovalError(
                f"StrategyAudit {audit_id!s} not found; cannot publish"
            )
        return audit

    @staticmethod
    def _verify_binding(
        draft: StrategyDraft,
        audit: StrategyAudit,
        decision: StrategyDecision,
    ) -> None:
        if decision.draft_id != draft.draft_id:
            raise StrategyApprovalError(
                "StrategyDecision.draft_id does not match the supplied draft"
            )
        if decision.audit_id != audit.audit_id:
            raise StrategyApprovalError(
                "StrategyDecision.audit_id does not match the supplied audit"
            )
        if audit.draft_id != draft.draft_id:
            raise StrategyApprovalError(
                "StrategyAudit.draft_id does not match the supplied draft"
            )
        if draft.artifact_hash != decision.artifact_hash:
            raise StrategyApprovalError(
                "StrategyDecision.artifact_hash does not match the draft"
            )
        if audit.artifact_hash != draft.artifact_hash:
            raise StrategyApprovalError(
                "StrategyAudit.artifact_hash does not match the draft"
            )

    @staticmethod
    def _verify_verdict(audit: StrategyAudit) -> None:
        if audit.verdict is not StrategyAuditVerdict.PASS:
            raise StrategyApprovalError(
                "StrategyAudit.verdict must be PASS, got "
                f"{audit.verdict.value!r}"
            )

    def _verify_approver(self, decision: StrategyDecision) -> None:
        if decision.decided_by_agent_id not in self._authorized:
            raise StrategyApprovalError(
                "StrategyDecision.decided_by_agent_id "
                f"{decision.decided_by_agent_id!r} is not an authorized approver"
            )

    @staticmethod
    def _build_version(
        draft: StrategyDraft,
        decision: StrategyDecision,
        decision_ref: str,
        decision_hash: str,
    ) -> StrategyVersion:
        return StrategyVersion.create(
            strategy_key=draft.strategy_key,
            version=draft.proposed_version,
            artifact_ref=draft.artifact_ref,
            artifact_hash=draft.artifact_hash,
            source_hashes=tuple(
                source.content_hash for source in draft.source_refs
            ),
            decision_ref=decision_ref,
            decision_hash=decision_hash,
            decided_by_agent_id=decision.decided_by_agent_id,
            audit_id=decision.audit_id,
            approved_at=decision.decided_at,
            activated_at=None,
        )


__all__ = ["StrategyGovernanceService"]
