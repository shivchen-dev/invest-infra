"""Behavioral contracts for :class:`StrategyGovernanceService`."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.strategy import (
    DECISION_APPROVE,
    DECISION_SCHEMA_VERSION,
    SourceRef,
    StrategyApprovalError,
    StrategyAudit,
    StrategyAuditVerdict,
    StrategyDecision,
    StrategyDraft,
    StrategyVersion,
    StrategyVersionAlreadyActiveError,
    StrategyVersionNotFoundError,
)
from invest_pipeline.strategy_governance import StrategyGovernanceService

# Synthetic identifiers used across the suite.
DRAFT_ID: UUID = UUID("11111111-1111-1111-1111-111111111111")
AUDIT_ID: UUID = UUID("22222222-2222-2222-2222-222222222222")
STRATEGY_ID: UUID = UUID("33333333-3333-3333-3333-333333333333")
ARTIFACT_HASH = "a" * 64
SOURCE_HASH_A = "b" * 64
SOURCE_HASH_B = "c" * 64
DECISION_REF = "decisions/2026/08/sample.json"
DECISION_HASH = "d" * 64
REPORT_HASH = "e" * 64
APPROVER_PRIMARY = "cia:approver:alpha"
APPROVER_SECONDARY = "cia:approver:beta"
AUTHORIZED_APPROVERS: tuple[str, ...] = (APPROVER_PRIMARY, APPROVER_SECONDARY)
DECIDED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
ACTIVATED_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
STRATEGY_KEY = "sample-strategy"
ARTIFACT_REF = "strategies/sample/v1/strategy.json"
PROPOSED_VERSION = "v1"


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.strategy_drafts = MagicMock(name="strategy_drafts")
        self.strategy_audits = MagicMock(name="strategy_audits")
        self.strategy_versions = MagicMock(name="strategy_versions")
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


def _uow_factory(uow: _FakeUnitOfWork) -> MagicMock:
    def _factory(*_args: Any, **_kwargs: Any) -> _FakeUnitOfWork:
        return uow

    return MagicMock(name="UnitOfWorkFactory", side_effect=_factory)


def _build_draft(*, artifact_hash: str = ARTIFACT_HASH) -> StrategyDraft:
    return StrategyDraft.create(
        draft_id=DRAFT_ID,
        strategy_key=STRATEGY_KEY,
        proposed_version=PROPOSED_VERSION,
        artifact_ref=ARTIFACT_REF,
        artifact_hash=artifact_hash,
        source_refs=(
            SourceRef("sources/article-1.html", SOURCE_HASH_A),
            SourceRef("sources/article-2.html", SOURCE_HASH_B),
        ),
        validation_result={},
    )


def _build_audit(
    *,
    draft_id: UUID = DRAFT_ID,
    artifact_hash: str = ARTIFACT_HASH,
    verdict: StrategyAuditVerdict = StrategyAuditVerdict.PASS,
) -> StrategyAudit:
    return StrategyAudit(
        audit_id=AUDIT_ID,
        draft_id=draft_id,
        artifact_hash=artifact_hash,
        agentoa_task_id="agentoa:task:abc",
        auditor_agent_id="raa:auditor:1",
        verdict=verdict,
        findings=(),
        limitations=(),
        report_ref="audits/sample/report.md",
        report_hash=REPORT_HASH,
        audited_at=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )


def _build_decision(
    *,
    draft_id: UUID = DRAFT_ID,
    audit_id: UUID = AUDIT_ID,
    artifact_hash: str = ARTIFACT_HASH,
    decided_by_agent_id: str = APPROVER_PRIMARY,
    decided_at: datetime = DECIDED_AT,
) -> StrategyDecision:
    return StrategyDecision(
        schema_version=DECISION_SCHEMA_VERSION,
        draft_id=draft_id,
        artifact_hash=artifact_hash,
        audit_id=audit_id,
        decision=DECISION_APPROVE,
        decided_by="Approver Alpha",
        decided_by_agent_id=decided_by_agent_id,
        decided_at=decided_at,
        limitations=(),
        statement="Approve strategy v1",
    )


def _stamp_id(version: StrategyVersion, strategy_id: UUID) -> StrategyVersion:
    return StrategyVersion(
        strategy_id=strategy_id,
        strategy_key=version.strategy_key,
        version=version.version,
        artifact_ref=version.artifact_ref,
        artifact_hash=version.artifact_hash,
        source_hashes=version.source_hashes,
        decision_ref=version.decision_ref,
        decision_hash=version.decision_hash,
        decided_by_agent_id=version.decided_by_agent_id,
        audit_id=version.audit_id,
        approved_at=version.approved_at,
        activated_at=version.activated_at,
        created_at=version.created_at,
    )


def _wire_publish_happy_path(
    uow: _FakeUnitOfWork,
    *,
    audit: StrategyAudit | None = None,
    draft: StrategyDraft | None = None,
) -> tuple[StrategyDraft, StrategyAudit]:
    draft = draft or _build_draft()
    audit = audit or _build_audit()
    uow.strategy_drafts.get_by_id.return_value = draft
    uow.strategy_audits.get_by_id.return_value = audit
    uow.strategy_versions.add.side_effect = lambda version: _stamp_id(
        version, STRATEGY_ID
    )
    return draft, audit


class PublishHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.uow = _FakeUnitOfWork()
        self.factory = _uow_factory(self.uow)
        self.service = StrategyGovernanceService(
            uow_factory=self.factory,
            authorized_approver_agent_ids=AUTHORIZED_APPROVERS,
        )
        self.decision = _build_decision()

    def _publish(self) -> StrategyVersion:
        return self.service.publish_approved_version(
            draft_id=DRAFT_ID,
            audit_id=AUDIT_ID,
            expected_strategy_key=STRATEGY_KEY,
            expected_version=PROPOSED_VERSION,
            decision=self.decision,
            decision_ref=DECISION_REF,
            decision_hash=DECISION_HASH,
        )

    def test_publish_returns_strategy_version_with_draft_metadata(self) -> None:
        _wire_publish_happy_path(self.uow)

        stored = self._publish()

        self.assertIsInstance(stored, StrategyVersion)
        self.assertEqual(stored.strategy_id, STRATEGY_ID)
        self.assertEqual(stored.strategy_key, STRATEGY_KEY)
        self.assertEqual(stored.version, PROPOSED_VERSION)
        self.assertEqual(stored.artifact_ref, ARTIFACT_REF)
        self.assertEqual(stored.artifact_hash, ARTIFACT_HASH)
        self.assertIsNone(stored.activated_at)
        self.assertEqual(stored.audit_id, AUDIT_ID)
        self.assertEqual(stored.decided_by_agent_id, APPROVER_PRIMARY)
        self.assertEqual(stored.approved_at, DECIDED_AT)
        self.assertEqual(stored.decision_ref, DECISION_REF)
        self.assertEqual(stored.decision_hash, DECISION_HASH)
        self.assertEqual(stored.source_hashes, (SOURCE_HASH_A, SOURCE_HASH_B))
        self.assertTrue(self.uow.committed, "publish must commit on success")
        self.uow.strategy_versions.add.assert_called_once()
        self.factory.assert_called_once()
        self.assertEqual(self.factory.call_args.args, ())


class PublishNegativeTests(unittest.TestCase):
    """Every rejected publish must avoid both add and commit."""

    def test_publish_rejects_invariant_matrix(self) -> None:
        cases = (
            ("missing draft", None, _build_audit(), _build_decision(), AUTHORIZED_APPROVERS),
            ("missing audit", _build_draft(), None, _build_decision(), AUTHORIZED_APPROVERS),
            (
                "strategy key binding",
                _build_draft(),
                _build_audit(),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "strategy version binding",
                _build_draft(),
                _build_audit(),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "decision draft binding",
                _build_draft(),
                _build_audit(),
                _build_decision(draft_id=uuid4()),
                AUTHORIZED_APPROVERS,
            ),
            (
                "decision audit binding",
                _build_draft(),
                _build_audit(),
                _build_decision(audit_id=uuid4()),
                AUTHORIZED_APPROVERS,
            ),
            (
                "audit draft binding",
                _build_draft(),
                _build_audit(draft_id=uuid4()),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "audit artifact binding",
                _build_draft(),
                _build_audit(artifact_hash="f" * 64),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "decision artifact binding",
                _build_draft(),
                _build_audit(),
                _build_decision(artifact_hash="0" * 64),
                AUTHORIZED_APPROVERS,
            ),
            (
                "changes-required verdict",
                _build_draft(),
                _build_audit(verdict=StrategyAuditVerdict.CHANGES_REQUIRED),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "reject verdict",
                _build_draft(),
                _build_audit(verdict=StrategyAuditVerdict.REJECT),
                _build_decision(),
                AUTHORIZED_APPROVERS,
            ),
            (
                "unauthorized approver",
                _build_draft(),
                _build_audit(),
                _build_decision(decided_by_agent_id="cia:approver:rogue"),
                AUTHORIZED_APPROVERS,
            ),
            (
                "empty authorization",
                _build_draft(),
                _build_audit(),
                _build_decision(),
                (),
            ),
        )

        for name, draft, audit, decision, authorized in cases:
            with self.subTest(name=name):
                uow = _FakeUnitOfWork()
                uow.strategy_drafts.get_by_id.return_value = draft
                uow.strategy_audits.get_by_id.return_value = audit
                service = StrategyGovernanceService(
                    uow_factory=_uow_factory(uow),
                    authorized_approver_agent_ids=authorized,
                )

                with self.assertRaises(StrategyApprovalError):
                    service.publish_approved_version(
                        draft_id=DRAFT_ID,
                        audit_id=AUDIT_ID,
                        expected_strategy_key=(
                            "other-strategy"
                            if name == "strategy key binding"
                            else STRATEGY_KEY
                        ),
                        expected_version=(
                            "v2"
                            if name == "strategy version binding"
                            else PROPOSED_VERSION
                        ),
                        decision=decision,
                        decision_ref=DECISION_REF,
                        decision_hash=DECISION_HASH,
                    )

                self.assertFalse(uow.committed)
                uow.strategy_versions.add.assert_not_called()


class ActivateVersionTests(unittest.TestCase):
    """Activation wires the supplied ``at`` and the repository's CAS."""

    def setUp(self) -> None:
        self.uow = _FakeUnitOfWork()
        self.factory = _uow_factory(self.uow)
        self.service = StrategyGovernanceService(
            uow_factory=self.factory,
            authorized_approver_agent_ids=(),
        )

    def _seed_version(
        self,
        *,
        version: str = PROPOSED_VERSION,
        activated_at: datetime | None = None,
    ) -> StrategyVersion:
        return StrategyVersion(
            strategy_id=STRATEGY_ID,
            strategy_key=STRATEGY_KEY,
            version=version,
            artifact_ref=ARTIFACT_REF,
            artifact_hash=ARTIFACT_HASH,
            source_hashes=(SOURCE_HASH_A, SOURCE_HASH_B),
            decision_ref=DECISION_REF,
            decision_hash=DECISION_HASH,
            decided_by_agent_id=APPROVER_PRIMARY,
            audit_id=AUDIT_ID,
            approved_at=DECIDED_AT,
            activated_at=activated_at,
            created_at=DECIDED_AT,
        )

    def test_activate_happy_path(self) -> None:
        seeded = self._seed_version()
        self.uow.strategy_versions.get_by_id.return_value = seeded
        activated = self._seed_version(activated_at=ACTIVATED_AT)
        self.uow.strategy_versions.activate.return_value = activated

        stored = self.service.activate_version(
            strategy_id=STRATEGY_ID, version=PROPOSED_VERSION, at=ACTIVATED_AT
        )

        self.assertEqual(stored.activated_at, ACTIVATED_AT)
        self.assertTrue(self.uow.committed)
        self.uow.strategy_versions.activate.assert_called_once_with(
            STRATEGY_ID, at=ACTIVATED_AT
        )

    def test_activate_missing_version_raises_not_found(self) -> None:
        self.uow.strategy_versions.get_by_id.return_value = None

        with self.assertRaises(StrategyVersionNotFoundError):
            self.service.activate_version(
                strategy_id=STRATEGY_ID,
                version=PROPOSED_VERSION,
                at=ACTIVATED_AT,
            )

        self.assertFalse(self.uow.committed)
        self.uow.strategy_versions.activate.assert_not_called()

    def test_activate_version_mismatch_raises_approval_error(self) -> None:
        self.uow.strategy_versions.get_by_id.return_value = self._seed_version(
            version="v2"
        )

        with self.assertRaises(StrategyApprovalError):
            self.service.activate_version(
                strategy_id=STRATEGY_ID,
                version=PROPOSED_VERSION,
                at=ACTIVATED_AT,
            )

        self.assertFalse(self.uow.committed)
        self.uow.strategy_versions.activate.assert_not_called()

    def test_activate_already_active_propagates_repository_error(self) -> None:
        seeded = self._seed_version(activated_at=DECIDED_AT)
        self.uow.strategy_versions.get_by_id.return_value = seeded
        self.uow.strategy_versions.activate.side_effect = (
            StrategyVersionAlreadyActiveError(
                f"StrategyVersion {STRATEGY_ID} is already active"
            )
        )

        with self.assertRaises(StrategyVersionAlreadyActiveError):
            self.service.activate_version(
                strategy_id=STRATEGY_ID,
                version=PROPOSED_VERSION,
                at=ACTIVATED_AT,
            )

        self.assertFalse(self.uow.committed)

    def test_activate_uses_injected_clock_when_at_is_none(self) -> None:
        self.uow.strategy_versions.get_by_id.return_value = self._seed_version()
        self.uow.strategy_versions.activate.return_value = self._seed_version(
            activated_at=ACTIVATED_AT
        )

        fixed_clock_value = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)

        def _clock() -> datetime:
            return fixed_clock_value

        service = StrategyGovernanceService(
            uow_factory=self.factory,
            authorized_approver_agent_ids=AUTHORIZED_APPROVERS,
            clock=_clock,
        )

        service.activate_version(
            strategy_id=STRATEGY_ID, version=PROPOSED_VERSION
        )

        self.uow.strategy_versions.activate.assert_called_once_with(
            STRATEGY_ID, at=fixed_clock_value
        )


