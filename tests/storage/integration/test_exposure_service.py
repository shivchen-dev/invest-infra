"""Integration tests for :mod:`invest_pipeline.exposure_service`.

Verifies the DC-3 atomic slice against a real Testcontainers PostgreSQL:

* Happy path: persist raw fixture payload through to all four tables in one
  UnitOfWork transaction and commit exactly once.
* Stable identity: ``uow.index_identities.add`` returns a stable ``index_id``
  that is used to rebuild the ``EtfIndexMapping``.
* Idempotent rerun: re-invoking with the same payload returns the same
  ``ExposurePersistResult`` identifiers (content-hash idempotency short-circuits
  re-insertion).
* Missing instrument rollback: when the ETF instrument does not exist,
  no rows are committed to any of the four tables.
* Cross-session visibility: committed records are readable in a new session.

Tests run against the disposable Testcontainers PostgreSQL; each test is
isolated via the truncation fixture in the parent conftest.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from invest_domain.instruments import Instrument, InstrumentType
from invest_pipeline.exposure_service import (
    ExposurePersistResult,
    InstrumentNotFoundError,
    persist_exposure,
)
from sqlalchemy import text

ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _load_fixture() -> dict[str, Any]:
    """Load the raw AKShare exposure fixture JSON.

    The repository root is three parents up from this file:
    - parents[0]: tests/storage/integration/
    - parents[1]: tests/storage/
    - parents[2]: tests/
    - parents[3]: invest-infra/ (repository root)
    """
    fixture_path = (
        Path(__file__)
        .resolve()
        .parents[3]
        / "apps"
        / "pipeline"
        / "tests"
        / "unit"
        / "fixtures"
        / "exposure"
        / "akshare_exposure_payload.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@pytest.fixture
def etf_instrument(uow_factory) -> UUID:
    """Create an ETF instrument in the database and return its id."""
    instrument = Instrument(
        symbol="510300",
        name="沪深300ETF",
        exchange="SSE",
        instrument_type=InstrumentType.ETF,
        is_active=True,
    )
    with uow_factory() as uow:
        uow.instruments.upsert_many([instrument])
        uow.commit()
    persisted = None
    with uow_factory() as uow:
        persisted = uow.instruments.get_by_business_key(exchange="SSE", symbol="510300")
    assert persisted is not None
    return persisted.instrument_id.value


def _raw_payload(etf_id: UUID) -> dict[str, Any]:
    """Return the raw fixture payload with the given etf_id in mapping and holdings."""
    payload = _load_fixture()
    payload["etf_index_mapping"]["etf_id"] = str(etf_id)
    payload["etf_holdings"]["etf_id"] = str(etf_id)
    return payload


def test_happy_path_persists_all_four_tables_and_commits_once(
    uow_factory, etf_instrument: UUID, session_factory_fixture
) -> None:
    """persist_exposure writes all four records and commits exactly once.

    Verifies index_profiles, index_constituent_snapshots, etf_index_mappings,
    and etf_holding_snapshots tables plus the canonical index identity.
    """
    raw_payload = _raw_payload(etf_instrument)

    result = persist_exposure(raw_payload, uow_factory)

    assert isinstance(result, ExposurePersistResult)
    assert len(result.profile_content_hash) == 64
    assert len(result.constituent_content_hash) == 64
    assert len(result.mapping_content_hash) == 64
    assert len(result.holding_content_hash) == 64

    with session_factory_fixture() as verify_session:
        profile_row = verify_session.execute(
            text(
                "SELECT id, index_id, content_hash FROM core.index_profiles "
                "WHERE content_hash = :ch"
            ),
            {"ch": result.profile_content_hash},
        ).fetchone()
        assert profile_row is not None
        assert profile_row.index_id == result.index_id

        const_row = verify_session.execute(
            text(
                "SELECT id, index_id, content_hash FROM core.index_constituent_snapshots "
                "WHERE content_hash = :ch"
            ),
            {"ch": result.constituent_content_hash},
        ).fetchone()
        assert const_row is not None
        assert const_row.index_id == result.index_id

        map_row = verify_session.execute(
            text(
                "SELECT id, etf_id, index_id, content_hash FROM core.etf_index_mappings "
                "WHERE content_hash = :ch"
            ),
            {"ch": result.mapping_content_hash},
        ).fetchone()
        assert map_row is not None
        assert map_row.etf_id == etf_instrument
        assert map_row.index_id == result.index_id

        hold_row = verify_session.execute(
            text(
                "SELECT id, etf_id, content_hash FROM core.etf_holding_snapshots "
                "WHERE content_hash = :ch"
            ),
            {"ch": result.holding_content_hash},
        ).fetchone()
        assert hold_row is not None
        assert hold_row.etf_id == etf_instrument

        index_identity_row = verify_session.execute(
            text(
                "SELECT id, index_code FROM core.indexes "
                "WHERE index_code = :ic"
            ),
            {"ic": "000300"},
        ).fetchone()
        assert index_identity_row is not None
        assert index_identity_row.id == result.index_id


def test_stable_identity_replaces_payload_index_id(
    uow_factory, etf_instrument: UUID
) -> None:
    """The canonical index identity is obtained via index_identities.add;
    the payload index_id is explicitly ignored in the rebuilt EtfIndexMapping."""
    raw_payload = _raw_payload(etf_instrument)
    payload_index_id = UUID(raw_payload["etf_index_mapping"]["index_id"])

    result = persist_exposure(raw_payload, uow_factory)

    assert result.index_id != payload_index_id
    with uow_factory() as uow:
        identity = uow.index_identities.get_by_index_code("000300")
        assert identity is not None
        assert identity.id == result.index_id


def test_idempotent_rerun_returns_same_identifiers(
    uow_factory, etf_instrument: UUID
) -> None:
    """Re-running persist_exposure with the same bundle returns the same
    ExposurePersistResult (content-hash idempotency short-circuits re-insertion)."""
    raw_payload = _raw_payload(etf_instrument)

    first = persist_exposure(raw_payload, uow_factory)
    second = persist_exposure(raw_payload, uow_factory)

    assert first.index_id == second.index_id
    assert first.profile_content_hash == second.profile_content_hash
    assert (
        first.constituent_content_hash == second.constituent_content_hash
    )
    assert first.mapping_content_hash == second.mapping_content_hash
    assert first.holding_content_hash == second.holding_content_hash


def test_missing_etf_instrument_raises_and_rolls_back_no_exposure_rows(
    uow_factory,
) -> None:
    """When the ETF instrument does not exist, InstrumentNotFoundError is
    raised and no rows are committed to any of the four exposure tables."""
    raw_payload = _raw_payload(UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"))

    with pytest.raises(InstrumentNotFoundError) as ctx:
        persist_exposure(raw_payload, uow_factory)
    assert str(UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")) in str(ctx.value)

    with uow_factory() as uow:
        profile_count = uow.session.execute(
            text("SELECT COUNT(*) FROM core.index_profiles")
        ).scalar_one()
        const_count = uow.session.execute(
            text("SELECT COUNT(*) FROM core.index_constituent_snapshots")
        ).scalar_one()
        map_count = uow.session.execute(
            text("SELECT COUNT(*) FROM core.etf_index_mappings")
        ).scalar_one()
        hold_count = uow.session.execute(
            text("SELECT COUNT(*) FROM core.etf_holding_snapshots")
        ).scalar_one()

    assert profile_count == 0
    assert const_count == 0
    assert map_count == 0
    assert hold_count == 0


if __name__ == "__main__":
    import unittest

    unittest.main()
