"""Storage contract tests for immutable strategy audit reports."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from invest_domain.strategy import StrategyAudit, StrategyAuditVerdict
from invest_storage.models import StrategyAuditRow
from invest_storage.repositories import (
    SqlAlchemyStrategyAuditRepository,
    StrategyAuditConflictError,
)
from invest_storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
    StrategyAuditRepositoryPort,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
DRAFT_ID = UUID("11111111-2222-4333-8444-555555555555")
AUDIT_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")


def _audit(**overrides) -> StrategyAudit:
    values = {
        "draft_id": DRAFT_ID,
        "artifact_hash": "a" * 64,
        "agentoa_task_id": "tsk_example",
        "auditor_agent_id": "agt_raa",
        "verdict": StrategyAuditVerdict.CHANGES_REQUIRED,
        "findings": ({"code": "missing-threshold", "severity": "high"},),
        "limitations": ("no historical replay",),
        "report_ref": "audit/tsk_example/audit.json",
        "report_hash": "b" * 64,
        "audited_at": NOW,
        "audit_id_factory": lambda: AUDIT_ID,
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return StrategyAudit.create(**values)


def _row(audit: StrategyAudit) -> MagicMock:
    row = MagicMock(spec=StrategyAuditRow)
    for name in (
        "audit_id", "draft_id", "artifact_hash", "agentoa_task_id",
        "auditor_agent_id", "report_ref", "report_hash", "audited_at", "created_at",
    ):
        setattr(row, name, getattr(audit, name))
    row.verdict = audit.verdict.value
    row.findings = [dict(item) for item in audit.findings]
    row.limitations = list(audit.limitations)
    return row


def _repo() -> tuple[SqlAlchemyStrategyAuditRepository, MagicMock]:
    session = MagicMock(spec=Session)
    session.scalars.return_value.first.return_value = None
    return SqlAlchemyStrategyAuditRepository(session), session


def test_add_and_get_roundtrip() -> None:
    repo, session = _repo()
    audit = _audit()
    assert repo.add(audit) == audit
    persisted = session.add.call_args.args[0]
    assert isinstance(persisted, StrategyAuditRow)
    assert persisted.findings == [{"code": "missing-threshold", "severity": "high"}]
    session.get.return_value = _row(audit)
    assert repo.get_by_id(audit.audit_id) == audit


def test_same_idempotency_key_and_identical_content_returns_existing() -> None:
    repo, session = _repo()
    audit = _audit()
    session.scalars.return_value.first.return_value = _row(audit)
    assert repo.add(audit) == audit
    session.add.assert_not_called()


def test_idempotency_ignores_new_system_identity_and_creation_time() -> None:
    repo, session = _repo()
    stored = _audit()
    incoming = _audit(
        audit_id_factory=lambda: UUID("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"),
        clock=lambda: datetime(2026, 8, 26, 16, 0, tzinfo=UTC),
        audited_at=NOW,
    )
    session.scalars.return_value.first.return_value = _row(stored)
    assert repo.add(incoming) == stored
    session.add.assert_not_called()


def test_same_idempotency_key_with_conflicting_content_fails() -> None:
    repo, session = _repo()
    audit = _audit()
    session.scalars.return_value.first.return_value = _row(
        _audit(verdict=StrategyAuditVerdict.REJECT)
    )
    with pytest.raises(StrategyAuditConflictError):
        repo.add(audit)
    session.add.assert_not_called()


def test_list_by_draft_is_mapped() -> None:
    repo, session = _repo()
    audit = _audit()
    session.scalars.return_value.all.return_value = [_row(audit)]
    assert repo.list_by_draft(DRAFT_ID) == [audit]


def test_rejects_wrong_type() -> None:
    repo, session = _repo()
    with pytest.raises(TypeError):
        repo.add({"draft_id": DRAFT_ID})  # type: ignore[arg-type]
    session.add.assert_not_called()


def test_table_metadata_contract() -> None:
    table = StrategyAuditRow.__table__
    assert (table.schema, table.name) == ("analytics", "strategy_audits")
    assert {constraint.name for constraint in table.constraints if isinstance(
        constraint, UniqueConstraint
    )} == {"uq_strategy_audits_draft_artifact_task"}
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints if isinstance(constraint, CheckConstraint)
    }
    assert set(checks) == {
        "ck_strategy_audits_artifact_hash_len64",
        "ck_strategy_audits_report_hash_len64",
        "ck_strategy_audits_verdict_valid",
        "ck_strategy_audits_findings_array",
        "ck_strategy_audits_limitations_array",
    }
    assert "changes_required" in checks["ck_strategy_audits_verdict_valid"]
    foreign_keys = {
        constraint.name for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys == {"fk_strategy_audits_draft_id_strategy_drafts"}
    assert {index.name for index in table.indexes} == {
        "ix_strategy_audits_draft_id_audited_at"
    }


def test_uow_exposes_cached_repository_and_resets_on_exit() -> None:
    session = MagicMock(spec=Session)
    factory = MagicMock(return_value=session)
    uow = SqlAlchemyUnitOfWork(factory)
    with uow:
        audits = uow.strategy_audits
        assert isinstance(audits, SqlAlchemyStrategyAuditRepository)
        assert isinstance(audits, StrategyAuditRepositoryPort)
        assert audits._session is session
        assert uow.strategy_audits is audits
    with uow:
        assert uow.strategy_audits is not audits
