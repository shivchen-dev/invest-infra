"""Focused unit contracts for the StrategyVersion repository adapter.

PostgreSQL constraints, persistence round trips, activation writes, and the
partial unique index are covered by the integration suite. These mocks retain
only behavior that is cheaper and clearer to exercise at the adapter boundary:

- domain-to-row and row-to-domain mapping;
- idempotency and immutable-payload conflict classification;
- basic lookup results without pinning generated SQL;
- activation error branches, including the rowcount-zero classifier; and
- the public Unit-of-Work repository surface and context lifecycle.

The CAS tests below model branch inputs only. They do not claim to reproduce
transaction scheduling or prove database concurrency behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from invest_domain.strategy import (
    StrategyVersion,
    StrategyVersionAlreadyActiveError,
    StrategyVersionConflictError,
    StrategyVersionNotFoundError,
)
from invest_storage.models import StrategyVersionRow
from invest_storage.repositories import SqlAlchemyStrategyVersionRepository
from invest_storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
    StrategyVersionRepositoryPort,
    UnitOfWork,
)
from sqlalchemy.orm import Session

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
STRATEGY_KEY = "sector-strength"
VERSION = "1.0.0"
STRATEGY_ID = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
AUDIT_ID = UUID("22222222-3333-4444-8555-666666666666")
APPROVED_AT = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)
ACTIVATED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _version(**overrides: object) -> StrategyVersion:
    values = {
        "strategy_id": STRATEGY_ID,
        "strategy_key": STRATEGY_KEY,
        "version": VERSION,
        "artifact_ref": "strategy.json",
        "artifact_hash": HASH_A,
        "source_hashes": (HASH_A, HASH_C),
        "decision_ref": "decision.json",
        "decision_hash": HASH_B,
        "decided_by_agent_id": "agt_approver",
        "audit_id": AUDIT_ID,
        "approved_at": APPROVED_AT,
        "activated_at": None,
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return StrategyVersion(**values)  # type: ignore[arg-type]


def _row(version: StrategyVersion) -> MagicMock:
    row = MagicMock(spec=StrategyVersionRow)
    for name in (
        "strategy_id",
        "strategy_key",
        "version",
        "artifact_ref",
        "artifact_hash",
        "decision_ref",
        "decision_hash",
        "decided_by_agent_id",
        "audit_id",
        "approved_at",
        "activated_at",
        "created_at",
    ):
        setattr(row, name, getattr(version, name))
    row.source_hashes = list(version.source_hashes)
    return row


def _repo() -> tuple[SqlAlchemyStrategyVersionRepository, MagicMock]:
    session = MagicMock(spec=Session)
    session.scalars.return_value.first.return_value = None
    return SqlAlchemyStrategyVersionRepository(session), session


def _scalar_results(session: MagicMock, *rows: object) -> None:
    """Configure successive ``scalars(...).first()`` domain-row results."""
    results = []
    for row in rows:
        result = MagicMock()
        result.first.return_value = row
        results.append(result)
    session.scalars.side_effect = results


# Domain-to-row mapping -----------------------------------------------------


def test_add_maps_domain_to_row() -> None:
    repository, session = _repo()
    version = _version()

    assert repository.add(version) == version

    persisted = session.add.call_args.args[0]
    assert isinstance(persisted, StrategyVersionRow)
    for name in (
        "strategy_id",
        "strategy_key",
        "version",
        "artifact_ref",
        "artifact_hash",
        "decision_ref",
        "decision_hash",
        "decided_by_agent_id",
        "audit_id",
        "approved_at",
        "activated_at",
        "created_at",
    ):
        assert getattr(persisted, name) == getattr(version, name)
    assert persisted.source_hashes == list(version.source_hashes)


def test_add_rejects_wrong_domain_type() -> None:
    repository, session = _repo()
    with pytest.raises(TypeError):
        repository.add({"strategy_id": uuid4()})  # type: ignore[arg-type]
    session.add.assert_not_called()


# Idempotency and conflicts ------------------------------------------------


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("artifact_ref", "other.json"),
        ("artifact_hash", HASH_C),
        ("source_hashes", (HASH_A, HASH_B)),
        ("decision_ref", "other-decision.json"),
        ("decision_hash", HASH_C),
        ("decided_by_agent_id", "agt_other"),
        ("audit_id", UUID("33333333-4444-4555-8666-777777777777")),
        ("approved_at", APPROVED_AT + timedelta(minutes=1)),
    ],
)
def test_same_natural_key_rejects_immutable_payload_drift(
    field: str, changed: object
) -> None:
    repository, session = _repo()
    session.scalars.return_value.first.return_value = _row(_version())

    with pytest.raises(StrategyVersionConflictError):
        repository.add(_version(**{field: changed}))
    session.add.assert_not_called()


@pytest.mark.parametrize(
    "ignored_change",
    [
        {"strategy_id": UUID("44444444-5555-4666-8777-888888888888")},
        {"created_at": CREATED_AT + timedelta(seconds=1)},
        {"activated_at": ACTIVATED_AT},
    ],
)
def test_identical_payload_is_idempotent(ignored_change: dict[str, object]) -> None:
    repository, session = _repo()
    stored = _version()
    session.scalars.return_value.first.return_value = _row(stored)

    assert repository.add(_version(**ignored_change)) == stored
    session.add.assert_not_called()


@pytest.mark.parametrize("conflict", ["artifact_hash", "decision_hash"])
def test_global_hash_reuse_raises_conflict(conflict: str) -> None:
    repository, session = _repo()
    other = _row(
        _version(
            strategy_id=uuid4(),
            strategy_key="other-strategy",
            version="2.0.0",
            artifact_hash=HASH_A if conflict == "artifact_hash" else HASH_C,
            decision_hash=HASH_B,
        )
    )
    if conflict == "artifact_hash":
        _scalar_results(session, None, other)
    else:
        _scalar_results(session, None, None, other)

    with pytest.raises(StrategyVersionConflictError):
        repository.add(_version())
    session.add.assert_not_called()


# Row-to-domain lookup mapping ---------------------------------------------


def test_get_by_id_maps_row_and_source_hashes() -> None:
    repository, session = _repo()
    stored = _version(source_hashes=(HASH_A, HASH_B, HASH_C))
    session.get.return_value = _row(stored)

    result = repository.get_by_id(stored.strategy_id)

    assert result == stored
    assert isinstance(result.source_hashes, tuple)
    session.get.return_value = None
    assert repository.get_by_id(uuid4()) is None


def test_get_active_maps_present_and_absent_rows() -> None:
    repository, session = _repo()
    stored = _version(activated_at=ACTIVATED_AT)
    session.scalars.return_value.first.return_value = _row(stored)

    assert repository.get_active(STRATEGY_KEY) == stored
    session.scalars.return_value.first.return_value = None
    assert repository.get_active(STRATEGY_KEY) is None


# Activation and CAS classification ----------------------------------------


def test_activate_updates_and_returns_refreshed_domain() -> None:
    repository, session = _repo()
    refreshed = _version(activated_at=ACTIVATED_AT)
    _scalar_results(session, _row(_version()), _row(refreshed))
    session.execute.return_value.rowcount = 1

    assert repository.activate(STRATEGY_ID, at=ACTIVATED_AT) == refreshed
    session.flush.assert_called_once()


def test_activate_missing_and_already_active_are_classified() -> None:
    repository, session = _repo()
    with pytest.raises(StrategyVersionNotFoundError):
        repository.activate(STRATEGY_ID, at=ACTIVATED_AT)

    session.scalars.return_value.first.return_value = _row(
        _version(activated_at=ACTIVATED_AT)
    )
    with pytest.raises(StrategyVersionAlreadyActiveError):
        repository.activate(STRATEGY_ID, at=ACTIVATED_AT)


@pytest.mark.parametrize(
    ("reread", "error"),
    [
        (_row(_version(activated_at=ACTIVATED_AT)), StrategyVersionAlreadyActiveError),
        (None, StrategyVersionNotFoundError),
    ],
)
def test_activate_cas_lost_classifies_reread(
    reread: object, error: type[Exception]
) -> None:
    """Mock only the rowcount=0 classifier; real concurrency lives in integration."""
    repository, session = _repo()
    _scalar_results(session, _row(_version()), reread)
    session.execute.return_value.rowcount = 0

    with pytest.raises(error):
        repository.activate(STRATEGY_ID, at=ACTIVATED_AT)
    session.flush.assert_not_called()


def test_activate_missing_refresh_after_update_is_not_found() -> None:
    repository, session = _repo()
    _scalar_results(session, _row(_version()), None)
    session.execute.return_value.rowcount = 1

    with pytest.raises(StrategyVersionNotFoundError):
        repository.activate(STRATEGY_ID, at=ACTIVATED_AT)


@pytest.mark.parametrize("at", [ACTIVATED_AT.replace(tzinfo=None), "not-a-time"])
def test_activate_requires_aware_datetime(at: object) -> None:
    repository, _ = _repo()
    with pytest.raises((TypeError, ValueError)):
        repository.activate(STRATEGY_ID, at=at)  # type: ignore[arg-type]


# Unit-of-Work public surface ----------------------------------------------


def test_uow_exposes_repository_port_for_each_context_lifecycle() -> None:
    session = MagicMock(spec=Session)
    uow = SqlAlchemyUnitOfWork(MagicMock(return_value=session))

    with uow as entered:
        first = entered.strategy_versions
        assert isinstance(entered, UnitOfWork)
        assert isinstance(first, SqlAlchemyStrategyVersionRepository)
        assert isinstance(first, StrategyVersionRepositoryPort)
        assert entered.strategy_versions is first
        for method in (
            "add",
            "get_by_id",
            "get_active",
            "activate",
        ):
            assert callable(getattr(first, method))

    with uow as entered:
        assert entered.strategy_versions is not first
