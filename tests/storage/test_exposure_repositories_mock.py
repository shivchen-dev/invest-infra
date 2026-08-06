"""Mock-based unit tests for the Stage DC-3 exposure storage repositories.

The tests drive :class:`unittest.mock.MagicMock` ``Session`` instances so
the five repositories (IndexIdentity, IndexProfile, IndexConstituentSnapshot,
EtfIndexMapping, EtfHoldingSnapshot) can be verified without spinning
up Testcontainers or speaking to a real PostgreSQL. The contracts
pinned here:

- domain -> row mapping: every column of the relevant ORM row is
  populated from the domain dataclass (and vice versa on read).
- content_hash idempotency: the ``INSERT ... ON CONFLICT (content_hash)
  DO NOTHING`` path returns the pre-existing row untouched on
  re-collect so the application never silently overwrites evidence.
- revision / provenance columns carry the provider observation
  metadata end-to-end.
- children rows (``core.index_constituents`` / ``core.etf_holdings``)
  are written in the same transaction as the parent snapshot and
  round-trip back through ``get_by_id`` / ``find_by_content_hash``.
- the persisted ``IndexProfile.id`` is reusable as the
  ``EtfIndexMapping.index_id`` FK so the application service can
  thread one identity through both writes.
- index_code lives in IndexIdentityRow; IndexProfileRow and
  IndexConstituentSnapshotRow carry index_id FK instead.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.exposure import (
    EtfHolding,
    EtfHoldingSnapshot,
    EtfIndexMapping,
    ExposureProvenance,
    IndexConstituent,
    IndexConstituentSnapshot,
    IndexProfile,
)
from invest_storage import (
    EtfHoldingRow,
    EtfHoldingSnapshotRow,
    EtfIndexMappingRow,
    IndexConstituentRow,
    IndexConstituentSnapshotRow,
    IndexIdentityRow,
    IndexProfileRow,
    SqlAlchemyEtfHoldingSnapshotRepository,
    SqlAlchemyEtfIndexMappingRepository,
    SqlAlchemyIndexConstituentSnapshotRepository,
    SqlAlchemyIndexIdentityRepository,
    SqlAlchemyIndexProfileRepository,
    SqlAlchemyUnitOfWork,
    StoredEtfIndexMapping,
    StoredIndexIdentity,
    StoredIndexProfile,
)
from sqlalchemy.orm import Session

_OBSERVED_AT = datetime(2026, 8, 6, 9, 30, tzinfo=UTC)
_BATCH_ID = UUID("11111111-1111-1111-1111-111111111111")


def _prov(**overrides: object) -> ExposureProvenance:
    base: dict[str, object] = {
        "provider_key": "akshare",
        "dataset_key": "index_profile_snapshot",
        "observed_at": _OBSERVED_AT,
        "source_batch_id": _BATCH_ID,
        "revision": 1,
        "confidence": Decimal("0.95"),
    }
    base.update(overrides)
    return ExposureProvenance(**base)


def _profile(**overrides: object) -> IndexProfile:
    base: dict[str, object] = {
        "index_code": "000300.SH",
        "index_name": "沪深300",
        "provenance": _prov(),
        "category": "宽基指数",
        "as_of_date": date(2026, 8, 5),
    }
    base.update(overrides)
    return IndexProfile(**base)


def _mapping(
    *,
    etf_id: UUID | None = None,
    index_id: UUID,
    effective_from: date = date(2026, 8, 1),
    effective_to: date | None = None,
    provenance: ExposureProvenance | None = None,
) -> EtfIndexMapping:
    return EtfIndexMapping(
        etf_id=etf_id or uuid4(),
        index_id=index_id,
        effective_from=effective_from,
        effective_to=effective_to,
        observed_at=_OBSERVED_AT,
        provenance=provenance or _prov(),
    )


def _constituents_snapshot(
    *,
    index_code: str = "000300.SH",
    as_of_date: date = date(2026, 8, 5),
) -> IndexConstituentSnapshot:
    return IndexConstituentSnapshot.create(
        index_code=index_code,
        as_of_date=as_of_date,
        observed_at=_OBSERVED_AT,
        constituents=(
            IndexConstituent(stock_code="600519.SH", weight=Decimal("0.0500"), industry="食品饮料"),
            IndexConstituent(stock_code="000001.SZ", weight=Decimal("0.0200"), industry="银行"),
        ),
        provenance=_prov(),
    )


def _holdings_snapshot(
    *,
    etf_id: UUID | None = None,
    as_of_date: date = date(2026, 8, 5),
) -> EtfHoldingSnapshot:
    return EtfHoldingSnapshot.create(
        etf_id=etf_id or uuid4(),
        as_of_date=as_of_date,
        observed_at=_OBSERVED_AT,
        holdings=(
            EtfHolding(stock_code="600519.SH", weight=Decimal("0.0500"), industry="食品饮料"),
            EtfHolding(stock_code="000001.SZ", weight=Decimal("0.0200"), industry="银行"),
        ),
        provenance=_prov(),
    )


# ---------------------------------------------------------------------------
# IndexIdentity
# ---------------------------------------------------------------------------


def _index_identity_row(
    index_code: str = "000300.SH",
    index_name: str = "沪深300",
    category: str | None = "宽基指数",
    identity_id: UUID | None = None,
) -> MagicMock:
    row = MagicMock(spec=IndexIdentityRow)
    row.id = identity_id or uuid4()
    row.index_code = index_code
    row.index_name = index_name
    row.category = category
    row.first_observed_at = _OBSERVED_AT
    row.last_observed_at = _OBSERVED_AT
    row.created_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    return row


class IndexIdentityRepositoryTests(unittest.TestCase):
    """Pin the write/read path for ``core.indexes``."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyIndexIdentityRepository(self._session)

    def test_add_inserts_row_with_domain_payload(self) -> None:
        identity_row = _index_identity_row()
        self._session.execute.return_value.scalar_one_or_none.return_value = identity_row.id
        self._session.get.return_value = identity_row
        self._session.flush.return_value = None

        stored = self._repo.add(
            index_code="000300.SH",
            index_name="沪深300",
            category="宽基指数",
        )

        self.assertIsInstance(stored, StoredIndexIdentity)
        self.assertEqual(stored.index_code, "000300.SH")
        self.assertEqual(stored.index_name, "沪深300")
        self.assertEqual(stored.category, "宽基指数")
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once()

    def test_get_by_id_maps_row(self) -> None:
        identity_row = _index_identity_row()
        self._session.get.return_value = identity_row

        stored = self._repo.get_by_id(identity_row.id)

        self.assertEqual(stored.id, identity_row.id)
        self.assertEqual(stored.index_code, identity_row.index_code)
        self._session.get.assert_called_once_with(IndexIdentityRow, identity_row.id)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_get_by_index_code_returns_row(self) -> None:
        identity_row = _index_identity_row()
        self._session.scalars.return_value.first.return_value = identity_row

        stored = self._repo.get_by_index_code("000300.SH")

        self.assertEqual(stored.index_code, "000300.SH")
        self._session.scalars.assert_called_once()

    def test_get_by_index_code_returns_none_when_missing(self) -> None:
        self._session.scalars.return_value.first.return_value = None
        self.assertIsNone(self._repo.get_by_index_code("MISSING.SH"))

    def test_list_by_index_code_returns_rows(self) -> None:
        identity_row = _index_identity_row()
        self._session.scalars.return_value.all.return_value = [identity_row]

        result = self._repo.list_by_index_code("000300.SH")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index_code, "000300.SH")
        self._session.scalars.assert_called_once()

    def test_list_by_index_code_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_code("000300.SH", limit=-1)

    def test_list_by_index_code_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_code("000300.SH", offset=-1)


