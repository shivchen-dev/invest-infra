"""Unit tests for the Stage 4B Market Breadth asset pair.

The slice wires the
:mod:`invest_pipeline.market_breadth_service` into two Dagster assets
without duplicating any calculation or persistence logic. The tests
exercise the slice-4B contract end-to-end through a hand-rolled fake
UoW so the suite never boots a real database.

* :class:`StockInputSnapshotAssetTest` pins the partition / dependency
  metadata for :func:`invest_pipeline.assets.stock_input_snapshot` and
  the happy path through the asset: the asset derives the stock
  universe from the persisted ``core.instruments`` table through
  :func:`invest_pipeline.market_breadth_service.list_active_stock_instrument_ids`,
  and persists the resulting :class:`InputSnapshot` through the
  existing :func:`create_input_snapshot` helper. The
  "empty-universe" case surfaces a hard
  :class:`StockUniverseEmptyError` so a misconfigured upstream
  ``stock_instruments`` materialisation fails closed rather than
  producing a partial snapshot.
* :class:`MarketBreadthSnapshotAssetTest` does the same for
  :func:`invest_pipeline.assets.market_breadth_snapshot`: the asset
  resolves the persisted input snapshot for the partition date,
  delegates to the breadth service, and surfaces the run / quality /
  freshness state through Dagster metadata. The "insufficient data"
  and "no snapshot persisted" cases surface ``skipped=True`` /
  ``invalid=True`` rather than raising so the slice never enters a
  Dagster retry loop on a contract-failure outcome.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import dagster as dg
import invest_storage
from invest_domain.analytics.market_observations import (
    MarketObservation,
    MarketObservationSnapshot,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_domain.research.models import FreshnessStatus, QualityStatus
from invest_pipeline import assets
from invest_pipeline.market_breadth_service import (
    MarketBreadthPublishResult,
    StockUniverseEmptyError,
)

_TRADE_DATE = date(2026, 8, 10)
_TRADE_DATE_HISTORICAL = date(2026, 7, 31)


def _instrument(symbol: str, instrument_id: UUID) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"{symbol} Co",
        exchange="SSE" if symbol.startswith(("5", "6")) else "SZSE",
        instrument_type=InstrumentType.STOCK,
        is_active=True,
        instrument_id=InstrumentId(instrument_id),
    )


def _patch_engine() -> MagicMock:
    engine = MagicMock(name="Engine")
    return engine


# ---------------------------------------------------------------------------
# stock_input_snapshot
# ---------------------------------------------------------------------------


class StockInputSnapshotAssetTest(unittest.TestCase):
    """``stock_input_snapshot`` wiring + happy path + empty-universe fail-closed."""

    def test_stock_input_snapshot_is_partitioned_and_depends_on_stock_instruments(self) -> None:
        assert isinstance(
            assets.stock_input_snapshot.partitions_def, dg.DailyPartitionsDefinition
        )
        assert dg.AssetKey("stock_instruments") in assets.stock_input_snapshot.dependency_keys

    def test_stock_input_snapshot_uses_partition_date_and_dynamic_active_stock_universe(
        self,
    ) -> None:
        ids = [uuid4(), uuid4()]
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        engine = _patch_engine()

        def _create(
            uow_factory: Any, snapshot_date: date, instrument_ids: list[UUID]
        ) -> InputSnapshot:
            return InputSnapshot.create(
                snapshot_date,
                instrument_ids,
                id_factory=lambda: UUID("10000000-0000-0000-0000-000000000000"),
                now_factory=lambda: datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
            )

        captured: dict[str, Any] = {}

        def _capturing_create(
            uow_factory: Any, snapshot_date: date, instrument_ids: list[UUID]
        ) -> InputSnapshot:
            captured["snapshot_date"] = snapshot_date
            captured["instrument_ids"] = instrument_ids
            return _create(uow_factory, snapshot_date, instrument_ids)

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(
                assets,
                "list_active_stock_instrument_ids",
                lambda _uow: list(ids),
            ),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(assets, "create_input_snapshot", _capturing_create),
        ):
            result = assets.stock_input_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert captured["snapshot_date"] == _TRADE_DATE
        assert captured["instrument_ids"] == ids
        assert result.metadata["partition_key"] == _TRADE_DATE.isoformat()
        assert result.metadata["row_count"] == len(ids)
        assert result.metadata["universe_size"] == len(ids)
        engine.dispose.assert_called_once_with()

    def test_stock_input_snapshot_does_not_consult_stock_universe_yaml(self) -> None:
        """The asset must NOT call ``load_stock_universe`` after the dynamic-universe slice.

        The persisted ``core.instruments`` table is the authoritative
        stock universe; consulting ``config/stock-universe.yaml``
        would silently couple the asset to a hand-curated symbol set
        and bypass the upstream ``stock_instruments`` materialisation.
        The wiring test explodes the call to surface a regression.
        """

        captured_calls: list[Any] = []

        def _explode_if_called(_path: Any) -> None:
            captured_calls.append(_path)
            raise RuntimeError("STOP_AFTER_LOAD_STOCK_UNIVERSE")

        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        engine = _patch_engine()

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(
                assets,
                "list_active_stock_instrument_ids",
                lambda _uow: [uuid4()],
            ),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(assets, "load_stock_universe", _explode_if_called),
        ):
            assets.stock_input_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert captured_calls == []
        engine.dispose.assert_called_once_with()

    def test_stock_input_snapshot_empty_universe_fails_closed(self) -> None:
        """An empty active ``STOCK`` universe fails closed with ``StockUniverseEmptyError``.

        The asset propagates :class:`StockUniverseEmptyError` rather
        than calling :func:`create_input_snapshot` with an empty
        list, so a misconfigured upstream ``stock_instruments``
        materialisation surfaces as a hard Dagster failure (Dagster
        surfaces uncaught exceptions as materialisation errors, not
        silent ``skipped`` / ``invalid`` skips). ``create_input_snapshot``
        is never invoked so the ``InputSnapshot`` row never appears in
        storage.
        """

        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        engine = _patch_engine()

        def _raise_empty(_uow: Any) -> list[UUID]:
            raise StockUniverseEmptyError(
                "no active STOCK rows in core.instruments; the dynamic "
                "stock universe is empty so stock_input_snapshot cannot "
                "persist a non-empty InputSnapshot — re-materialise "
                "stock_instruments before retrying"
            )

        create_spy = MagicMock(name="create_input_snapshot")

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(assets, "list_active_stock_instrument_ids", _raise_empty),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(assets, "create_input_snapshot", create_spy),
            self.assertRaises(StockUniverseEmptyError),
        ):
            assets.stock_input_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        create_spy.assert_not_called()
        engine.dispose.assert_called_once_with()


# ---------------------------------------------------------------------------
# market_breadth_snapshot
# ---------------------------------------------------------------------------


def _build_snapshot(
    *,
    snapshot_id: UUID | None = None,
    instrument_ids: tuple[UUID, ...] = (uuid4(), uuid4()),
    as_of: date = _TRADE_DATE,
) -> InputSnapshot:
    return InputSnapshot.create(
        as_of,
        instrument_ids,
        id_factory=lambda: snapshot_id or uuid4(),
        now_factory=lambda: datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
    )


def _build_breadth_snapshot(
    input_snapshot_id: UUID,
    *,
    quality: QualityStatus,
    freshness: FreshnessStatus,
    as_of: date = _TRADE_DATE,
) -> MarketObservationSnapshot:
    return MarketObservationSnapshot(
        input_snapshot_id=input_snapshot_id,
        as_of_date=as_of,
        observations=(
            MarketObservation(
                observation_key="advancing_ratio",
                value=None,
                unit="ratio",
                observed_date=as_of,
                source_kind="analytics",
                source_ref="market_breadth:1.0.0",
                quality_status=quality,
            ),
        ),
        quality_status=quality,
        freshness_status=freshness,
    )


class MarketBreadthSnapshotAssetTest(unittest.TestCase):
    """``market_breadth_snapshot`` wiring + happy path + skip paths."""

    def test_market_breadth_snapshot_is_partitioned_and_depends_on_inputs(self) -> None:
        assert isinstance(
            assets.market_breadth_snapshot.partitions_def, dg.DailyPartitionsDefinition
        )
        keys = assets.market_breadth_snapshot.dependency_keys
        assert dg.AssetKey("stock_input_snapshot") in keys
        assert dg.AssetKey("stock_daily_bars") in keys

    def test_market_breadth_snapshot_uses_partition_date_not_today(self) -> None:
        snapshot = _build_snapshot(as_of=_TRADE_DATE_HISTORICAL)
        repo = MagicMock(name="SnapshotRepo")
        repo.list_by_date = MagicMock(return_value=[snapshot])
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.input_snapshot_repository = repo
        engine = _patch_engine()

        captured: dict[str, Any] = {}

        def _fake_publish(
            *, uow_factory: Any, input_snapshot: InputSnapshot, as_of: date
        ) -> MarketBreadthPublishResult:
            captured["as_of"] = as_of
            captured["input_snapshot"] = input_snapshot
            breadth = _build_breadth_snapshot(
                input_snapshot.id,
                quality=QualityStatus.COMPLETE,
                freshness=FreshnessStatus.FRESH,
                as_of=as_of,
            )
            return MarketBreadthPublishResult(
                snapshot=breadth,
                input_snapshot=input_snapshot,
                instrument_count=2,
            )

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(
                assets, "calculate_and_publish_market_breadth", _fake_publish
            ),
        ):
            assets.market_breadth_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE_HISTORICAL.isoformat())
            )

        assert captured["as_of"] == _TRADE_DATE_HISTORICAL
        assert captured["as_of"] != date.today()
        engine.dispose.assert_called_once_with()

    def test_market_breadth_snapshot_happy_path_surfaces_metadata(self) -> None:
        snapshot = _build_snapshot()
        repo = MagicMock(name="SnapshotRepo")
        repo.list_by_date = MagicMock(return_value=[snapshot])
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.input_snapshot_repository = repo
        engine = _patch_engine()

        def _fake_publish(
            *, uow_factory: Any, input_snapshot: InputSnapshot, as_of: date
        ) -> MarketBreadthPublishResult:
            breadth = _build_breadth_snapshot(
                input_snapshot.id,
                quality=QualityStatus.COMPLETE,
                freshness=FreshnessStatus.FRESH,
            )
            return MarketBreadthPublishResult(
                snapshot=breadth,
                input_snapshot=input_snapshot,
                instrument_count=2,
            )

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(
                assets, "calculate_and_publish_market_breadth", _fake_publish
            ),
        ):
            result = assets.market_breadth_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert result.metadata["skipped"] is False
        assert result.metadata["invalid"] is False
        assert result.metadata["as_of"] == _TRADE_DATE.isoformat()
        assert result.metadata["partition_key"] == _TRADE_DATE.isoformat()
        assert result.metadata["instrument_count"] == 2
        assert result.metadata["quality_status"] == QualityStatus.COMPLETE.value
        assert result.metadata["freshness_status"] == FreshnessStatus.FRESH.value
        assert result.metadata["input_snapshot_id"] == str(snapshot.id)
        engine.dispose.assert_called_once_with()

    def test_market_breadth_snapshot_skips_when_no_snapshot_persisted(self) -> None:
        repo = MagicMock(name="SnapshotRepo")
        repo.list_by_date = MagicMock(return_value=[])
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.input_snapshot_repository = repo
        engine = _patch_engine()

        service_invoked = MagicMock(name="calculate_and_publish_market_breadth")

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(
                assets, "calculate_and_publish_market_breadth", service_invoked
            ),
        ):
            result = assets.market_breadth_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert result.metadata["skipped"] is True
        assert result.metadata["invalid"] is True
        assert result.metadata["instrument_count"] == 0
        assert _TRADE_DATE.isoformat() in result.metadata["reason"]
        assert "stock_input_snapshot" in result.metadata["reason"]
        service_invoked.assert_not_called()
        engine.dispose.assert_called_once_with()

    def test_market_breadth_snapshot_skips_when_service_publishes_invalid_snapshot(self) -> None:
        """A persisted ``INVALID / FAILED`` snapshot must surface as ``skipped`` / ``invalid``.

        The breadth service fail-closes when any instrument lacks a
        valid 20-day history (the all-filtered or mixed valid+missing
        cases) and the resulting snapshot is the deterministic
        ``INVALID / FAILED`` shape. The asset must mirror that as
        ``skipped=True`` / ``invalid=True`` with a ``reason`` instead
        of raising, so Dagster does not enter a retry loop on a
        contract-failure outcome. ``skipped=False`` is reserved for
        the ``COMPLETE`` / ``FRESH`` success path.
        """

        snapshot = _build_snapshot()
        repo = MagicMock(name="SnapshotRepo")
        repo.list_by_date = MagicMock(return_value=[snapshot])
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.input_snapshot_repository = repo
        engine = _patch_engine()

        def _fake_publish(
            *, uow_factory: Any, input_snapshot: InputSnapshot, as_of: date
        ) -> MarketBreadthPublishResult:
            breadth = _build_breadth_snapshot(
                input_snapshot.id,
                quality=QualityStatus.INVALID,
                freshness=FreshnessStatus.FAILED,
                as_of=as_of,
            )
            return MarketBreadthPublishResult(
                snapshot=breadth,
                input_snapshot=input_snapshot,
                instrument_count=0,
            )

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(
                assets, "calculate_and_publish_market_breadth", _fake_publish
            ),
        ):
            result = assets.market_breadth_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert result.metadata["skipped"] is True
        assert result.metadata["invalid"] is True
        assert result.metadata["instrument_count"] == 0
        assert result.metadata["quality_status"] == QualityStatus.INVALID.value
        assert result.metadata["freshness_status"] == FreshnessStatus.FAILED.value
        assert _TRADE_DATE.isoformat() in result.metadata["reason"]
        assert QualityStatus.INVALID.value in result.metadata["reason"]
        engine.dispose.assert_called_once_with()

    def test_market_breadth_snapshot_surfaces_partial_snapshot_as_skipped(self) -> None:
        """Non-``COMPLETE`` / non-``FRESH`` snapshots surface as ``skipped`` but ``invalid=False``.

        Defensive guard: a ``PARTIAL`` snapshot — distinct from the
        ``INVALID / FAILED`` shape — must still surface as ``skipped``
        so Dagster does not enter a retry loop, but the ``invalid``
        flag stays ``False`` because the snapshot itself is not
        tagged as contract-invalid. Operators rely on
        ``skipped=False`` meaning "COMPLETE / FRESH" exactly.
        """

        snapshot = _build_snapshot()
        repo = MagicMock(name="SnapshotRepo")
        repo.list_by_date = MagicMock(return_value=[snapshot])
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)
        uow.input_snapshot_repository = repo
        engine = _patch_engine()

        def _fake_publish(
            *, uow_factory: Any, input_snapshot: InputSnapshot, as_of: date
        ) -> MarketBreadthPublishResult:
            breadth = _build_breadth_snapshot(
                input_snapshot.id,
                quality=QualityStatus.PARTIAL,
                freshness=FreshnessStatus.FRESH,
                as_of=as_of,
            )
            return MarketBreadthPublishResult(
                snapshot=breadth,
                input_snapshot=input_snapshot,
                instrument_count=2,
            )

        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow),
            patch.object(
                assets, "calculate_and_publish_market_breadth", _fake_publish
            ),
        ):
            result = assets.market_breadth_snapshot.op.compute_fn.decorated_fn(
                dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
            )

        assert result.metadata["skipped"] is True
        assert result.metadata["invalid"] is False
        assert result.metadata["quality_status"] == QualityStatus.PARTIAL.value
        assert _TRADE_DATE.isoformat() in result.metadata["reason"]
