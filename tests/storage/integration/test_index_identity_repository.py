"""Integration tests for :class:`SqlAlchemyIndexIdentityRepository`.

Verifies the idempotent get-or-create contract and the stable index_id
propagated through :class:`StoredIndexProfile` into
:class:`EtfIndexMappingRow`.

Tests run against the disposable Testcontainers PostgreSQL; each test
is isolated via savepoint-rolling fixtures in the parent conftest.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from invest_domain.exposure import (
    EtfIndexMapping,
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_domain.instruments import Instrument, InstrumentType
from invest_storage.models import IndexConstituentSnapshotRow
from sqlalchemy.exc import IntegrityError


def _prov(
    *,
    provider_key: str = "akshare",
    dataset_key: str = "index_profile_snapshot",
    observed_at: datetime | None = None,
    source_batch_id=None,
    revision: int = 1,
    confidence: Decimal | None = None,
) -> ExposureProvenance:
    return ExposureProvenance(
        provider_key=provider_key,
        dataset_key=dataset_key,
        observed_at=observed_at or datetime(2026, 8, 6, 9, 30, tzinfo=UTC),
        source_batch_id=source_batch_id,
        revision=revision,
        confidence=confidence or Decimal("0.95"),
    )


def _profile(
    *,
    index_code: str = "000300.SH",
    index_name: str = "沪深300",
    revision: int = 1,
    category: str | None = "宽基指数",
    as_of_date: date | None = date(2026, 8, 5),
) -> IndexProfile:
    return IndexProfile(
        index_code=index_code,
        index_name=index_name,
        provenance=_prov(revision=revision),
        category=category,
        as_of_date=as_of_date,
    )


def test_duplicate_index_code_returns_same_stable_id(
    uow_factory,
) -> None:
    """Calling add() twice with the same index_code yields the same index_id."""
    with uow_factory() as uow:
        first = uow.index_identities.add(index_code="000300.SH", index_name="沪深300")
        second = uow.index_identities.add(index_code="000300.SH", index_name="沪深300 v2")
        assert first.id == second.id, "duplicate index_code must return the same index_id"
        assert first.index_code == "000300.SH"
        assert second.index_code == "000300.SH"
        uow.commit()


def test_add_rejects_empty_index_code(uow_factory) -> None:
    """add() raises ValueError when index_code is empty or whitespace-only."""
    with uow_factory() as uow:
        with pytest.raises(ValueError, match="non-empty"):
            uow.index_identities.add(index_code="", index_name="name")
        with pytest.raises(ValueError, match="non-empty"):
            uow.index_identities.add(index_code="   ", index_name="name")


def test_add_rejects_empty_index_name(uow_factory) -> None:
    """add() raises ValueError when index_name is empty or whitespace-only."""
    with uow_factory() as uow:
        with pytest.raises(ValueError, match="non-empty"):
            uow.index_identities.add(index_code="000300.SH", index_name="")
        with pytest.raises(ValueError, match="non-empty"):
            uow.index_identities.add(index_code="000300.SH", index_name="   ")


def test_two_profile_revisions_share_index_id(uow_factory) -> None:
    """Two distinct profile observations for the same index_code share the same index_id."""
    with uow_factory() as uow:
        identity = uow.index_identities.add(index_code="000300.SH", index_name="沪深300")
        profile_v1 = uow.index_profiles.add(_profile(revision=1), index_id=identity.id)
        profile_v2 = uow.index_profiles.add(_profile(revision=2), index_id=identity.id)
        assert profile_v1.index_id == identity.id
        assert profile_v2.index_id == identity.id
        assert profile_v1.index_id == profile_v2.index_id
        assert profile_v1.id != profile_v2.id, "distinct revisions have distinct profile IDs"
        uow.commit()


def test_snapshot_and_mapping_reference_same_index_id(uow_factory) -> None:
    """Index constituent snapshot and ETF mapping both FK to the same stable index_id."""
    with uow_factory() as uow:
        identity = uow.index_identities.add(index_code="000300.SH", index_name="沪深300")

        snapshot = IndexConstituentSnapshot.create(
            index_code="000300.SH",
            as_of_date=date(2026, 8, 5),
            observed_at=datetime(2026, 8, 6, 9, 30, tzinfo=UTC),
            constituents=(
                IndexConstituent(
                    stock_code="600519.SH",
                    weight=Decimal("0.0500"),
                    industry="食品饮料",
                ),
            ),
            provenance=_prov(),
        )
        uow.index_constituent_snapshots.add(snapshot, index_id=identity.id)

        stored_row = uow.session.get(IndexConstituentSnapshotRow, snapshot.id)
        assert stored_row.index_id == identity.id

        etf = Instrument(
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
            instrument_type=InstrumentType.ETF,
            is_active=True,
        )
        uow.instruments.upsert_many([etf])
        persisted_etf = uow.instruments.get_by_business_key(exchange="SSE", symbol="510300")
        assert persisted_etf is not None
        etf_id = persisted_etf.instrument_id.value

        mapping = EtfIndexMapping(
            etf_id=etf_id,
            index_id=identity.id,
            effective_from=date(2026, 8, 1),
            effective_to=None,
            observed_at=datetime(2026, 8, 6, 9, 30, tzinfo=UTC),
            provenance=_prov(),
        )
        stored_mapping = uow.etf_index_mappings.add(mapping)
        assert stored_mapping.index_id == identity.id
        assert stored_mapping.index_id == stored_row.index_id
        uow.commit()


def test_unknown_index_id_fk_fails(uow_factory) -> None:
    """Adding a profile or mapping with a non-existent index_id raises IntegrityError."""
    fake_index_id = uuid4()
    with uow_factory() as uow:
        profile = _profile()
        with pytest.raises(IntegrityError):
            uow.index_profiles.add(profile, index_id=fake_index_id)
            uow.commit()
    with uow_factory() as uow:
        etf = Instrument(
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
            instrument_type=InstrumentType.ETF,
            is_active=True,
        )
        uow.instruments.upsert_many([etf])
        persisted_etf = uow.instruments.get_by_business_key(exchange="SSE", symbol="510300")
        assert persisted_etf is not None
        etf_id = persisted_etf.instrument_id.value

        mapping = EtfIndexMapping(
            etf_id=etf_id,
            index_id=fake_index_id,
            effective_from=date(2026, 8, 1),
            effective_to=None,
            observed_at=datetime(2026, 8, 6, 9, 30, tzinfo=UTC),
            provenance=_prov(),
        )
        with pytest.raises(IntegrityError):
            uow.etf_index_mappings.add(mapping)
            uow.commit()