# ---------------------------------------------------------------------------
# IndexProfile
# ---------------------------------------------------------------------------


def _index_profile_row(
    profile: IndexProfile, profile_id: UUID, index_id: UUID
) -> MagicMock:
    row = MagicMock(spec=IndexProfileRow)
    row.id = profile_id
    row.index_id = index_id
    row.index_name = profile.index_name
    row.category = profile.category
    row.as_of_date = profile.as_of_date
    row.source_provider = profile.provenance.provider_key
    row.source_dataset = profile.provenance.dataset_key
    row.observed_at = profile.provenance.observed_at
    row.source_batch_id = profile.provenance.source_batch_id
    row.source_revision = profile.provenance.revision
    row.confidence = profile.provenance.confidence
    row.revision = profile.provenance.revision
    row.content_hash = profile.content_hash
    row.created_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    identity_row = _index_identity_row(
        index_code=profile.index_code,
        identity_id=index_id,
    )
    row.index_identity = identity_row
    return row


class IndexProfileRepositoryTests(unittest.TestCase):
    """Pin the idempotent upsert + read path for ``core.index_profiles``."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyIndexProfileRepository(self._session)

    def test_add_inserts_row_with_full_domain_payload(self) -> None:
        profile = _profile()
        index_id = uuid4()
        persisted_id = uuid4()
        persisted_row = _index_profile_row(profile, persisted_id, index_id)
        self._session.execute.return_value.scalar_one_or_none.return_value = persisted_id
        self._session.scalars.return_value.first.return_value = persisted_row

        stored = self._repo.add(profile, index_id)

        self.assertIsInstance(stored, StoredIndexProfile)
        self.assertEqual(stored.id, persisted_id)
        self.assertEqual(stored.index_id, index_id)
        self.assertEqual(stored.index_code, profile.index_code)
        self.assertEqual(stored.index_name, profile.index_name)
        self.assertEqual(stored.category, profile.category)
        self.assertEqual(stored.as_of_date, profile.as_of_date)
        self.assertEqual(stored.provenance, profile.provenance)
        self.assertEqual(stored.content_hash, profile.content_hash)
        self.assertEqual(stored.revision, profile.provenance.revision)
        self.assertEqual(stored.confidence, profile.provenance.confidence)

        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["index_id"], index_id)
        self.assertEqual(params["index_name"], profile.index_name)
        self.assertEqual(params["category"], profile.category)
        self.assertEqual(params["as_of_date"], profile.as_of_date)
        self.assertEqual(
            params["source_provider"], profile.provenance.provider_key
        )
        self.assertEqual(
            params["source_dataset"], profile.provenance.dataset_key
        )
        self.assertEqual(params["observed_at"], profile.provenance.observed_at)
        self.assertEqual(
            params["source_batch_id"], profile.provenance.source_batch_id
        )
        self.assertEqual(
            params["source_revision"], profile.provenance.revision
        )
        self.assertEqual(params["confidence"], profile.provenance.confidence)
        self.assertEqual(params["content_hash"], profile.content_hash)

    def test_add_returns_existing_row_on_content_hash_conflict(self) -> None:
        profile = _profile()
        index_id = uuid4()
        existing_id = uuid4()
        existing_row = _index_profile_row(profile, existing_id, index_id)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = existing_row

        stored = self._repo.add(profile, index_id)

        self.assertEqual(stored.id, existing_id)
        self.assertEqual(stored.content_hash, profile.content_hash)

    def test_add_raises_when_conflict_but_row_missing(self) -> None:
        profile = _profile()
        index_id = uuid4()
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(profile, index_id)

    def test_upsert_skips_insert_when_hash_exists(self) -> None:
        profile = _profile()
        index_id = uuid4()
        existing_id = uuid4()
        existing_row = _index_profile_row(profile, existing_id, index_id)
        self._session.scalars.return_value.first.return_value = existing_row

        stored = self._repo.upsert(profile, index_id)

        self.assertEqual(stored.id, existing_id)
        self._session.execute.assert_not_called()
        self._session.flush.assert_not_called()

    def test_upsert_inserts_when_hash_missing(self) -> None:
        profile = _profile()
        index_id = uuid4()
        inserted_id = uuid4()
        persisted_row = _index_profile_row(profile, inserted_id, index_id)
        self._session.scalars.return_value.first.side_effect = [None, persisted_row]
        self._session.execute.return_value.scalar_one_or_none.return_value = inserted_id

        stored = self._repo.upsert(profile, index_id)

        self.assertEqual(stored.id, inserted_id)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

    def test_get_by_id_maps_row(self) -> None:
        profile = _profile()
        index_id = uuid4()
        row = _index_profile_row(profile, uuid4(), index_id)
        self._session.get.return_value = row

        stored = self._repo.get_by_id(row.id)

        self.assertEqual(stored.id, row.id)
        self.assertEqual(stored.index_code, profile.index_code)
        self.assertEqual(stored.provenance, profile.provenance)
        self._session.get.assert_called_once_with(IndexProfileRow, row.id)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_find_by_content_hash_returns_none_when_absent(self) -> None:
        self._session.scalars.return_value.first.return_value = None
        self.assertIsNone(self._repo.find_by_content_hash("a" * 64))

    def test_list_by_index_id_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_id(uuid4(), limit=-1)

    def test_list_by_index_id_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_id(uuid4(), offset=-1)

    def test_list_by_index_id_maps_rows(self) -> None:
        profile = _profile()
        index_id = uuid4()
        rows = [
            _index_profile_row(profile, uuid4(), index_id),
            _index_profile_row(profile, uuid4(), index_id),
        ]
        self._session.scalars.return_value.all.return_value = rows

        result = self._repo.list_by_index_id(index_id)

        self.assertEqual(len(result), 2)
        self.assertEqual({item.content_hash for item in result}, {profile.content_hash})
        self._session.scalars.assert_called_once()

    def test_list_by_provider_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_provider("")

    def test_list_by_provider_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_provider("akshare", limit=-1)


# ---------------------------------------------------------------------------
# IndexConstituentSnapshot
# ---------------------------------------------------------------------------


def _index_constituent_snapshot_row(
    snapshot: IndexConstituentSnapshot, snapshot_id: UUID, index_id: UUID
) -> MagicMock:
    row = MagicMock(spec=IndexConstituentSnapshotRow)
    row.id = snapshot_id
    row.index_id = index_id
    row.as_of_date = snapshot.as_of_date
    row.source_provider = snapshot.provenance.provider_key
    row.source_dataset = snapshot.provenance.dataset_key
    row.observed_at = snapshot.provenance.observed_at
    row.source_batch_id = snapshot.provenance.source_batch_id
    row.source_revision = snapshot.provenance.revision
    row.confidence = snapshot.provenance.confidence
    row.revision = snapshot.provenance.revision
    row.content_hash = snapshot.content_hash
    row.created_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    identity_row = _index_identity_row(
        index_code=snapshot.index_code,
        identity_id=index_id,
    )
    row.index_identity = identity_row
    return row


def _constituent_row(
    snapshot_id: UUID, item: IndexConstituent, revision: int
) -> MagicMock:
    row = MagicMock(spec=IndexConstituentRow)
    row.id = uuid4()
    row.snapshot_id = snapshot_id
    row.stock_code = item.stock_code
    row.weight = item.weight
    row.industry = item.industry
    row.revision = revision
    return row


class IndexConstituentSnapshotRepositoryTests(unittest.TestCase):
    """Pin the snapshot+children writes and full round-trip reads."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyIndexConstituentSnapshotRepository(self._session)

    def test_add_inserts_parent_and_children_rows(self) -> None:
        snapshot = _constituents_snapshot()
        index_id = uuid4()
        self._session.execute.return_value.scalar_one_or_none.return_value = snapshot.id

        result = self._repo.add(snapshot, index_id)

        self.assertIs(result, snapshot)
        self._session.execute.assert_called_once()
        self.assertEqual(self._session.add_all.call_count, 1)
        added = self._session.add_all.call_args.args[0]
        self.assertEqual(len(added), len(snapshot.constituents))
        for child_row, constituent in zip(added, snapshot.constituents, strict=True):
            self.assertEqual(child_row.snapshot_id, snapshot.id)
            self.assertEqual(child_row.stock_code, constituent.stock_code)
            self.assertEqual(child_row.weight, constituent.weight)
            self.assertEqual(child_row.industry, constituent.industry)
            self.assertEqual(child_row.revision, snapshot.provenance.revision)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["id"], snapshot.id)
        self.assertEqual(params["index_id"], index_id)
        self.assertEqual(params["as_of_date"], snapshot.as_of_date)
        self.assertEqual(params["content_hash"], snapshot.content_hash)
        self.assertEqual(params["revision"], snapshot.provenance.revision)
        self.assertEqual(
            params["source_provider"], snapshot.provenance.provider_key
        )
        self.assertEqual(
            params["source_batch_id"], snapshot.provenance.source_batch_id
        )

    def test_add_returns_existing_snapshot_on_hash_conflict(self) -> None:
        snapshot = _constituents_snapshot()
        index_id = uuid4()
        existing_id = uuid4()
        existing = IndexConstituentSnapshot.create(
            index_code=snapshot.index_code,
            as_of_date=snapshot.as_of_date,
            observed_at=snapshot.provenance.observed_at,
            constituents=snapshot.constituents,
            provenance=snapshot.provenance,
            id_factory=lambda: existing_id,
            now_factory=lambda: snapshot.provenance.observed_at,
        )
        existing_row = _index_constituent_snapshot_row(existing, existing_id, index_id)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        child_rows = tuple(
            _constituent_row(existing.id, item, snapshot.provenance.revision)
            for item in snapshot.constituents
        )
        self._session.scalars.return_value.first.return_value = existing_row
        self._session.scalars.return_value.all.return_value = list(child_rows)

        result = self._repo.add(snapshot, index_id)

        self.assertNotEqual(result.id, snapshot.id)
        self.assertEqual(result.id, existing_id)
        self._session.add_all.assert_not_called()

    def test_add_raises_when_conflict_but_row_missing(self) -> None:
        snapshot = _constituents_snapshot()
        index_id = uuid4()
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(snapshot, index_id)
        self._session.add_all.assert_not_called()

    def test_get_by_id_reconstructs_snapshot_with_children(self) -> None:
        snapshot = _constituents_snapshot()
        index_id = uuid4()
        parent_row = _index_constituent_snapshot_row(snapshot, snapshot.id, index_id)
        child_rows = tuple(
            _constituent_row(snapshot.id, item, snapshot.provenance.revision)
            for item in snapshot.constituents
        )
        self._session.get.return_value = parent_row
        self._session.scalars.return_value.all.return_value = list(child_rows)

        result = self._repo.get_by_id(snapshot.id)

        self.assertEqual(result.id, snapshot.id)
        self.assertEqual(result.index_code, snapshot.index_code)
        self.assertEqual(result.as_of_date, snapshot.as_of_date)
        self.assertEqual(result.observed_at, snapshot.observed_at)
        self.assertEqual(
            tuple(
                (item.stock_code, item.weight, item.industry)
                for item in result.constituents
            ),
            tuple(
                (item.stock_code, item.weight, item.industry)
                for item in snapshot.constituents
            ),
        )
        self.assertEqual(result.content_hash, snapshot.content_hash)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_list_by_index_id_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_id(uuid4(), limit=-1)

    def test_list_by_index_id_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_id(uuid4(), offset=-1)

    def test_list_by_index_id_maps_snapshots(self) -> None:
        snapshot = _constituents_snapshot()
        index_id = uuid4()
        child_rows = tuple(
            _constituent_row(snapshot.id, item, snapshot.provenance.revision)
            for item in snapshot.constituents
        )
        parent_row = _index_constituent_snapshot_row(snapshot, snapshot.id, index_id)
        parents_scalars = MagicMock()
        parents_scalars.all.return_value = [parent_row]
        children_scalars = MagicMock()
        children_scalars.all.return_value = list(child_rows)
        self._session.scalars.side_effect = [
            parents_scalars,
            children_scalars,
        ]

        result = self._repo.list_by_index_id(index_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content_hash, snapshot.content_hash)


