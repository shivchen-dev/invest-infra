"""Unit tests for :func:`invest_pipeline.research_context_projection.load_context_projection`.

The helper is the application-layer gateway that rebuilds a
:class:`ContextProjection` from storage using a pre-loaded
case / run / pack trio. The tests inject hand-rolled fake
repositories that satisfy the structural UoW surface so the slice
can be exercised without booting the real database.

Coverage:

- success: bundle + snapshots line up, the projection is the
  deterministic ``build_projection`` output;
- missing bundle: bundle row absent from storage;
- missing snapshot: snapshot row absent from storage;
- mismatch matrix: hash / as_of_date / quality_status /
  freshness_status drift;
- legacy None: ``run.evidence_bundle_id`` is ``None``.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from invest_domain.analytics.market_observations import (
    MarketObservation,
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
    ContextProjection,
    DataQuality,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    ResearchEvidenceBundle,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun, ResearchRunStatus
from invest_pipeline.research_context_projection import (
    ContextProjectionLoadError,
    load_context_projection,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSTRUMENT_ID = InstrumentId(UUID("11111111-1114-4118-9111-111111111111"))
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_BUNDLE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_RUN_ID = UUID("33333333-3334-4338-9333-333333333333")

_AS_OF = date(2026, 3, 6)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
_HORIZON = "20-60d"
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)
_CREATED_AT = datetime(2026, 3, 6, 7, tzinfo=UTC)
_INPUT_SNAPSHOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _bars(count: int) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
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
                source=_SOURCE,
                revision=1,
                currency=Currency.CNY,
            )
        )
    return tuple(out)


def _build_pack() -> EvidencePack:
    selected = _bars(65)
    calculation = calculate_market_state_factors(
        selected, as_of_date=selected[-1].trade_date, instrument_id=_INSTRUMENT_ID
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF,
            question=_QUESTION,
            horizon=_HORIZON,
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
        pack_id=_PACK_ID,
    )


def _market_snapshot(
    *,
    snapshot_input_id: UUID = _INPUT_SNAPSHOT_ID,
    snapshot_as_of: date = _AS_OF,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    freshness_status: FreshnessStatus = FreshnessStatus.FRESH,
) -> MarketObservationSnapshot:
    observation = MarketObservation(
        observation_key="market_temperature_score",
        value=Decimal("0.5"),
        unit="score",
        observed_date=snapshot_as_of,
        source_kind="analytics",
        source_ref="market_temperature:1.0.0",
        quality_status=quality_status,
    )
    return MarketObservationSnapshot(
        input_snapshot_id=snapshot_input_id,
        as_of_date=snapshot_as_of,
        observations=(observation,),
        quality_status=quality_status,
        freshness_status=freshness_status,
    )


def _build_case(
    pack: EvidencePack, *, status: ResearchCaseStatus = ResearchCaseStatus.READY
) -> ResearchCase:
    return ResearchCase(
        case_id=_CASE_ID,
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=status,
        created_at=_CREATED_AT,
        closed_at=None,
    )


def _build_run(
    pack: EvidencePack,
    *,
    evidence_bundle_id: UUID | None = _BUNDLE_ID,
    status: ResearchRunStatus = ResearchRunStatus.QUEUED,
    started_at: datetime | None = None,
) -> ResearchRun:
    run = ResearchRun.create(
        case_id=_CASE_ID,
        evidence_pack_id=pack.pack_id,
        runner_key="jiuwenswarm-runner-v1",
        playbook_key="etf_medium_term_assessment",
        evidence_bundle_id=evidence_bundle_id,
    )
    if status is ResearchRunStatus.QUEUED:
        return run
    if started_at is None:
        started_at = _CREATED_AT + timedelta(minutes=1)
    running = run.start(occurred_at=started_at)
    if status is ResearchRunStatus.RUNNING:
        return running
    if status is ResearchRunStatus.SUCCEEDED:
        return running.succeed(occurred_at=started_at + timedelta(seconds=30))
    raise AssertionError(f"unsupported test status {status!r}")


def _build_bundle(
    pack: EvidencePack,
    *,
    snapshots: tuple[MarketObservationSnapshot, ...] = (),
    bundle_id: UUID = _BUNDLE_ID,
) -> ResearchEvidenceBundle:
    return ResearchEvidenceBundle.build(
        evidence_pack=pack,
        market_snapshots=snapshots,
        bundle_id=bundle_id,
        created_at=_CREATED_AT + timedelta(minutes=2),
    )


# ---------------------------------------------------------------------------
# Fake UoW
# ---------------------------------------------------------------------------


@dataclass
class _FakeBundleRepo:
    by_id: dict[UUID, ResearchEvidenceBundle] = field(default_factory=dict)

    def get_by_id(self, bundle_id: UUID) -> ResearchEvidenceBundle | None:
        return self.by_id.get(bundle_id)


@dataclass
class _FakeSnapshotRepo:
    by_content_hash: dict[str, MarketObservationSnapshot] = field(
        default_factory=dict
    )

    def get_by_content_hash(
        self, content_hash: str
    ) -> MarketObservationSnapshot | None:
        return self.by_content_hash.get(content_hash)


@dataclass
class _FakeUoW:
    bundles: _FakeBundleRepo
    snapshots: _FakeSnapshotRepo

    def __getattr__(self, name: str) -> Any:
        if name == "research_evidence_bundles":
            return self.bundles
        if name == "market_observation_snapshots":
            return self.snapshots
        raise AttributeError(f"'_FakeUoW' object has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class LoadContextProjectionSuccessTest(unittest.TestCase):
    """The happy path returns the deterministic ContextProjection."""

    def test_returns_projection_for_aligned_bundle_and_snapshots(self) -> None:
        pack = _build_pack()
        snapshot = _market_snapshot()
        bundle = _build_bundle(pack, snapshots=(snapshot,))
        case = _build_case(pack)
        run = _build_run(pack)

        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={snapshot.content_hash: snapshot}
            ),
        )

        projection = load_context_projection(
            uow, case=case, run=run, evidence_pack=pack
        )

        self.assertIsInstance(projection, ContextProjection)
        self.assertEqual(projection.bundle_id, bundle.bundle_id)
        self.assertEqual(projection.bundle_hash, bundle.bundle_hash)
        self.assertEqual(projection.evidence_pack_id, pack.pack_id)
        self.assertEqual(projection.evidence_pack_hash, pack.pack_hash)
        self.assertEqual(projection.research_case_id, case.case_id)
        self.assertEqual(projection.as_of_date, case.as_of_date)
        self.assertEqual(projection.market_snapshot_ids, (snapshot.snapshot_id,))
        self.assertEqual(projection.schema_version, bundle.schema_version)


class LoadContextProjectionMissingBundleTest(unittest.TestCase):
    """A bundle id that resolves to no row fails closed."""

    def test_missing_bundle_raises_load_error(self) -> None:
        pack = _build_pack()
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(),
            snapshots=_FakeSnapshotRepo(),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("did not find", str(ctx.exception))
        self.assertIn(str(_BUNDLE_ID), str(ctx.exception))


class LoadContextProjectionMissingSnapshotTest(unittest.TestCase):
    """A bundle ref that resolves to no snapshot row fails closed."""

    def test_missing_snapshot_raises_load_error(self) -> None:
        pack = _build_pack()
        snapshot = _market_snapshot()
        bundle = _build_bundle(pack, snapshots=(snapshot,))
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("MarketObservationSnapshot", str(ctx.exception))
        self.assertIn(snapshot.content_hash, str(ctx.exception))


class LoadContextProjectionMismatchTest(unittest.TestCase):
    """Hash / date / quality drift between bundle refs and storage rows."""

    def _aligned_uow(
        self,
        pack: EvidencePack,
        bundle: ResearchEvidenceBundle,
        snapshot: MarketObservationSnapshot,
    ) -> _FakeUoW:
        return _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={snapshot.content_hash: snapshot}
            ),
        )

    def test_content_hash_mismatch_raises_load_error(self) -> None:
        pack = _build_pack()
        bundle_snapshot = _market_snapshot(
            snapshot_input_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        )
        bundle = _build_bundle(pack, snapshots=(bundle_snapshot,))
        # A different snapshot with a different content_hash than the bundle ref
        stale_snapshot = _market_snapshot(
            snapshot_input_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        )
        case = _build_case(pack)
        run = _build_run(pack)
        uow = self._aligned_uow(pack, bundle, stale_snapshot)

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("content_hash", str(ctx.exception))

    def test_as_of_date_mismatch_raises_load_error(self) -> None:
        pack = _build_pack()
        bundle_snapshot = _market_snapshot(snapshot_as_of=_AS_OF)
        bundle = _build_bundle(pack, snapshots=(bundle_snapshot,))
        # Bypass the auto-derived content_hash to produce a row whose
        # content_hash matches the bundle ref but whose as_of_date
        # disagrees with it (simulates in-place DB tampering).
        tampered_snapshot = _market_snapshot(snapshot_as_of=_AS_OF)
        object.__setattr__(tampered_snapshot, "as_of_date", date(2026, 3, 7))
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={
                    bundle_snapshot.content_hash: tampered_snapshot,
                }
            ),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("as_of_date", str(ctx.exception))

    def test_quality_status_not_complete_raises_load_error(self) -> None:
        pack = _build_pack()
        snapshot = _market_snapshot(quality_status=QualityStatus.PARTIAL)
        bundle = _build_bundle(pack, snapshots=(snapshot,))
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={snapshot.content_hash: snapshot}
            ),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("quality_status", str(ctx.exception))
        self.assertIn(QualityStatus.COMPLETE.value, str(ctx.exception))

    def test_freshness_status_not_fresh_raises_load_error(self) -> None:
        pack = _build_pack()
        snapshot = _market_snapshot(freshness_status=FreshnessStatus.STALE)
        bundle = _build_bundle(pack, snapshots=(snapshot,))
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={bundle.bundle_id: bundle}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={snapshot.content_hash: snapshot}
            ),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("freshness_status", str(ctx.exception))
        self.assertIn(FreshnessStatus.FRESH.value, str(ctx.exception))

    def test_evidence_pack_hash_mismatch_raises_load_error(self) -> None:
        pack = _build_pack()
        snapshot = _market_snapshot()
        bundle = _build_bundle(pack, snapshots=(snapshot,))
        # Forge a bundle whose evidence_pack_hash disagrees with the pack.
        # Passing an empty bundle_hash skips the canonical re-validation in
        # ``__post_init__``; load_context_projection must still detect the
        # hash drift before any other check fires.
        from dataclasses import replace

        forged = replace(bundle, evidence_pack_hash="0" * 64, bundle_hash="")
        case = _build_case(pack)
        run = _build_run(pack)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(by_id={forged.bundle_id: forged}),
            snapshots=_FakeSnapshotRepo(
                by_content_hash={snapshot.content_hash: snapshot}
            ),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("evidence_pack_hash", str(ctx.exception))


class LoadContextProjectionLegacyNoneTest(unittest.TestCase):
    """A run with no evidence_bundle_id never returns None."""

    def test_none_bundle_id_raises_load_error(self) -> None:
        pack = _build_pack()
        case = _build_case(pack)
        run = _build_run(pack, evidence_bundle_id=None)
        uow = _FakeUoW(
            bundles=_FakeBundleRepo(),
            snapshots=_FakeSnapshotRepo(),
        )

        with self.assertRaises(ContextProjectionLoadError) as ctx:
            load_context_projection(uow, case=case, run=run, evidence_pack=pack)
        self.assertIn("evidence_bundle_id", str(ctx.exception))
        self.assertIn("opt out", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()