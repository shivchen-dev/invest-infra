"""PostgreSQL contracts for the StrategyVersion repository."""

from datetime import UTC, datetime

import pytest
from invest_domain.strategy import (
    SourceRef,
    StrategyAudit,
    StrategyAuditVerdict,
    StrategyDraft,
    StrategyVersion,
)
from invest_storage.repositories import (
    SqlAlchemyStrategyAuditRepository,
    SqlAlchemyStrategyDraftRepository,
    SqlAlchemyStrategyVersionRepository,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
ACTIVE_AT = datetime(2026, 8, 27, 10, 0, tzinfo=UTC)
STRATEGY_KEY = "sector-strength"


def _seed_versions(session: Session) -> tuple[StrategyVersion, StrategyVersion]:
    draft = StrategyDraft.create(
        strategy_key=STRATEGY_KEY,
        proposed_version="1.0.0",
        artifact_ref="strategies/sector-strength/strategy.json",
        artifact_hash="a" * 64,
        source_refs=(SourceRef("sources/spec.md", "b" * 64),),
        validation_result={"status": "passed"},
        created_at=NOW,
    )
    SqlAlchemyStrategyDraftRepository(session).add(draft)
    audit = StrategyAudit.create(
        draft_id=draft.draft_id,
        artifact_hash=draft.artifact_hash,
        agentoa_task_id="agentoa:strategy-version-integration",
        auditor_agent_id="raa:auditor",
        verdict=StrategyAuditVerdict.PASS,
        findings=(),
        limitations=(),
        report_ref="audits/strategy-version.json",
        report_hash="c" * 64,
        audited_at=NOW,
        clock=lambda: NOW,
    )
    SqlAlchemyStrategyAuditRepository(session).add(audit)
    versions = tuple(
        StrategyVersion.create(
            strategy_key=STRATEGY_KEY,
            version=version,
            artifact_ref=f"strategies/sector-strength/{version}.json",
            artifact_hash=artifact_hash * 64,
            source_hashes=("b" * 64,),
            decision_ref=f"decisions/sector-strength/{version}.json",
            decision_hash=decision_hash * 64,
            decided_by_agent_id="cia:approver",
            audit_id=audit.audit_id,
            approved_at=NOW,
            clock=lambda: NOW,
        )
        for version, artifact_hash, decision_hash in (
            ("1.0.0", "d", "e"),
            ("2.0.0", "f", "0"),
        )
    )
    repository = SqlAlchemyStrategyVersionRepository(session)
    return repository.add(versions[0]), repository.add(versions[1])


def test_add_get_and_activate_round_trip(db_session: Session) -> None:
    first, _ = _seed_versions(db_session)
    db_session.commit()
    db_session.expunge_all()
    repository = SqlAlchemyStrategyVersionRepository(db_session)

    assert repository.get_by_id(first.strategy_id) == first
    assert repository.get_active(STRATEGY_KEY) is None

    activated = repository.activate(first.strategy_id, at=ACTIVE_AT)
    db_session.commit()
    db_session.expunge_all()

    assert activated.activated_at == ACTIVE_AT
    assert repository.get_by_id(first.strategy_id).activated_at == ACTIVE_AT
    assert repository.get_active(STRATEGY_KEY).strategy_id == first.strategy_id


def test_second_version_activation_hits_partial_unique_index(
    db_session: Session,
) -> None:
    first, second = _seed_versions(db_session)
    db_session.commit()
    repository = SqlAlchemyStrategyVersionRepository(db_session)
    repository.activate(first.strategy_id, at=ACTIVE_AT)
    db_session.commit()

    with pytest.raises(IntegrityError) as exc_info:
        repository.activate(second.strategy_id, at=ACTIVE_AT)

    assert "uq_strategy_versions_activated_strategy_key" in str(exc_info.value)
