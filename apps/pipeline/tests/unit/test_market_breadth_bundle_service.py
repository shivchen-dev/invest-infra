"""Focused unit tests for the Stage 4B Market Breadth bundle service.

The service is the smallest possible vertical cut that wires one
:class:`invest_domain.analytics.market_observations.MarketObservationSnapshot`
(``scope_type=ashare_universe`` / ``scope_key=ashare_active_universe_v1``)
into a fresh :class:`invest_domain.research.evidence_bundle.ResearchEvidenceBundle`.
The contract is verified end-to-end through a hand-rolled fake UoW so
the suite never boots a real database:

* :class:`MarketBreadthBundleHappyPathTest` covers the canonical
  ``evidence_pack_id`` -> ``EvidencePack`` -> ``MarketObservationSnapshot``
  -> ``ResearchEvidenceBundle`` flow, including the deterministic
  ``bundle_hash`` / ``bundle_id`` and the expected
  ``market_snapshot_refs`` projection.
* :class:`MarketBreadthBundleFailureTest` exercises the fail-closed
  branches: a missing :class:`EvidencePack`, a missing Market Breadth
  snapshot, an ``as_of_date`` drift between the case and the snapshot,
  and the ``quality_status != COMPLETE`` / ``freshness_status != FRESH``
  rejection branches.
* :class:`MarketBreadthBundleUoWTest` asserts the single-UoW
  transaction boundary: the service commits exactly once on the happy
  path and never commits on a failure path so the read + write
  succeed / fail atomically.

Idempotency on same input (``bundle_hash``-based natural key) is the
repository contract and is exercised in
``tests/storage/test_research_evidence_bundle_repository_mock.py``;
the service is a thin broker and does not re-implement it.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from invest_domain.analytics.market_breadth import (
    MarketBreadthInput,
    build_market_breadth,
)
from invest_domain.analytics.market_observations import (
    MarketObservationSnapshot,
)
from invest_domain.instruments import InstrumentId
from invest_domain.market_data import (
    Adjust,
    BarSource,
    Currency,
    DailyBar,
    TradingStatus,
)
from invest_domain.research import (
    CandidateContext,
    CaseContext,
    DataQuality,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    ResearchEvidenceBundle,
    SourceReference,
    calculate_market_state_factors,
)
from invest_pipeline.market_breadth_bundle_service import (
    MARKET_BREADTH_SCOPE_KEY,
    MARKET_BREADTH_SCOPE_TYPE,
    MarketBreadthBundleEvidencePackMissingError,
    MarketBreadthBundleInputError,
    MarketBreadthBundleInvariantError,
    MarketBreadthBundleSnapshotMissingError,
    build_and_persist_market_breadth_bundle,
)

_AS_OF = date(2026, 8, 10)
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_INPUT_SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_INSTRUMENT_ID = InstrumentId(UUID("12345678-1234-5678-9234-567812345678"))
_CREATED_AT = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


def _build_bars(count: int) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    source = BarSource(
        provider_key="fixture_dev",
        source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        observed_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
    )
    out: list[DailyBar] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = Decimal(100 + index)
        out.append(
            DailyBar.build(
                instrument_id=_INSTRUMENT_ID,
                trade_date=trade_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                prev_close=None if index == 0 else Decimal(99 + index),
                volume=Decimal(1000 + index),
                amount=Decimal(1_000_000 + index * 1000),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=source,
                revision=1,
                currency=Currency.CNY,
            )
        )
    return tuple(out)


def _build_pack() -> EvidencePack:
    bars = _build_bars(65)
    calculation = calculate_market_state_factors(
        bars, as_of_date=bars[-1].trade_date, instrument_id=_INSTRUMENT_ID
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF,
            question="评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险",
            horizon="20-60d",
            case_id=_CASE_ID,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        candidate_context=CandidateContext(
            included=True, rank=1, total_score=Decimal("0.5"), exclusion_codes=()
        ),
        market_snapshot=MarketSnapshot(
            latest_trade_date=_AS_OF,
            latest_close=Decimal("164"),
            currency="CNY",
            observed_trading_days=65,
            valid_price_days=65,
        ),
        factors=tuple(reversed(calculation.factors)),
        data_quality=DataQuality(
            freshness_status=FreshnessStatus.FRESH,
            quality_status=QualityStatus.COMPLETE,
            target_trading_days=65,
            observed_trading_days=65,
            valid_price_days=65,
        ),
        source_refs=(
            SourceReference(
                source_kind="daily_bar",
                source_ref="core.daily_bars:2026-08-10",
                observed_date=_AS_OF,
                revision=1,
            ),
            SourceReference(
                source_kind="instrument",
                source_ref="core.instruments:510300",
                observed_date=_AS_OF,
            ),
        ),
        pack_id=_PACK_ID,
        generated_at=datetime(2026, 8, 10, 7, 0, tzinfo=UTC),
    )


def _build_market_breadth_snapshot(
    *,
    as_of_date: date = _AS_OF,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    freshness_status: FreshnessStatus = FreshnessStatus.FRESH,
) -> MarketObservationSnapshot:
    """Build a Market Breadth snapshot whose own metadata matches the case date.

    Defaults to ``COMPLETE / FRESH`` so the happy path stays in scope;
    failure tests override the explicit ``quality_status`` /
    ``freshness_status`` / ``as_of_date`` fields to exercise the
    fail-closed branches.
    """

    inputs: list[MarketBreadthInput] = []
    for index in range(3):
        inputs.append(
            MarketBreadthInput(
                instrument_id=InstrumentId(uuid4()),
                close=Decimal("11") if index % 2 == 0 else Decimal("9"),
                prev_close=Decimal("10"),
                ma20=Decimal("10"),
                observed_date=as_of_date,
                trading_status="normal",
            )
        )
    snapshot = build_market_breadth(
        input_snapshot_id=_INPUT_SNAPSHOT_ID,
        instruments=inputs,
        as_of_date=as_of_date,
    )
    if (
        snapshot.quality_status is not quality_status
        or snapshot.freshness_status is not freshness_status
    ):
        object.__setattr__(snapshot, "quality_status", quality_status)
        object.__setattr__(snapshot, "freshness_status", freshness_status)
    return snapshot


@dataclass
class _FakeEvidencePackRepo:
    """In-memory fake for ``research_evidence_packs.get_by_id``."""

    packs: dict[UUID, EvidencePack] = field(default_factory=dict)

    def get_by_id(self, pack_id: UUID) -> EvidencePack | None:
        return self.packs.get(pack_id)


@dataclass
class _FakeMarketObservationRepo:
    """In-memory fake for the Market Breadth read path."""

    snapshots_by_scope: dict[
        tuple[str, str, date], MarketObservationSnapshot
    ] = field(default_factory=dict)
    latest_calls: list[tuple[str, str, date | None]] = field(default_factory=list)

    def add(self, snapshot: MarketObservationSnapshot) -> MarketObservationSnapshot:
        return snapshot

    def get_latest_for_scope(
        self,
        scope_type: str,
        scope_key: str,
        as_of_date: date | None = None,
    ) -> MarketObservationSnapshot | None:
        self.latest_calls.append((scope_type, scope_key, as_of_date))
        if as_of_date is None:
            return None
        return self.snapshots_by_scope.get((scope_type, scope_key, as_of_date))


@dataclass
class _FakeEvidenceBundleRepo:
    """In-memory fake for the bundle persistence layer."""

    persisted: list[ResearchEvidenceBundle] = field(default_factory=list)
    add_calls: list[ResearchEvidenceBundle] = field(default_factory=list)

    def add(self, bundle: ResearchEvidenceBundle) -> ResearchEvidenceBundle:
        self.add_calls.append(bundle)
        self.persisted.append(bundle)
        return bundle


class _FakeUoW:
    def __init__(
        self,
        *,
        evidence_pack_repo: _FakeEvidencePackRepo,
        market_observation_repo: _FakeMarketObservationRepo,
        evidence_bundle_repo: _FakeEvidenceBundleRepo,
    ) -> None:
        self._evidence_packs = evidence_pack_repo
        self._market_observation_snapshots = market_observation_repo
        self._research_evidence_bundles = evidence_bundle_repo
        self.commit_count = 0
        self.rollback_count = 0
        self.in_use = False

    def __getattr__(self, name: str) -> Any:
        if name == "research_evidence_packs":
            return self._evidence_packs
        if name == "market_observation_snapshots":
            return self._market_observation_snapshots
        if name == "research_evidence_bundles":
            return self._research_evidence_bundles
        raise AttributeError(f"'_FakeUoW' object has no attribute {name!r}")

    def commit(self) -> None:
        if not self.in_use:
            raise AssertionError("commit() called outside 'with' block")
        self.commit_count += 1

    def rollback(self) -> None:
        if not self.in_use:
            raise AssertionError("rollback() called outside 'with' block")
        self.rollback_count += 1

    def __enter__(self) -> _FakeUoW:
        self.in_use = True
        return self

    def __exit__(self, *_args: Any) -> None:
        self.in_use = False


def _build_uow_factory(
    *,
    pack: EvidencePack | None,
    snapshot: MarketObservationSnapshot | None,
) -> tuple[
    Any, _FakeUoW, _FakeEvidencePackRepo, _FakeMarketObservationRepo, _FakeEvidenceBundleRepo
]:
    pack_repo = _FakeEvidencePackRepo()
    if pack is not None:
        pack_repo.packs[pack.pack_id] = pack
    observation_repo = _FakeMarketObservationRepo()
    if snapshot is not None:
        observation_repo.snapshots_by_scope[
            (MARKET_BREADTH_SCOPE_TYPE, MARKET_BREADTH_SCOPE_KEY, snapshot.as_of_date)
        ] = snapshot
    bundle_repo = _FakeEvidenceBundleRepo()
    uow = _FakeUoW(
        evidence_pack_repo=pack_repo,
        market_observation_repo=observation_repo,
        evidence_bundle_repo=bundle_repo,
    )
    return (
        lambda: uow,
        uow,
        pack_repo,
        observation_repo,
        bundle_repo,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class MarketBreadthBundleHappyPathTest(unittest.TestCase):
    """End-to-end happy path through the bundle service."""

    def test_builds_bundle_with_pinned_scope_and_evidence_pack_identity(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, uow, _p, _o, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        bundle = build_and_persist_market_breadth_bundle(
            uow_factory=uow_factory,
            evidence_pack_id=pack.pack_id,
            created_at=_CREATED_AT,
        )

        self.assertIsInstance(bundle, ResearchEvidenceBundle)
        self.assertEqual(bundle.research_case_id, pack.case.case_id)
        self.assertEqual(bundle.evidence_pack_id, pack.pack_id)
        self.assertEqual(bundle.evidence_pack_hash, pack.pack_hash)
        self.assertEqual(bundle.as_of_date, pack.case.as_of_date)
        self.assertEqual(bundle.schema_version, "1.0.0")
        # ``bundle_hash`` is derived from canonical content and must be
        # the same as the pure-domain builder's projection for the same
        # inputs.
        from invest_domain.research.evidence_bundle import compute_bundle_hash

        self.assertEqual(bundle.bundle_hash, compute_bundle_hash(bundle))

        # Single market snapshot is bound with a ref matching the
        # snapshot's content_hash / as_of_date.
        self.assertEqual(len(bundle.market_snapshot_refs), 1)
        ref = bundle.market_snapshot_refs[0]
        self.assertEqual(ref.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(ref.content_hash, snapshot.content_hash)
        self.assertEqual(ref.as_of_date, snapshot.as_of_date)

        self.assertEqual(bundle_repo.add_calls, [bundle])
        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(uow.rollback_count, 0)

    def test_lookup_passes_pinned_scope_and_case_as_of_date(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, _uow, _p, observation_repo, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        build_and_persist_market_breadth_bundle(
            uow_factory=uow_factory,
            evidence_pack_id=pack.pack_id,
            created_at=_CREATED_AT,
        )

        self.assertEqual(
            observation_repo.latest_calls,
            [
                (
                    MARKET_BREADTH_SCOPE_TYPE,
                    MARKET_BREADTH_SCOPE_KEY,
                    pack.case.as_of_date,
                )
            ],
        )

    def test_same_inputs_yield_same_bundle_hash_via_service(self) -> None:
        """Same pack + same snapshot produces an identical bundle_hash.

        The repository is responsible for idempotency on ``bundle_hash``;
        the service is verified here to forward the same canonical
        content to the bundle factory so a same-input re-run is safe.
        """

        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()

        def _run_once() -> ResearchEvidenceBundle:
            uow_factory, _uow, _p, _o, _b = _build_uow_factory(
                pack=pack, snapshot=snapshot
            )
            return build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        first = _run_once()
        second = _run_once()
        self.assertEqual(first.bundle_hash, second.bundle_hash)
        self.assertEqual(first.evidence_pack_hash, second.evidence_pack_hash)
        self.assertEqual(
            [item.content_hash for item in first.market_snapshot_refs],
            [item.content_hash for item in second.market_snapshot_refs],
        )

    def test_default_created_at_is_aware_utc(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        bundle = build_and_persist_market_breadth_bundle(
            uow_factory=uow_factory,
            evidence_pack_id=pack.pack_id,
        )

        self.assertIsNotNone(bundle.created_at.tzinfo)
        self.assertIsNotNone(bundle.created_at.utcoffset())


# ---------------------------------------------------------------------------
# Fail-closed branches
# ---------------------------------------------------------------------------


class MarketBreadthBundleFailureTest(unittest.TestCase):
    """Every failure mode the contract calls out is a typed exception."""

    def test_missing_evidence_pack_raises_pack_missing_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=None, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleEvidencePackMissingError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(ctx.exception.evidence_pack_id, pack.pack_id)
        self.assertIn(str(pack.pack_id), str(ctx.exception))

    def test_missing_market_breadth_snapshot_raises_snapshot_missing_error(
        self,
    ) -> None:
        pack = _build_pack()
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=None
        )

        with self.assertRaises(MarketBreadthBundleSnapshotMissingError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        exc = ctx.exception
        self.assertEqual(exc.as_of_date, pack.case.as_of_date)
        self.assertEqual(exc.scope_type, MARKET_BREADTH_SCOPE_TYPE)
        self.assertEqual(exc.scope_key, MARKET_BREADTH_SCOPE_KEY)
        self.assertIn("No Market Breadth snapshot", str(exc))

    def test_snapshot_as_of_mismatch_raises_invariant_error(self) -> None:
        pack = _build_pack()
        wrong_date = pack.case.as_of_date - timedelta(days=1)
        snapshot = _build_market_breadth_snapshot(as_of_date=wrong_date)
        # The repository lookup uses ``case.as_of_date`` as the
        # ``as_of_date`` filter; the test must seed the snapshot under
        # the case date so the service actually receives the
        # wrong-dated snapshot back from ``get_latest_for_scope``.
        uow_factory, _uow, _p, observation_repo, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )
        observation_repo.snapshots_by_scope[
            (
                MARKET_BREADTH_SCOPE_TYPE,
                MARKET_BREADTH_SCOPE_KEY,
                pack.case.as_of_date,
            )
        ] = snapshot
        observation_repo.snapshots_by_scope.pop(
            (
                MARKET_BREADTH_SCOPE_TYPE,
                MARKET_BREADTH_SCOPE_KEY,
                wrong_date,
            ),
            None,
        )

        with self.assertRaises(MarketBreadthBundleInvariantError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        exc = ctx.exception
        self.assertEqual(exc.reason, "as_of_mismatch")
        self.assertEqual(exc.snapshot_as_of_date, wrong_date)
        self.assertEqual(exc.case_as_of_date, pack.case.as_of_date)
        self.assertEqual(exc.snapshot_id, snapshot.snapshot_id)
        # The bundle must not be persisted when the snapshot fails the
        # contract.
        self.assertEqual(bundle_repo.add_calls, [])

    def test_snapshot_invalid_quality_raises_invariant_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot(
            quality_status=QualityStatus.INVALID,
            freshness_status=FreshnessStatus.FRESH,
        )
        uow_factory, _uow, _p, _o, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInvariantError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        exc = ctx.exception
        self.assertEqual(exc.reason, "quality_not_complete")
        self.assertEqual(exc.quality_status, QualityStatus.INVALID)
        self.assertEqual(bundle_repo.add_calls, [])

    def test_snapshot_stale_freshness_raises_invariant_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot(
            quality_status=QualityStatus.COMPLETE,
            freshness_status=FreshnessStatus.STALE,
        )
        uow_factory, _uow, _p, _o, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInvariantError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        exc = ctx.exception
        self.assertEqual(exc.reason, "freshness_not_fresh")
        self.assertEqual(exc.freshness_status, FreshnessStatus.STALE)
        self.assertEqual(bundle_repo.add_calls, [])

    def test_snapshot_failed_freshness_raises_invariant_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot(
            quality_status=QualityStatus.COMPLETE,
            freshness_status=FreshnessStatus.FAILED,
        )
        uow_factory, _uow, _p, _o, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInvariantError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(ctx.exception.reason, "freshness_not_fresh")
        self.assertEqual(bundle_repo.add_calls, [])

    def test_partial_quality_with_fresh_status_still_rejected(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot(
            quality_status=QualityStatus.PARTIAL,
            freshness_status=FreshnessStatus.FRESH,
        )
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInvariantError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(ctx.exception.reason, "quality_not_complete")


# ---------------------------------------------------------------------------
# UoW commit boundary
# ---------------------------------------------------------------------------


class MarketBreadthBundleUoWTest(unittest.TestCase):
    """The service must commit exactly once on success and never on failure."""

    def test_happy_path_commits_exactly_once(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        build_and_persist_market_breadth_bundle(
            uow_factory=uow_factory,
            evidence_pack_id=pack.pack_id,
            created_at=_CREATED_AT,
        )

        self.assertEqual(uow.commit_count, 1)
        self.assertEqual(uow.rollback_count, 0)

    def test_missing_pack_does_not_commit(self) -> None:
        pack = _build_pack()
        uow_factory, uow, _p, _o, _b = _build_uow_factory(
            pack=None, snapshot=None
        )

        with self.assertRaises(MarketBreadthBundleEvidencePackMissingError):
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(uow.commit_count, 0)

    def test_missing_snapshot_does_not_commit(self) -> None:
        pack = _build_pack()
        uow_factory, uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=None
        )

        with self.assertRaises(MarketBreadthBundleSnapshotMissingError):
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(uow.commit_count, 0)

    def test_invariant_failure_does_not_commit(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot(
            quality_status=QualityStatus.INVALID
        )
        uow_factory, uow, _p, _o, bundle_repo = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInvariantError):
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=_CREATED_AT,
            )

        self.assertEqual(uow.commit_count, 0)
        self.assertEqual(bundle_repo.add_calls, [])


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class MarketBreadthBundleInputValidationTest(unittest.TestCase):
    """Caller-side argument validation that happens before the UoW opens."""

    def test_non_uuid_evidence_pack_id_raises_input_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInputError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id="not-a-uuid",  # type: ignore[arg-type]
                created_at=_CREATED_AT,
            )

        self.assertIn("evidence_pack_id", str(ctx.exception))

    def test_naive_created_at_raises_input_error(self) -> None:
        pack = _build_pack()
        snapshot = _build_market_breadth_snapshot()
        uow_factory, _uow, _p, _o, _b = _build_uow_factory(
            pack=pack, snapshot=snapshot
        )

        with self.assertRaises(MarketBreadthBundleInputError) as ctx:
            build_and_persist_market_breadth_bundle(
                uow_factory=uow_factory,
                evidence_pack_id=pack.pack_id,
                created_at=datetime(2026, 8, 10, 8, 0),  # noqa: DTZ001 - naive datetime
            )

        self.assertIn("timezone-aware", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
