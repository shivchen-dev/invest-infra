"""Unit tests for the PR-1B ETF asset provider wiring.

PR-1A shipped :func:`invest_pipeline.provider_factory.build_provider` and
:class:`invest_pipeline.config.Settings.provider_key`. PR-1B wires the
production ETF Dagster assets
(``etf_instruments_raw``, ``etf_instruments``,
``etf_daily_bars_raw``, ``etf_daily_bars``) onto the factory and
removes the concrete ``FixtureDevInstrumentProvider`` instantiation
from the service-module defaults so the service modules do not reach
for a provider at import time.

The tests target the *wiring* contract — they do not exercise the full
asset body (that coverage lives in the existing fixture-style suites
under :mod:`invest_pipeline.tests.unit`). Specifically:

* :class:`EtfAssetsSourceWiringTest` reads each production asset's
  source via :mod:`ast` (Dagster's ``@asset`` decorator wraps the
  function into an ``AssetsDefinition`` that ``inspect.getsource``
  cannot read directly) and asserts it routes through
  ``build_provider(get_settings())`` rather than constructing
  ``FixtureDevInstrumentProvider`` directly.
* :class:`EtfAssetsRuntimeWiringTest` invokes each production asset's
  underlying callable (via
  ``AssetsDefinition.op.compute_fn.decorated_fn``) with a mocked
  context and patches :func:`invest_pipeline.assets.build_provider` to
  a sentinel that raises immediately, so the suite verifies the
  factory call happens at runtime without booting a real database.
* :class:`SeedInstrumentsLegacyTest` pins the explicit preservation
  guarantee for ``seed_instruments`` — the legacy fixture-only asset
  must keep its direct ``FixtureDevInstrumentProvider()`` construction
  per the PR-1B "do not broaden this slice" guardrail.
* :class:`ServiceModuleDefaultsTest` asserts the service-module
  defaults are plain strings (no concrete-provider instantiation) and
  that importing either service module does not materialise a
  ``FixtureDevInstrumentProvider`` instance.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from invest_pipeline.adapters.fixture_dev.adapter import (
    FixtureDevInstrumentProvider,
)
from invest_pipeline.config import Settings


def _assets_source() -> str:
    """Return the source text of :mod:`invest_pipeline.assets`."""

    from invest_pipeline import assets

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

    from invest_pipeline import assets

    assets_def = getattr(assets, asset_name)
    return assets_def.op.compute_fn.decorated_fn


class EtfAssetsSourceWiringTest(unittest.TestCase):
    """Source-level guarantee that the production ETF assets route through the factory."""

    def test_etf_instruments_raw_asset_calls_build_provider_with_settings(self) -> None:
        self.assertIn(
            "build_provider(get_settings())",
            _asset_body("etf_instruments_raw"),
        )

    def test_etf_instruments_asset_calls_build_provider_with_settings(self) -> None:
        body = _asset_body("etf_instruments")
        self.assertIn("build_provider(get_settings())", body)
        # The downstream lookup must not hard-code the provider key.
        self.assertNotIn('provider_key="fixture_dev"', body)
        self.assertNotIn("provider_key='fixture_dev'", body)

    def test_etf_daily_bars_raw_asset_calls_build_provider_with_settings(self) -> None:
        self.assertIn(
            "build_provider(get_settings())",
            _asset_body("etf_daily_bars_raw"),
        )

    def test_etf_daily_bars_asset_calls_build_provider_with_settings(self) -> None:
        self.assertIn(
            "build_provider(get_settings())",
            _asset_body("etf_daily_bars"),
        )

    def test_production_etf_assets_do_not_directly_instantiate_fixture(
        self,
    ) -> None:
        # Only ``seed_instruments`` (legacy) may call
        # ``FixtureDevInstrumentProvider()`` directly; the production
        # ETF slice must always route through the factory.
        production_assets = (
            "etf_instruments_raw",
            "etf_instruments",
            "etf_daily_bars_raw",
            "etf_daily_bars",
        )
        for name in production_assets:
            with self.subTest(asset=name):
                self.assertNotIn(
                    "FixtureDevInstrumentProvider()",
                    _asset_body(name),
                    f"{name} must not directly construct "
                    "FixtureDevInstrumentProvider; use "
                    "build_provider(get_settings())",
                )


class EtfAssetsRuntimeWiringTest(unittest.TestCase):
    """Runtime guarantee that the production ETF assets actually invoke the factory."""

    def _invoke_and_capture(
        self,
        asset_name: str,
    ) -> list[Settings]:
        captured: list[Settings] = []

        def _raise_after_capture(settings: Settings) -> None:
            captured.append(settings)
            raise RuntimeError("STOP_AFTER_BUILD_PROVIDER")

        context = MagicMock()
        fn = _underlying_callable(asset_name)
        with (
            patch(
                "invest_pipeline.assets.build_provider",
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
            f"{asset_name} must call build_provider exactly once",
        )
        self.assertIsInstance(
            captured[0],
            Settings,
            f"{asset_name} must pass a Settings instance to build_provider",
        )

    def test_etf_instruments_raw_invokes_build_provider(self) -> None:
        self._assert_factory_called_with_settings("etf_instruments_raw")

    def test_etf_instruments_invokes_build_provider(self) -> None:
        self._assert_factory_called_with_settings("etf_instruments")

    def test_etf_daily_bars_raw_invokes_build_provider(self) -> None:
        self._assert_factory_called_with_settings("etf_daily_bars_raw")

    def test_etf_daily_bars_invokes_build_provider(self) -> None:
        self._assert_factory_called_with_settings("etf_daily_bars")


class SeedInstrumentsLegacyTest(unittest.TestCase):
    """``seed_instruments`` keeps its legacy fixture-only construction."""

    def test_seed_instruments_keeps_direct_fixture_construction(self) -> None:
        # The PR-1B guardrail preserves ``seed_instruments`` as
        # legacy fixture-only behaviour. The asset must still
        # instantiate ``FixtureDevInstrumentProvider`` directly —
        # swapping it to ``build_provider`` would broaden the slice.
        self.assertIn(
            "FixtureDevInstrumentProvider()",
            _asset_body("seed_instruments"),
        )

    def test_seed_instruments_does_not_route_through_factory(self) -> None:
        self.assertNotIn(
            "build_provider(get_settings())",
            _asset_body("seed_instruments"),
        )


class ServiceModuleDefaultsTest(unittest.TestCase):
    """Service defaults are plain strings and import does not instantiate a provider."""

    def test_upsert_etf_instruments_default_provider_key_is_string(self) -> None:
        from invest_pipeline.etf_instruments import upsert_etf_instruments

        default = inspect.signature(upsert_etf_instruments).parameters[
            "provider_key"
        ].default
        self.assertEqual(default, "fixture_dev")
        self.assertIsInstance(default, str)

    def test_upsert_etf_daily_bars_default_provider_key_is_string(self) -> None:
        from invest_pipeline.etf_daily_bars import upsert_etf_daily_bars

        default = inspect.signature(upsert_etf_daily_bars).parameters[
            "provider_key"
        ].default
        self.assertEqual(default, "fixture_dev")
        self.assertIsInstance(default, str)

    def test_etf_instruments_module_import_does_not_instantiate_fixture(
        self,
    ) -> None:
        # Guard against the previous default ``FixtureDevInstrumentProvider()
        # .provider_key`` sneaking back in. ``__init__`` must never be
        # called at module-import time.
        with patch.object(
            FixtureDevInstrumentProvider,
            "__init__",
            side_effect=AssertionError(
                "FixtureDevInstrumentProvider must not be instantiated "
                "at module import time; use a string default instead"
            ),
        ):
            module = importlib.import_module("invest_pipeline.etf_instruments")
            importlib.reload(module)

    def test_etf_daily_bars_module_import_does_not_instantiate_fixture(
        self,
    ) -> None:
        with patch.object(
            FixtureDevInstrumentProvider,
            "__init__",
            side_effect=AssertionError(
                "FixtureDevInstrumentProvider must not be instantiated "
                "at module import time; use a string default instead"
            ),
        ):
            module = importlib.import_module("invest_pipeline.etf_daily_bars")
            importlib.reload(module)


if __name__ == "__main__":
    unittest.main()