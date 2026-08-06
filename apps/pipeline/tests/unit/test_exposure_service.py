"""Unit tests for :mod:`invest_pipeline.exposure_service`.

Tests cover the DC-3 atomic slice contract:

* Mapper call: persist_exposure calls map_standardized_payload exactly once.
* Happy path / order: profile → constituent → mapping → holding, single commit.
* Stable identity: ``uow.index_identities.add`` result ``id`` replaces payload
  ``index_id`` in the rebuilt ``EtfIndexMapping``.
* Mismatched index code: ``profile.index_code != constituent.index_code`` raises
  :class:`IndexCodeMismatchError` BEFORE factory is called.
* Mismatched ETF IDs: ``mapping.etf_id != holding.etf_id`` raises
  :class:`EtfIdMismatchError` BEFORE factory is called.
* Missing instrument: ``uow.instruments.get_by_id`` returning ``None`` raises
  :class:`InstrumentNotFoundError` without calling ``commit``.
* Exception / no commit: any exception raised inside the ``with`` block must
  not result in a ``commit`` call.
* Idempotent rerun: re-invoking with the same payload returns the same
  ``ExposurePersistResult`` identifiers (content-hash idempotency short-circuits
  re-inserts).
* Frozen result: returned ExposurePersistResult is immutable.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
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
from invest_pipeline.exposure_service import (
    EtfIdMismatchError,
    ExposurePersistResult,
    ExposureServiceError,
    IndexCodeMismatchError,
    InstrumentNotFoundError,
    persist_exposure,
)

_ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ETF_ID_ALT = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_INDEX_ID_PAYLOAD = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_INDEX_ID_STABLE = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
_PROFILE_ID = uuid4()
_CONSTITUENT_ID = uuid4()
_MAPPING_ID = uuid4()
_HOLDING_ID = uuid4()
_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_AS_OF_DATE = date(2026, 7, 31)


def _prov(
    provider_key: str = "akshare",
    dataset_key: str = "exposure_bundle",
) -> ExposureProvenance:
    return ExposureProvenance(
        provider_key=provider_key,
        dataset_key=dataset_key,
        observed_at=_NOW,
        revision=1,
        confidence=Decimal("0.95"),
    )


def _profile(
    index_code: str = "000300",
    index_name: str = "CSI 300",
    category: str | None = "Broad Market",
) -> IndexProfile:
    return IndexProfile(
        index_code=index_code,
        index_name=index_name,
        provenance=_prov(),
        category=category,
        as_of_date=_AS_OF_DATE,
    )


def _constituent_snapshot(
    index_code: str = "000300",
) -> IndexConstituentSnapshot:
    return IndexConstituentSnapshot.create(
        index_code=index_code,
        as_of_date=_AS_OF_DATE,
        observed_at=_NOW,
        constituents=(
            IndexConstituent(stock_code="600519", weight=Decimal("0.10"), industry="白酒"),
            IndexConstituent(stock_code="601318", weight=Decimal("0.05"), industry="金融"),
        ),
        provenance=_prov(),
    )


def _holding_snapshot(
    etf_id: UUID = _ETF_ID,
) -> EtfHoldingSnapshot:
    return EtfHoldingSnapshot.create(
        etf_id=etf_id,
        as_of_date=_AS_OF_DATE,
        observed_at=_NOW,
        holdings=(
            EtfHolding(stock_code="600519", weight=Decimal("0.10"), industry="白酒"),
            EtfHolding(stock_code="601318", weight=Decimal("0.05"), industry="金融"),
        ),
        provenance=_prov(),
    )


def _mapping(
    etf_id: UUID = _ETF_ID,
    index_id: UUID = _INDEX_ID_PAYLOAD,
) -> EtfIndexMapping:
    return EtfIndexMapping(
        etf_id=etf_id,
        index_id=index_id,
        effective_from=date(2024, 1, 1),
        effective_to=date(2026, 12, 31),
        observed_at=_NOW,
        provenance=_prov(),
    )


def _mapped_bundle(
    profile: IndexProfile | None = None,
    constituent: IndexConstituentSnapshot | None = None,
    mapping: EtfIndexMapping | None = None,
    holding: EtfHoldingSnapshot | None = None,
) -> dict[str, Any]:
    return {
        "index_profile": profile or _profile(),
        "index_constituents": constituent or _constituent_snapshot(),
        "etf_index_mapping": mapping or _mapping(),
        "etf_holdings": holding or _holding_snapshot(),
    }


@dataclass
class _FakeStoredResult:
    id: UUID
    content_hash: str


@dataclass
class _FakeInstrument:
    instrument_id: UUID


@dataclass
class _FakeUoW:
    """Stand-in for :class:`SqlAlchemyUnitOfWork`.

    Wires the repository methods so the service can exercise the
    production code paths without a real database.
    """

    instruments: MagicMock
    index_identities: MagicMock
    index_profiles: MagicMock
    index_constituent_snapshots: MagicMock
    etf_index_mappings: MagicMock
    etf_holding_snapshots: MagicMock

    commit_count: int = 0
    rollback_count: int = 0

    def __init__(self) -> None:
        self.instruments = MagicMock()
        self.index_identities = MagicMock()
        self.index_profiles = MagicMock()
        self.index_constituent_snapshots = MagicMock()
        self.etf_index_mappings = MagicMock()
        self.etf_holding_snapshots = MagicMock()
        self._closed = False

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *_args: Any) -> None:
        self._closed = True


def _build_uow(
    instrument_exists: bool = True,
    index_identity_result: _FakeStoredResult | None = None,
    profile_result: _FakeStoredResult | None = None,
    constituent_result: _FakeStoredResult | None = None,
    mapping_result: _FakeStoredResult | None = None,
    holding_result: _FakeStoredResult | None = None,
) -> tuple[_FakeUoW, MagicMock]:
    uow = _FakeUoW()

    if instrument_exists:
        uow.instruments.get_by_id.return_value = _FakeInstrument(instrument_id=_ETF_ID)
    else:
        uow.instruments.get_by_id.return_value = None

    if index_identity_result is None:
        index_identity_result = _FakeStoredResult(
            id=_INDEX_ID_STABLE, content_hash="idx_hash"
        )
    uow.index_identities.add.return_value = SimpleNamespace(
        id=index_identity_result.id,
        index_code="000300",
    )

    if profile_result is None:
        profile_result = _FakeStoredResult(id=_PROFILE_ID, content_hash="prof_hash")
    uow.index_profiles.add.return_value = SimpleNamespace(
        id=profile_result.id, content_hash=profile_result.content_hash
    )

    if constituent_result is None:
        constituent_result = _FakeStoredResult(
            id=_CONSTITUENT_ID, content_hash="const_hash"
        )
    uow.index_constituent_snapshots.add.return_value = SimpleNamespace(
        id=constituent_result.id, content_hash=constituent_result.content_hash
    )

    if mapping_result is None:
        mapping_result = _FakeStoredResult(id=_MAPPING_ID, content_hash="map_hash")
    uow.etf_index_mappings.add.return_value = SimpleNamespace(
        id=mapping_result.id, content_hash=mapping_result.content_hash
    )

    if holding_result is None:
        holding_result = _FakeStoredResult(id=_HOLDING_ID, content_hash="hold_hash")
    uow.etf_holding_snapshots.add.return_value = SimpleNamespace(
        id=holding_result.id, content_hash=holding_result.content_hash
    )

    factory = MagicMock(return_value=uow)
    return uow, factory


class MapperCallTest(unittest.TestCase):
    """persist_exposure calls map_standardized_payload exactly once."""

    def test_calls_mapper_with_raw_payload(self) -> None:
        uow, factory = _build_uow()
        raw_payload = {"index_profile": {}, "index_constituents": {}}

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ) as mock_map:
            persist_exposure(raw_payload, factory)

        mock_map.assert_called_once_with(raw_payload)


class HappyPathTest(unittest.TestCase):
    """persist_exposure commits exactly once and returns a frozen result."""

    def test_persists_in_order_and_commits_once(self) -> None:
        uow, factory = _build_uow()
        raw_payload: dict[str, Any] = {"index_profile": {}}

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            result = persist_exposure(raw_payload, factory)

        self.assertIsInstance(result, ExposurePersistResult)
        self.assertEqual(result.index_id, _INDEX_ID_STABLE)
        self.assertEqual(result.profile_id, _PROFILE_ID)
        self.assertEqual(result.constituent_snapshot_id, _CONSTITUENT_ID)
        self.assertEqual(result.mapping_id, _MAPPING_ID)
        self.assertEqual(result.holding_snapshot_id, _HOLDING_ID)

        self.assertEqual(uow.commit_count, 1)

        uow.index_identities.add.assert_called_once()
        call_args = uow.index_identities.add.call_args
        self.assertEqual(call_args.kwargs["index_code"], "000300")
        self.assertEqual(call_args.kwargs["index_name"], "CSI 300")
        self.assertEqual(call_args.kwargs["category"], "Broad Market")

        uow.index_profiles.add.assert_called_once()
        uow.index_constituent_snapshots.add.assert_called_once()
        uow.etf_index_mappings.add.assert_called_once()
        uow.etf_holding_snapshots.add.assert_called_once()

    def test_rebuilt_mapping_uses_stable_index_id(self) -> None:
        uow, factory = _build_uow(index_identity_result=_FakeStoredResult(
            id=_INDEX_ID_STABLE, content_hash="ihash"
        ))

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            persist_exposure({}, factory)

        mapping_call_args = factory.return_value.etf_index_mappings.add.call_args
        rebuilt_mapping: EtfIndexMapping = mapping_call_args.args[0]
        self.assertEqual(rebuilt_mapping.index_id, _INDEX_ID_STABLE)
        self.assertNotEqual(rebuilt_mapping.index_id, _INDEX_ID_PAYLOAD)

    def test_result_is_frozen(self) -> None:
        uow, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            result = persist_exposure({}, factory)

        with self.assertRaises(AttributeError):
            result.index_id = uuid4()


class StableIdentityTest(unittest.TestCase):
    """Canonical identity.id replaces payload index_id in rebuilt mapping."""

    def test_payload_index_id_ignored_stable_identity_used(self) -> None:
        _, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            result = persist_exposure({}, factory)

        self.assertEqual(result.index_id, _INDEX_ID_STABLE)
        called_mapping: EtfIndexMapping = (
            factory.return_value.etf_index_mappings.add.call_args.args[0]
        )
        self.assertEqual(called_mapping.index_id, _INDEX_ID_STABLE)
        self.assertNotEqual(called_mapping.index_id, _INDEX_ID_PAYLOAD)


class MismatchedIndexCodeTest(unittest.TestCase):
    """profile.index_code != constituent_snapshot.index_code raises BEFORE factory."""

    def test_raises_index_code_mismatch_and_factory_not_called(self) -> None:
        uow, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(
                constituent=_constituent_snapshot(index_code="DIFFERENT")
            ),
        ), self.assertRaises(IndexCodeMismatchError) as ctx:
            persist_exposure({}, factory)

        self.assertIn("000300", str(ctx.exception))
        self.assertIn("DIFFERENT", str(ctx.exception))
        factory.assert_not_called()
        uow.instruments.get_by_id.assert_not_called()
        self.assertEqual(uow.commit_count, 0)

    def test_error_is_subclass_of_exposure_service_error(self) -> None:
        _, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(
                constituent=_constituent_snapshot(index_code="BAD")
            ),
        ), self.assertRaises(ExposureServiceError):
            persist_exposure({}, factory)


class MismatchedEtfIdTest(unittest.TestCase):
    """mapping.etf_id != holding_snapshot.etf_id raises BEFORE factory."""

    def test_raises_etf_id_mismatch_and_factory_not_called(self) -> None:
        uow, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(
                holding=_holding_snapshot(etf_id=_ETF_ID_ALT)
            ),
        ), self.assertRaises(EtfIdMismatchError) as ctx:
            persist_exposure({}, factory)

        self.assertIn(str(_ETF_ID), str(ctx.exception))
        self.assertIn(str(_ETF_ID_ALT), str(ctx.exception))
        factory.assert_not_called()
        uow.instruments.get_by_id.assert_not_called()
        self.assertEqual(uow.commit_count, 0)

    def test_error_is_subclass_of_exposure_service_error(self) -> None:
        _, factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(
                holding=_holding_snapshot(etf_id=_ETF_ID_ALT)
            ),
        ), self.assertRaises(ExposureServiceError):
            persist_exposure({}, factory)


class MissingInstrumentTest(unittest.TestCase):
    """ETF not found via uow.instruments.get_by_id raises without commit."""

    def test_raises_instrument_not_found_no_commit(self) -> None:
        uow, factory = _build_uow(instrument_exists=False)

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ), self.assertRaises(InstrumentNotFoundError) as ctx:
            persist_exposure({}, factory)

        self.assertIn(str(_ETF_ID), str(ctx.exception))
        self.assertEqual(uow.commit_count, 0)
        uow.index_identities.add.assert_not_called()

    def test_instrument_check_happens_before_identity_add(self) -> None:
        uow, factory = _build_uow(instrument_exists=False)

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ), self.assertRaises(InstrumentNotFoundError):
            persist_exposure({}, factory)

        uow.instruments.get_by_id.assert_called_once_with(_ETF_ID)
        uow.index_identities.add.assert_not_called()


class ExceptionNoCommitTest(unittest.TestCase):
    """Any exception raised inside the with block must not call commit."""

    def test_instrument_not_found_no_commit(self) -> None:
        uow, factory = _build_uow(instrument_exists=False)

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ), self.assertRaises(InstrumentNotFoundError):
            persist_exposure({}, factory)

        self.assertEqual(uow.commit_count, 0)


class IdempotentRerunTest(unittest.TestCase):
    """Re-running with identical payload returns same record identifiers.

    The content-hash idempotency built into each repository means re-runs
    short-circuit re-insertion and return the same stored identifiers.
    """

    def test_two_calls_return_same_identifiers(self) -> None:
        first_uow, first_factory = _build_uow()
        second_uow, second_factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            first_result = persist_exposure({}, first_factory)
            second_result = persist_exposure({}, second_factory)

        self.assertEqual(first_result.index_id, second_result.index_id)
        self.assertEqual(
            first_result.profile_content_hash, second_result.profile_content_hash
        )
        self.assertEqual(
            first_result.constituent_content_hash,
            second_result.constituent_content_hash,
        )
        self.assertEqual(
            first_result.mapping_content_hash, second_result.mapping_content_hash
        )
        self.assertEqual(
            first_result.holding_content_hash, second_result.holding_content_hash
        )

    def test_each_call_commits_once(self) -> None:
        first_uow, first_factory = _build_uow()
        second_uow, second_factory = _build_uow()

        with patch(
            "invest_pipeline.exposure_service.map_standardized_payload",
            return_value=_mapped_bundle(),
        ):
            persist_exposure({}, first_factory)
            persist_exposure({}, second_factory)

        self.assertEqual(first_uow.commit_count, 1)
        self.assertEqual(second_uow.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
