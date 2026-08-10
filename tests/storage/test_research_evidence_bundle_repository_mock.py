"""Mock-based unit tests for :class:`SqlAlchemyResearchEvidenceBundleRepository`.

Stage 4B Phase 3 persistence for ``analytics.research_evidence_bundles``
(migration ``20260811_0016``). The repository owns the round-trip
between the immutable :class:`ResearchEvidenceBundle` value object
and the storage row, including the immutable ``bundle_hash`` /
``(research_case_id, evidence_pack_id)`` unique constraints that
guard the audit-grade identity.

The tests use a fake ``Session`` so the unit suite stays fast and
deterministic and never needs a real database; the database CHECK /
UNIQUE / FK constraints are exercised by the integration suite.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.analytics.market_observations import (
    MarketObservationSnapshot,
)
from invest_domain.analytics.market_temperature import build_market_temperature
from invest_domain.instruments import InstrumentId
from invest_domain.research import ResearchEvidenceBundle
from invest_domain.research.models import FactorObservation, QualityStatus
from invest_storage import (
    ResearchEvidenceBundleRow,
    SqlAlchemyResearchEvidenceBundleRepository,
)
from sqlalchemy.orm import Session

_BASE = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
_CASE_ID = UUID("11111111-1111-4111-8111-111111111111")
_PACK_ID = UUID("22222222-2222-4222-8222-222222222222")
_PACK_HASH = "f" * 64
_INPUT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _observation(
    instrument_id: InstrumentId,
    factor_key: str,
    value: str,
) -> FactorObservation:
    return FactorObservation(
        factor_key=factor_key,
        instrument_id=instrument_id,
        value=Decimal(value),
        unit="ratio",
        window=20,
        observed_date=date(2026, 8, 7),
        quality_status=QualityStatus.COMPLETE,
    )


def _make_market_snapshot(input_id: UUID) -> MarketObservationSnapshot:
    instruments = [InstrumentId(UUID("00000000-0000-4000-8000-000000000001"))]
    return build_market_temperature(
        input_snapshot_id=input_id,
        factor_observations=tuple(
            _observation(instruments[0], key, value)
            for key, value in zip(
                (
                    "return_20d",
                    "realized_volatility_20d",
                    "avg_turnover_amount_20d",
                    "max_drawdown_60d",
                ),
                ("0.2", "0.3", "50000000", "0.1"),
                strict=True,
            )
        ),
        as_of_date=date(2026, 8, 7),
    )


def _make_bundle(
    *,
    market_snapshots: tuple[MarketObservationSnapshot, ...] = (),
    bundle_id: UUID | None = None,
) -> ResearchEvidenceBundle:
    bundle = ResearchEvidenceBundle.build(
        evidence_pack=__placeholder_pack(),  # type: ignore[arg-type]
        market_snapshots=market_snapshots,
        created_at=_BASE,
        bundle_id=bundle_id or uuid4(),
    )
    return bundle


class _BundleBuilder:
    """Mimic the relevant surface of :class:`EvidencePack` for bundle tests.

    The repository only reads ``case.case_id``, ``pack_id`` and
    ``pack_hash`` when persisting a bundle, so this lightweight
    stand-in keeps the test self-contained without forcing every
    test to instantiate a full :class:`EvidencePack` (which would
    pull the factor calculator machinery).
    """

    def __init__(self) -> None:
        self.case = type(
            "_Case",
            (),
            {"case_id": _CASE_ID, "as_of_date": date(2026, 8, 7)},
        )()
        self.pack_id = _PACK_ID
        self.pack_hash = _PACK_HASH


def __placeholder_pack():
    return _BundleBuilder()


def _row_for(bundle: ResearchEvidenceBundle) -> MagicMock:
    row = MagicMock(spec=ResearchEvidenceBundleRow)
    row.bundle_id = bundle.bundle_id
    row.research_case_id = bundle.research_case_id
    row.evidence_pack_id = bundle.evidence_pack_id
    row.evidence_pack_hash = bundle.evidence_pack_hash
    row.as_of_date = bundle.as_of_date
    row.market_snapshot_ids = [
        item.snapshot_id for item in bundle.market_snapshot_refs
    ]
    row.market_snapshot_hashes = [
        item.content_hash for item in bundle.market_snapshot_refs
    ]
    row.market_snapshot_dates = [
        item.as_of_date.isoformat() for item in bundle.market_snapshot_refs
    ]
    row.schema_version = bundle.schema_version
    row.bundle_hash = bundle.bundle_hash
    row.created_at = bundle.created_at
    return row


def _bundle_with_snapshot(
    snapshot: MarketObservationSnapshot,
    bundle_id: UUID | None = None,
) -> ResearchEvidenceBundle:
    builder = _BundleBuilder()
    return ResearchEvidenceBundle.build(
        evidence_pack=builder,  # type: ignore[arg-type]
        market_snapshots=(snapshot,),
        created_at=_BASE,
        bundle_id=bundle_id or uuid4(),
    )


class ResearchEvidenceBundleRepositoryMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyResearchEvidenceBundleRepository(self._session)

    def test_add_persists_row_with_expected_values(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            bundle.bundle_id
        )
        self._session.scalars.return_value.first.return_value = _row_for(bundle)

        result = self._repo.add(bundle)

        self.assertEqual(result, bundle)
        self._session.execute.assert_called_once()
        statement = self._session.execute.call_args.args[0]
        compiled = statement.compile()
        params = compiled.params
        self.assertEqual(params["bundle_id"], bundle.bundle_id)
        self.assertEqual(params["research_case_id"], _CASE_ID)
        self.assertEqual(params["evidence_pack_id"], _PACK_ID)
        self.assertEqual(params["evidence_pack_hash"], _PACK_HASH)
        self.assertEqual(params["as_of_date"], date(2026, 8, 7))
        self.assertEqual(
            params["market_snapshot_ids"], [snapshot.snapshot_id]
        )
        self.assertEqual(
            params["market_snapshot_hashes"], [snapshot.content_hash]
        )
        self.assertEqual(
            params["market_snapshot_dates"], [snapshot.as_of_date.isoformat()]
        )
        self.assertEqual(params["schema_version"], bundle.schema_version)
        self.assertEqual(params["bundle_hash"], bundle.bundle_hash)
        self.assertEqual(params["created_at"], _BASE)
        self._session.flush.assert_called_once()

    def test_add_returns_existing_after_conflict(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        existing = _row_for(bundle)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = existing

        result = self._repo.add(bundle)

        self.assertEqual(result, bundle)
        # The repository should fall back to the on_conflict path and
        # never re-insert. We only assert that exactly one execute
        # call (the original INSERT) was made.
        self.assertEqual(self._session.execute.call_count, 1)

    def test_add_raises_when_existing_row_not_found(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(bundle)

    def test_add_rejects_non_bundle_input(self) -> None:
        with self.assertRaises(TypeError):
            self._repo.add("not-a-bundle")  # type: ignore[arg-type]

    def test_get_by_id_round_trip(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        self._session.get.return_value = _row_for(bundle)

        result = self._repo.get_by_id(bundle.bundle_id)

        self.assertEqual(result, bundle)
        self._session.get.assert_called_once_with(
            ResearchEvidenceBundleRow, bundle.bundle_id
        )

    def test_get_by_id_returns_none_when_absent(self) -> None:
        self._session.get.return_value = None
        self.assertIsNone(self._repo.get_by_id(uuid4()))

    def test_get_by_bundle_hash_round_trip(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        self._session.scalars.return_value.first.return_value = _row_for(bundle)

        result = self._repo.get_by_bundle_hash(bundle.bundle_hash)

        self.assertEqual(result, bundle)

    def test_get_by_bundle_hash_returns_none_for_invalid_hash(self) -> None:
        self.assertIsNone(self._repo.get_by_bundle_hash("not-64-chars"))
        self.assertIsNone(self._repo.get_by_bundle_hash(""))
        self._session.scalars.assert_not_called()

    def test_get_by_case_and_pack_returns_matching_row(self) -> None:
        snapshot = _make_market_snapshot(_INPUT_ID)
        bundle = _bundle_with_snapshot(snapshot)
        self._session.scalars.return_value.first.return_value = _row_for(bundle)

        result = self._repo.get_by_case_and_pack(
            research_case_id=bundle.research_case_id,
            evidence_pack_id=bundle.evidence_pack_id,
        )

        self.assertEqual(result, bundle)
        statement = self._session.scalars.call_args.args[0]
        compiled = statement.compile()
        sql = str(compiled).upper()
        params = compiled.params
        self.assertIn("ORDER BY", sql)
        # Newest-first: ``created_at DESC`` with ``bundle_id DESC``
        # as the deterministic tie-break (see plan §4B Phase 3 — a
        # changed market snapshot set MUST create a new bundle, so
        # multiple rows for the same ``(case, pack)`` pair are legal).
        self.assertIn("CREATED_AT DESC", sql)
        self.assertIn("BUNDLE_ID DESC", sql)
        # LIMIT is rendered as a bound parameter, so we check the
        # bound param value rather than the literal text.
        self.assertEqual(
            [value for value in params.values() if value == 1],
            [1],
            "expected the LIMIT clause to bind the integer 1 so the "
            "repository picks a single deterministic row",
        )

    def test_get_by_case_and_pack_returns_none(self) -> None:
        self._session.scalars.return_value.first.return_value = None
        self.assertIsNone(
            self._repo.get_by_case_and_pack(
                research_case_id=_CASE_ID, evidence_pack_id=_PACK_ID
            )
        )

    def test_get_by_case_and_pack_picks_newest_when_multiple_coexist(self) -> None:
        """Multiple bundles for the same ``(case, pack)`` are legal.

        The plan requires a changed market snapshot set to create a
        new bundle identity and preserve history. The repo must
        therefore return the newest bundle (with a ``bundle_id`` DESC
        tie-break) so the application layer sees a deterministic
        "current" record.
        """

        snap_a = _make_market_snapshot(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
        snap_b = _make_market_snapshot(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
        bundle_older = _bundle_with_snapshot(snap_a)
        bundle_newer = _bundle_with_snapshot(snap_b)
        self._session.scalars.return_value.first.return_value = _row_for(bundle_newer)

        result = self._repo.get_by_case_and_pack(
            research_case_id=bundle_older.research_case_id,
            evidence_pack_id=bundle_older.evidence_pack_id,
        )

        self.assertEqual(result, bundle_newer)

    def test_list_by_case_orders_deterministically(self) -> None:
        snap_a = _make_market_snapshot(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
        snap_b = _make_market_snapshot(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
        bundle_a = _bundle_with_snapshot(snap_a, bundle_id=uuid4())
        bundle_b = _bundle_with_snapshot(snap_b, bundle_id=uuid4())
        rows = [_row_for(bundle_b), _row_for(bundle_a)]
        self._session.scalars.return_value.all.return_value = rows

        result = self._repo.list_by_case(bundle_a.research_case_id)

        self.assertEqual(result, [bundle_b, bundle_a])
        stmt = self._session.scalars.call_args.args[0]
        self.assertIsNotNone(stmt)

    def test_list_by_case_returns_empty_list(self) -> None:
        self._session.scalars.return_value.all.return_value = []
        self.assertEqual(self._repo.list_by_case(_CASE_ID), [])

    def test_round_trip_preserves_market_snapshot_refs(self) -> None:
        snap_a = _make_market_snapshot(UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
        snap_b = _make_market_snapshot(UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))
        bundle = ResearchEvidenceBundle.build(
            evidence_pack=_BundleBuilder(),  # type: ignore[arg-type]
            market_snapshots=(snap_a, snap_b),
            created_at=_BASE,
            bundle_id=uuid4(),
        )
        self._session.get.return_value = _row_for(bundle)

        result = self._repo.get_by_id(bundle.bundle_id)

        assert result is not None
        self.assertEqual(
            [item.snapshot_id for item in result.market_snapshot_refs],
            [item.snapshot_id for item in bundle.market_snapshot_refs],
        )
        self.assertEqual(
            [item.content_hash for item in result.market_snapshot_refs],
            [item.content_hash for item in bundle.market_snapshot_refs],
        )
        self.assertEqual(
            [item.as_of_date for item in result.market_snapshot_refs],
            [item.as_of_date for item in bundle.market_snapshot_refs],
        )
        self.assertEqual(result.bundle_hash, bundle.bundle_hash)
        self.assertEqual(result.evidence_pack_hash, bundle.evidence_pack_hash)
        self.assertEqual(result.as_of_date, bundle.as_of_date)
        self.assertEqual(result.schema_version, bundle.schema_version)
        self.assertEqual(result.research_case_id, bundle.research_case_id)
        self.assertEqual(result.evidence_pack_id, bundle.evidence_pack_id)
        self.assertEqual(result.created_at, bundle.created_at)


if __name__ == "__main__":
    unittest.main()