class GetActiveVersionTests(unittest.TestCase):
    """Read-only lookup; no commit."""

    def setUp(self) -> None:
        self.uow = _FakeUnitOfWork()
        self.factory = _uow_factory(self.uow)
        self.service = StrategyGovernanceService(
            uow_factory=self.factory,
            authorized_approver_agent_ids=(),
        )

    def test_get_active_returns_repository_value(self) -> None:
        active = StrategyVersion(
            strategy_id=STRATEGY_ID,
            strategy_key=STRATEGY_KEY,
            version=PROPOSED_VERSION,
            artifact_ref=ARTIFACT_REF,
            artifact_hash=ARTIFACT_HASH,
            source_hashes=(SOURCE_HASH_A, SOURCE_HASH_B),
            decision_ref=DECISION_REF,
            decision_hash=DECISION_HASH,
            decided_by_agent_id=APPROVER_PRIMARY,
            audit_id=AUDIT_ID,
            approved_at=DECIDED_AT,
            activated_at=ACTIVATED_AT,
            created_at=DECIDED_AT,
        )
        self.uow.strategy_versions.get_active.return_value = active

        result = self.service.get_active_version(STRATEGY_KEY)

        self.assertEqual(result, active)
        self.assertEqual(result.artifact_ref, ARTIFACT_REF)
        self.assertEqual(result.artifact_hash, ARTIFACT_HASH)
        self.assertFalse(self.uow.committed)
        self.uow.strategy_versions.get_active.assert_called_once_with(
            STRATEGY_KEY
        )

    def test_get_active_returns_none(self) -> None:
        self.uow.strategy_versions.get_active.return_value = None

        result = self.service.get_active_version("absent")

        self.assertIsNone(result)
        self.assertFalse(self.uow.committed)
