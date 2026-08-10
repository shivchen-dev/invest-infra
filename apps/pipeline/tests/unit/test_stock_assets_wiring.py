"""Unit tests for the Stage 4B stock asset provider / loader wiring.

The four production stock assets (``stock_instruments_raw``,
``stock_instruments``, ``stock_daily_bars_raw``, ``stock_daily_bars``)
wrap the existing PR-02 / PR-05 / PR-06 service modules behind the
Tushare ``StockTushareProvider``. The slice wires a new Dagster asset
chain — the service layer is unchanged for the per-symbol baseline, and
the by-date batch path is additive — so the suite pins every relevant
invariant at the source / runtime boundary:

* :class:`StockAssetsSourceWiringTest` reads each production asset's
  source via :mod:`ast` and asserts:
  - ``stock_instruments_raw`` routes through ``build_stock_provider``,
    reuses ``write_etf_instruments_raw``, and never reaches for the
    ETF ``FixtureDevInstrumentProvider`` directly.
  - ``stock_instruments`` calls ``upsert_etf_instruments`` with
    explicit ``provider_key="tushare"`` / ``dataset_key="stock_instruments"``
    so the upstream lookup cannot collide with the ETF slice.
  - ``stock_daily_bars_raw`` routes through
    ``write_stock_daily_bars_raw_by_trade_date`` and stamps
    ``dataset_key="stock_daily_bars_by_date"`` so the by-date request
    cannot collide with the per-symbol ``stock_daily_bars`` baseline.
  - ``stock_daily_bars`` calls ``upsert_stock_daily_bars`` with
    ``dataset_key="stock_daily_bars_by_date"`` /
    ``request_key="daily-bars-by-date-{trade_date.isoformat()}"`` and
    surfaces a skipped ``MaterializeResult`` when the upstream request
    is missing or failed.

* :class:`StockAssetsRuntimeWiringTest` invokes each production asset's
  underlying callable (via
  ``AssetsDefinition.op.compute_fn.decorated_fn``) with a mocked
  context and patches :func:`invest_pipeline.assets.build_stock_provider`
  to a sentinel that raises immediately, so the suite verifies the
  factory call happens at runtime without booting a real database.

* :class:`StockDailyBarsByTradeDateAssetWiringTest` pins the
  by-trade-date wiring on both ``stock_daily_bars_raw`` (calls
  ``write_stock_daily_bars_raw_by_trade_date`` with the partition
  trade date) and ``stock_daily_bars`` (looks up
  ``(provider_key="tushare", dataset_key="stock_daily_bars_by_date",
  request_key="daily-bars-by-date-{trade_date.isoformat()}")``).

* :class:`StockAssetsSkippedBehaviourTest` exercises the
  ``MaterializeResult`` skip path: the upstream-request lookup returns
  ``None`` (no raw run yet) or ``failed`` (contract failure) and the
  asset must surface ``skipped=True`` without raising so the job does
  not enter a Dagster retry loop.

* :class:`SettingsStockUniversePathTest` pins the
  :attr:`Settings.stock_universe_path` setting — the path the loader
  receives must come from configuration, not from a hard-coded
  constant, so an operator can swap universes without editing the
  asset source. The setting is consumed by
  :func:`stock_input_snapshot` only; the by-date raw asset is
  universe-agnostic.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import dagster as dg
import invest_storage
from invest_pipeline import assets
from invest_pipeline.config import Settings
from invest_pipeline.stock_universe import StockUniverse

_FIXED_SYMBOLS: tuple[str, ...] = (
    "600519",
    "000001",
    "000858",
)
_FIXED_UNIVERSE = StockUniverse(version=1, symbols=_FIXED_SYMBOLS)
_HISTORICAL_PARTITION = "2026-07-31"
_HISTORICAL_DATE = date(2026, 7, 31)


def _assets_source() -> str:
    """Return the source text of :mod:`invest_pipeline.assets`."""

    src_path = Path(inspect.getsourcefile(assets) or "").resolve()
    return src_path.read_text(encoding="utf-8")


def _asset_body(name: str) -> str:
    """Return the source of the top-level function ``name`` in ``assets.py``.

    Dagster's ``@dg.asset`` decorator replaces the decorated function
    with an :class:`AssetsDefinition`, so :func:`inspect.getsource` on
    the attribute raises :class:`TypeError`. Parsing the module source
    with :mod:`ast` and slicing out the matching top-level
    :class:`ast.FunctionDef` body keeps the test independent of Dagster
    internals.
    """

    source = _assets_source()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node) or ""
            if segment:
                return segment
    raise AssertionError(f"top-level function {name!r} not found in assets.py")


def _underlying_callable(asset_name: str):
    """Return the unwrapped Python callable the Dagster ``@asset`` decorator wraps."""

    assets_def = getattr(assets, asset_name)
    return assets_def.op.compute_fn.decorated_fn


class StockAssetsSourceWiringTest(unittest.TestCase):
    """Source-level guarantee that the stock assets route through the right factory."""

    def test_stock_instruments_raw_calls_build_stock_provider_with_settings(self) -> None:
        body = _asset_body("stock_instruments_raw")
        self.assertIn("build_stock_provider(get_settings())", body)
        self.assertIn("write_etf_instruments_raw", body)

    def test_stock_instruments_invokes_upsert_with_tushare_stock_dataset(self) -> None:
        body = _asset_body("stock_instruments")
        self.assertIn("provider_key=\"tushare\"", body)
        self.assertIn("dataset_key=\"stock_instruments\"", body)
        self.assertIn("upsert_etf_instruments", body)

    def test_stock_daily_bars_raw_uses_by_trade_date_provider_path(self) -> None:
        body = _asset_body("stock_daily_bars_raw")
        self.assertIn("build_stock_provider(settings)", body)
        self.assertIn("write_stock_daily_bars_raw_by_trade_date", body)
        # ``stock_daily_bars_raw`` must surface the by-date dataset_key
        # in metadata so an operator can audit which logical-request
        # window a partition materialised.
        self.assertIn("\"stock_daily_bars_by_date\"", body)
        # The asset must NOT route through the per-symbol
        # ``write_stock_daily_bars_raw`` baseline — the additive by-date
        # function is the wired path. The per-symbol helper is still
        # exported and is preserved for any direct caller.
        self.assertNotIn("write_stock_daily_bars_raw(", body)
        # Hard-coded "ts_code" / "all market" defaults must not leak in.
        self.assertNotIn("fetch_stock_basic", body)
        self.assertNotIn("stock_basic", body)

    def test_stock_daily_bars_uses_by_date_dataset_key_and_request_key(self) -> None:
        body = _asset_body("stock_daily_bars")
        self.assertIn("build_stock_provider(settings)", body)
        self.assertIn("dataset_key=\"stock_daily_bars_by_date\"", body)
        self.assertIn("upsert_stock_daily_bars", body)
        # Must surface a skipped MaterializeResult rather than raising
        # so a missing or failed upstream attempt does not enter a
        # Dagster retry loop.
        self.assertIn("skipped_asset", body)
        self.assertIn("upstream attempt failed or missing", body)

    def test_stock_assets_do_not_directly_instantiate_etf_fixture(self) -> None:
        for name in (
            "stock_instruments_raw",
            "stock_instruments",
            "stock_daily_bars_raw",
            "stock_daily_bars",
        ):
            with self.subTest(asset=name):
                self.assertNotIn(
                    "FixtureDevInstrumentProvider()",
                    _asset_body(name),
                    f"{name} must not directly construct "
                    "FixtureDevInstrumentProvider; use build_stock_provider",
                )

    def test_stock_assets_do_not_use_etf_provider_factory(self) -> None:
        # The stock chain must not route through ``build_provider`` —
        # that helper returns an ``EtfMarketDataProvider`` and the stock
        # slice needs the dedicated ``StockTushareProvider`` instance.
        for name in (
            "stock_instruments_raw",
            "stock_daily_bars_raw",
            "stock_daily_bars",
        ):
            with self.subTest(asset=name):
                self.assertNotIn(
                    "build_provider(get_settings())",
                    _asset_body(name),
                    f"{name} must call build_stock_provider, not build_provider",
                )


class StockAssetsRuntimeWiringTest(unittest.TestCase):
    """Runtime guarantee that the stock assets actually invoke the factory."""

    def _invoke_and_capture(
        self,
        asset_name: str,
    ) -> list[Settings]:
        captured: list[Settings] = []

        def _raise_after_capture(settings: Settings) -> MagicMock:
            captured.append(settings)
            raise RuntimeError("STOP_AFTER_BUILD_STOCK_PROVIDER")

        context = MagicMock()
        context.partition_key = _HISTORICAL_PARTITION
        fn = _underlying_callable(asset_name)
        with (
            patch(
                "invest_pipeline.assets.build_stock_provider",
                side_effect=_raise_after_capture,
            ),
            self.assertRaises(RuntimeError),
        ):
            fn(context)
        return captured

    def _assert_factory_called_with_settings(self, asset_name: str) -> None:
        captured = self._invoke_and_capture(asset_name)
        self.assertEqual(
            len(captured),
            1,
            f"{asset_name} must call build_stock_provider exactly once",
        )
        self.assertIsInstance(
            captured[0],
            Settings,
            f"{asset_name} must pass a Settings instance to build_stock_provider",
        )

    def test_stock_instruments_raw_invokes_build_stock_provider(self) -> None:
        self._assert_factory_called_with_settings("stock_instruments_raw")

    def test_stock_daily_bars_raw_invokes_build_stock_provider(self) -> None:
        self._assert_factory_called_with_settings("stock_daily_bars_raw")

    def test_stock_daily_bars_invokes_build_stock_provider(self) -> None:
        self._assert_factory_called_with_settings("stock_daily_bars")


class StockDailyBarsByTradeDateAssetWiringTest(unittest.TestCase):
    """The ``stock_daily_bars_raw`` / ``stock_daily_bars`` assets use the by-trade-date path.

    Stage 4B narrows the ``stock_daily_bars_raw`` asset to the by-date
    ``StockTushareProvider.fetch_daily_bars_by_trade_date`` provider
    call (one HTTP roundtrip per trade date, every A-share daily bar
    for that date), and ``stock_daily_bars`` looks up the persisted
    request via the by-date logical key
    ``(provider_key='tushare',
    dataset_key='stock_daily_bars_by_date',
    request_key='daily-bars-by-date-{trade_date.isoformat()}')``. The
    upstream ``load_stock_universe`` / symbols-based projection is no
    longer consulted by the daily-bars chain; ``stock_input_snapshot``
    keeps the universe, untouched.
    """

    def _invoke_raw_with_capture(self) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def _fake_write(
            provider: Any,
            session_factory: Any,
            *,
            trade_date: date,
            unit_of_work_factory: Any = None,
        ) -> Any:
            captured["trade_date"] = trade_date
            from uuid import uuid4

            return SimpleNamespace(
                request_id=uuid4(),
                attempt_id=uuid4(),
                batch_id=uuid4(),
                request_status="succeeded",
                attempt_status="succeeded",
                record_count=7,
            )

        engine = MagicMock()
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(assets, "build_stock_provider", lambda _settings: MagicMock()),
            patch.object(
                assets, "write_stock_daily_bars_raw_by_trade_date", _fake_write
            ),
        ):
            result = _underlying_callable("stock_daily_bars_raw")(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )
        captured["result"] = result
        return captured

    def test_raw_asset_invokes_by_trade_date_write_with_partition_date(self) -> None:
        captured = self._invoke_raw_with_capture()
        self.assertEqual(captured["trade_date"], _HISTORICAL_DATE)
        self.assertEqual(captured["result"].metadata["trade_date"], _HISTORICAL_DATE.isoformat())
        self.assertEqual(
            captured["result"].metadata["dataset_key"],
            "stock_daily_bars_by_date",
        )
        self.assertEqual(
            captured["result"].metadata["partition_key"],
            _HISTORICAL_PARTITION,
        )

    def test_raw_asset_does_not_load_stock_universe(self) -> None:
        # The by-date path is universe-agnostic; the asset must NOT
        # call ``load_stock_universe`` (that's ``stock_input_snapshot``'s
        # job). A stale universe must never silently re-target or
        # filter the raw fetch.
        from uuid import uuid4 as _uuid4

        captured_calls: list[Path] = []

        def _explode_if_called(path: Path) -> StockUniverse:
            captured_calls.append(path)
            raise RuntimeError("STOP_AFTER_LOAD_UNIVERSE")

        engine = MagicMock()
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(assets, "build_stock_provider", lambda _settings: MagicMock()),
            patch.object(
                assets,
                "write_stock_daily_bars_raw_by_trade_date",
                lambda _provider, _factory, **_kwargs: SimpleNamespace(
                    request_id=_uuid4(),
                    attempt_id=_uuid4(),
                    batch_id=_uuid4(),
                    request_status="succeeded",
                    attempt_status="succeeded",
                    record_count=1,
                ),
            ),
            patch.object(assets, "load_stock_universe", _explode_if_called),
        ):
            _underlying_callable("stock_daily_bars_raw")(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )
        self.assertEqual(captured_calls, [])

    def test_upsert_asset_uses_partition_aligned_by_date_request_key(self) -> None:
        captured: dict[str, Any] = {}

        def _fake_upsert(
            session_factory: Any,
            *,
            provider_key: str = "tushare",
            dataset_key: str = "stock_daily_bars",
            request_key: str | None = None,
            unit_of_work_factory: Any = None,
        ) -> Any:
            captured["provider_key"] = provider_key
            captured["dataset_key"] = dataset_key
            captured["request_key"] = request_key
            from dataclasses import dataclass

            @dataclass
            class _Summary:
                inserted: int = 0
                skipped: int = 0

                @property
                def total(self) -> int:
                    return self.inserted + self.skipped

            return _Summary()

        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)

        stored_request = MagicMock(name="StoredRequest")
        stored_request.status = "succeeded"
        uow.provider_requests.get_by_logical_key = MagicMock(return_value=stored_request)

        engine = MagicMock()
        provider = MagicMock(name="StockTushareProvider")
        provider.provider_key = "tushare"
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(assets, "build_stock_provider", lambda _settings: provider),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _f: uow),
            patch.object(assets, "upsert_stock_daily_bars", _fake_upsert),
        ):
            result = _underlying_callable("stock_daily_bars")(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )

        expected_key = f"daily-bars-by-date-{_HISTORICAL_DATE.isoformat()}"
        self.assertEqual(captured["request_key"], expected_key)
        self.assertEqual(captured["dataset_key"], "stock_daily_bars_by_date")
        self.assertEqual(captured["provider_key"], "tushare")
        self.assertEqual(result.metadata["request_key"], expected_key)
        self.assertEqual(result.metadata["trade_date"], _HISTORICAL_DATE.isoformat())


class StockAssetsSkippedBehaviourTest(unittest.TestCase):
    """``stock_instruments`` / ``stock_daily_bars`` skip when upstream is missing or failed."""

    def _invoke(
        self,
        asset_name: str,
        stored_status: str | None,
    ) -> Any:
        uow = MagicMock(name="UoW")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)

        if stored_status is None:
            stored_request = None
        else:
            stored_request = MagicMock(name="StoredRequest")
            stored_request.status = stored_status
        uow.provider_requests.get_by_logical_key = MagicMock(return_value=stored_request)

        engine = MagicMock()
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(
                assets, "build_stock_provider", lambda _settings: MagicMock()
            ),
            patch.object(assets, "load_stock_universe", lambda _path: _FIXED_UNIVERSE),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _f: uow),
        ):
            return _underlying_callable(asset_name)(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )

    def test_stock_instruments_skips_when_request_missing(self) -> None:
        result = self._invoke("stock_instruments", stored_status=None)
        self.assertTrue(result.metadata["skipped"])
        self.assertEqual(result.metadata["row_count"], 0)

    def test_stock_instruments_skips_when_request_failed(self) -> None:
        result = self._invoke("stock_instruments", stored_status="failed")
        self.assertTrue(result.metadata["skipped"])
        self.assertEqual(result.metadata["row_count"], 0)

    def test_stock_daily_bars_skips_when_request_missing(self) -> None:
        result = self._invoke("stock_daily_bars", stored_status=None)
        self.assertTrue(result.metadata["skipped_asset"])
        self.assertEqual(result.metadata["inserted"], 0)

    def test_stock_daily_bars_skips_when_request_failed(self) -> None:
        result = self._invoke("stock_daily_bars", stored_status="failed")
        self.assertTrue(result.metadata["skipped_asset"])
        self.assertEqual(result.metadata["inserted"], 0)


class SettingsStockUniversePathTest(unittest.TestCase):
    """``Settings.stock_universe_path`` defaults to the repository config file."""

    def test_default_stock_universe_path_points_to_repository_config(self) -> None:
        repository_root = Path(__file__).resolve().parents[4]
        settings = Settings()
        self.assertEqual(
            settings.stock_universe_path,
            repository_root / "config" / "stock-universe.yaml",
        )


if __name__ == "__main__":
    unittest.main()