# ---------------------------------------------------------------------------
# EtfIndexMapping
# ---------------------------------------------------------------------------


def _etf_index_mapping_row(
    mapping: EtfIndexMapping, mapping_id: UUID
) -> MagicMock:
    row = MagicMock(spec=EtfIndexMappingRow)
    row.id = mapping_id
    row.etf_id = mapping.etf_id
    row.index_id = mapping.index_id
    row.effective_from = mapping.effective_from
    row.effective_to = mapping.effective_to
    row.observed_at = mapping.observed_at
    row.source_provider = mapping.provenance.provider_key
    row.source_dataset = mapping.provenance.dataset_key
    row.source_batch_id = mapping.provenance.source_batch_id
    row.source_revision = mapping.provenance.revision
    row.confidence = mapping.provenance.confidence
    row.revision = mapping.provenance.revision
    row.content_hash = mapping.content_hash
    row.created_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    return row


class EtfIndexMappingRepositoryTests(unittest.TestCase):
    """Pin the idempotent write/read path for ``core.etf_index_mappings``."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfIndexMappingRepository(self._session)

    def test_add_inserts_row_with_full_domain_payload(self) -> None:
        index_id = uuid4()
        mapping = _mapping(index_id=index_id, effective_to=date(2027, 1, 1))
        mapping_id = uuid4()
        persisted_row = _etf_index_mapping_row(mapping, mapping_id)
        self._session.execute.return_value.scalar_one_or_none.return_value = mapping_id
        self._session.scalars.return_value.first.return_value = persisted_row

        stored = self._repo.add(mapping)

        self.assertIsInstance(stored, StoredEtfIndexMapping)
        self.assertEqual(stored.id, mapping_id)
        self.assertEqual(stored.etf_id, mapping.etf_id)
        self.assertEqual(stored.index_id, mapping.index_id)
        self.assertEqual(stored.effective_from, mapping.effective_from)
        self.assertEqual(stored.effective_to, mapping.effective_to)
        self.assertEqual(stored.observed_at, mapping.observed_at)
        self.assertEqual(stored.provenance, mapping.provenance)
        self.assertEqual(stored.content_hash, mapping.content_hash)
        self.assertEqual(stored.revision, mapping.provenance.revision)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["etf_id"], mapping.etf_id)
        self.assertEqual(params["index_id"], mapping.index_id)
        self.assertEqual(params["effective_from"], mapping.effective_from)
        self.assertEqual(params["effective_to"], mapping.effective_to)
        self.assertEqual(params["observed_at"], mapping.observed_at)
        self.assertEqual(params["content_hash"], mapping.content_hash)
        self.assertEqual(
            params["source_provider"], mapping.provenance.provider_key
        )
        self.assertEqual(
            params["source_batch_id"], mapping.provenance.source_batch_id
        )

    def test_add_returns_existing_on_content_hash_conflict(self) -> None:
        mapping = _mapping(index_id=uuid4())
        existing_id = uuid4()
        existing_row = _etf_index_mapping_row(mapping, existing_id)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = existing_row

        stored = self._repo.add(mapping)

        self.assertEqual(stored.id, existing_id)
        self.assertEqual(stored.content_hash, mapping.content_hash)

    def test_add_raises_when_conflict_but_row_missing(self) -> None:
        mapping = _mapping(index_id=uuid4())
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(mapping)

    def test_upsert_is_noop_when_hash_exists(self) -> None:
        mapping = _mapping(index_id=uuid4())
        existing_id = uuid4()
        existing_row = _etf_index_mapping_row(mapping, existing_id)
        self._session.scalars.return_value.first.return_value = existing_row

        stored = self._repo.upsert(mapping)

        self.assertEqual(stored.id, existing_id)
        self._session.execute.assert_not_called()
        self._session.flush.assert_not_called()

    def test_upsert_inserts_when_hash_missing(self) -> None:
        mapping = _mapping(index_id=uuid4())
        inserted_id = uuid4()
        persisted_row = _etf_index_mapping_row(mapping, inserted_id)
        self._session.scalars.return_value.first.side_effect = [None, persisted_row]
        self._session.execute.return_value.scalar_one_or_none.return_value = inserted_id

        stored = self._repo.upsert(mapping)

        self.assertEqual(stored.id, inserted_id)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

    def test_get_by_id_maps_row(self) -> None:
        mapping = _mapping(index_id=uuid4())
        mapping_id = uuid4()
        row = _etf_index_mapping_row(mapping, mapping_id)
        self._session.get.return_value = row

        stored = self._repo.get_by_id(mapping_id)

        self.assertEqual(stored.id, mapping_id)
        self.assertEqual(stored.index_id, mapping.index_id)
        self.assertEqual(stored.content_hash, mapping.content_hash)
        self._session.get.assert_called_once_with(EtfIndexMappingRow, mapping_id)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_list_by_etf_id_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_etf_id(uuid4(), limit=-1)

    def test_list_by_etf_id_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_etf_id(uuid4(), offset=-1)

    def test_list_by_etf_id_maps_rows(self) -> None:
        mapping = _mapping(index_id=uuid4())
        rows = [_etf_index_mapping_row(mapping, uuid4())]
        self._session.scalars.return_value.all.return_value = rows

        result = self._repo.list_by_etf_id(mapping.etf_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].etf_id, mapping.etf_id)
        self._session.scalars.assert_called_once()

    def test_list_by_index_id_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_index_id(uuid4(), offset=-1)

    def test_list_by_index_id_maps_rows(self) -> None:
        mapping = _mapping(index_id=uuid4())
        rows = [_etf_index_mapping_row(mapping, uuid4())]
        self._session.scalars.return_value.all.return_value = rows

        result = self._repo.list_by_index_id(mapping.index_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index_id, mapping.index_id)
        self._session.scalars.assert_called_once()


# ---------------------------------------------------------------------------
# EtfHoldingSnapshot
# ---------------------------------------------------------------------------


def _etf_holding_snapshot_row(snapshot: EtfHoldingSnapshot) -> MagicMock:
    row = MagicMock(spec=EtfHoldingSnapshotRow)
    row.id = snapshot.id
    row.etf_id = snapshot.etf_id
    row.as_of_date = snapshot.as_of_date
    row.source_provider = snapshot.provenance.provider_key
    row.source_dataset = snapshot.provenance.dataset_key
    row.observed_at = snapshot.provenance.observed_at
    row.source_batch_id = snapshot.provenance.source_batch_id
    row.source_revision = snapshot.provenance.revision
    row.confidence = snapshot.provenance.confidence
    row.revision = snapshot.provenance.revision
    row.content_hash = snapshot.content_hash
    row.created_at = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
    return row


def _holding_row(
    snapshot_id: UUID, item: EtfHolding, revision: int
) -> MagicMock:
    row = MagicMock(spec=EtfHoldingRow)
    row.id = uuid4()
    row.snapshot_id = snapshot_id
    row.stock_code = item.stock_code
    row.weight = item.weight
    row.industry = item.industry
    row.revision = revision
    return row


class EtfHoldingSnapshotRepositoryTests(unittest.TestCase):
    """Pin the snapshot+children writes for ``core.etf_holding_snapshots``."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfHoldingSnapshotRepository(self._session)

    def test_add_inserts_parent_and_children(self) -> None:
        snapshot = _holdings_snapshot()
        self._session.execute.return_value.scalar_one_or_none.return_value = snapshot.id

        result = self._repo.add(snapshot)

        self.assertIs(result, snapshot)
        self._session.execute.assert_called_once()
        self.assertEqual(self._session.add_all.call_count, 1)
        added = self._session.add_all.call_args.args[0]
        self.assertEqual(len(added), len(snapshot.holdings))
        for child_row, holding in zip(added, snapshot.holdings, strict=True):
            self.assertEqual(child_row.snapshot_id, snapshot.id)
            self.assertEqual(child_row.stock_code, holding.stock_code)
            self.assertEqual(child_row.weight, holding.weight)
            self.assertEqual(child_row.industry, holding.industry)
            self.assertEqual(child_row.revision, snapshot.provenance.revision)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertEqual(params["id"], snapshot.id)
        self.assertEqual(params["etf_id"], snapshot.etf_id)
        self.assertEqual(params["as_of_date"], snapshot.as_of_date)
        self.assertEqual(params["content_hash"], snapshot.content_hash)
        self.assertEqual(params["revision"], snapshot.provenance.revision)
        self.assertEqual(
            params["source_provider"], snapshot.provenance.provider_key
        )
        self.assertEqual(
            params["source_batch_id"], snapshot.provenance.source_batch_id
        )

    def test_add_returns_existing_snapshot_on_hash_conflict(self) -> None:
        snapshot = _holdings_snapshot()
        existing_id = uuid4()
        existing = EtfHoldingSnapshot.create(
            etf_id=snapshot.etf_id,
            as_of_date=snapshot.as_of_date,
            observed_at=snapshot.provenance.observed_at,
            holdings=snapshot.holdings,
            provenance=snapshot.provenance,
            id_factory=lambda: existing_id,
            now_factory=lambda: snapshot.provenance.observed_at,
        )
        existing_row = _etf_holding_snapshot_row(existing)
        child_rows = tuple(
            _holding_row(existing.id, item, snapshot.provenance.revision)
            for item in snapshot.holdings
        )
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = existing_row
        self._session.scalars.return_value.all.return_value = list(child_rows)

        result = self._repo.add(snapshot)

        self.assertNotEqual(result.id, snapshot.id)
        self.assertEqual(result.id, existing_id)
        self._session.add_all.assert_not_called()

    def test_add_raises_when_conflict_but_row_missing(self) -> None:
        snapshot = _holdings_snapshot()
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(snapshot)
        self._session.add_all.assert_not_called()

    def test_get_by_id_reconstructs_snapshot_with_children(self) -> None:
        snapshot = _holdings_snapshot()
        parent_row = _etf_holding_snapshot_row(snapshot)
        child_rows = tuple(
            _holding_row(snapshot.id, item, snapshot.provenance.revision)
            for item in snapshot.holdings
        )
        self._session.get.return_value = parent_row
        self._session.scalars.return_value.all.return_value = list(child_rows)

        result = self._repo.get_by_id(snapshot.id)

        self.assertEqual(result.id, snapshot.id)
        self.assertEqual(result.etf_id, snapshot.etf_id)
        self.assertEqual(result.as_of_date, snapshot.as_of_date)
        self.assertEqual(
            tuple(
                (item.stock_code, item.weight, item.industry)
                for item in result.holdings
            ),
            tuple(
                (item.stock_code, item.weight, item.industry)
                for item in snapshot.holdings
            ),
        )
        self.assertEqual(result.content_hash, snapshot.content_hash)

    def test_get_by_id_returns_none_when_missing(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_list_by_etf_id_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_etf_id(uuid4(), limit=-1)

    def test_list_by_etf_id_rejects_negative_offset(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_etf_id(uuid4(), offset=-1)

    def test_list_by_etf_id_maps_snapshots(self) -> None:
        snapshot = _holdings_snapshot()
        child_rows = tuple(
            _holding_row(snapshot.id, item, snapshot.provenance.revision)
            for item in snapshot.holdings
        )
        parent_row = _etf_holding_snapshot_row(snapshot)
        parents_scalars = MagicMock()
        parents_scalars.all.return_value = [parent_row]
        children_scalars = MagicMock()
        children_scalars.all.return_value = list(child_rows)
        self._session.scalars.side_effect = [
            parents_scalars,
            children_scalars,
        ]

        result = self._repo.list_by_etf_id(snapshot.etf_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content_hash, snapshot.content_hash)


# ---------------------------------------------------------------------------
# Cross-aggregate invariant: IndexProfile.id must be reusable as
# EtfIndexMapping.index_id.
# ---------------------------------------------------------------------------


class CrossRepositoryIndexIdTests(unittest.TestCase):
    """The single most-load-bearing DC-3 storage invariant:

    the persisted ``IndexProfile.id`` must be reusable as the
    ``EtfIndexMapping.index_id`` so the application service can thread
    one UUID through both writes. The mapping can only persist if its
    ``index_id`` FK resolves to an existing ``core.indexes.id``,
    but the storage layer also carries that UUID as part of the
    domain-transport dataclass so the application can plan two writes
    without a second round-trip.
    """

    def test_index_id_matches_mapping_index_id(self) -> None:
        profile_session = MagicMock(spec=Session)
        mapping_session = MagicMock(spec=Session)

        profile = _profile()
        index_id = uuid4()
        persisted_id = uuid4()
        persisted_row = _index_profile_row(profile, persisted_id, index_id)
        profile_session.execute.return_value.scalar_one_or_none.return_value = persisted_id
        profile_session.scalars.return_value.first.return_value = persisted_row

        profile_repo = SqlAlchemyIndexProfileRepository(profile_session)
        stored_profile = profile_repo.add(profile, index_id)

        self.assertEqual(stored_profile.index_id, index_id)

        mapping = _mapping(
            etf_id=uuid4(),
            index_id=stored_profile.index_id,
        )
        self.assertEqual(mapping.index_id, stored_profile.index_id)

        persisted_mapping_id = uuid4()
        mapping_row = _etf_index_mapping_row(mapping, persisted_mapping_id)
        mapping_session.execute.return_value.scalar_one_or_none.return_value = persisted_mapping_id
        mapping_session.scalars.return_value.first.return_value = mapping_row

        mapping_repo = SqlAlchemyEtfIndexMappingRepository(mapping_session)
        stored_mapping = mapping_repo.add(mapping)

        self.assertEqual(stored_mapping.index_id, stored_profile.index_id)
        self.assertEqual(stored_mapping.index_id, index_id)
        mapping_stmt_params = mapping_session.execute.call_args.args[0].compile().params
        self.assertEqual(mapping_stmt_params["index_id"], stored_profile.index_id)


# ---------------------------------------------------------------------------
# UnitOfWork
# ---------------------------------------------------------------------------


class UoWExposureRepositoryTests(unittest.TestCase):
    """The five repos must be cached per-UoW and reset on exit."""

    def test_uow_exposes_cached_exposure_repositories(self) -> None:
        session = MagicMock(spec=Session)
        uow = SqlAlchemyUnitOfWork(lambda: session)
        with uow:
            self.assertIsInstance(
                uow.index_identities, SqlAlchemyIndexIdentityRepository
            )
            self.assertIs(
                uow.index_identities, uow.index_identities
            )
            self.assertIsInstance(
                uow.index_profiles, SqlAlchemyIndexProfileRepository
            )
            self.assertIs(
                uow.index_profiles, uow.index_profiles
            )
            self.assertIsInstance(
                uow.index_constituent_snapshots,
                SqlAlchemyIndexConstituentSnapshotRepository,
            )
            self.assertIs(
                uow.index_constituent_snapshots,
                uow.index_constituent_snapshots,
            )
            self.assertIsInstance(
                uow.etf_index_mappings, SqlAlchemyEtfIndexMappingRepository
            )
            self.assertIs(uow.etf_index_mappings, uow.etf_index_mappings)
            self.assertIsInstance(
                uow.etf_holding_snapshots, SqlAlchemyEtfHoldingSnapshotRepository
            )
            self.assertIs(
                uow.etf_holding_snapshots, uow.etf_holding_snapshots
            )


if __name__ == "__main__":
    unittest.main()
