"""Unit tests for the PR-01 partition alignment of the ETF master-data assets.

PR-01 makes :func:`invest_pipeline.assets.etf_instruments_raw` and
:func:`invest_pipeline.assets.etf_instruments` honour the daily
partition key the rest of the daily slice already shares, so a
historical back-fill run cannot silently re-target today's data.

The tests target three contracts:

* **Shared partition definition** — both production assets declare the
  same ``_ETF_INPUT_SNAPSHOT_PARTITIONS`` instance that
  ``etf_daily_bars_raw`` / ``etf_daily_bars`` / ``etf_input_snapshot``
  / ``personal_candidate_pool`` already use; partition start, timezone
  and cadence stay byte-equal so a Dagster scheduler can place the
  whole daily slice on the same partition key.
* **Partition key, not ``date.today()``, drives the write path** —
  invoking the raw asset's underlying callable with a historical
  partition such as ``2026-07-31`` propagates that date to
  :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`
  and into the persisted ``request_key`` and ``request_params`` of the
  raw ``provider_requests`` row.
* **Partition key, not ``date.today()``, drives the upsert path** —
  invoking the upsert asset with the same historical partition
  propagates that date into the upstream request lookup
  ``request_key=instruments-{as_of}`` and the call to
  :func:`invest_pipeline.etf_instruments.upsert_etf_instruments`.

The slice is implemented in :mod:`invest_pipeline.assets` and is
independent of the legacy ``seed_instruments`` asset (which keeps
``FixtureDevInstrumentProvider()`` and a non-partitioned body) and
the CLI default ``date.today()`` fallback in
:mod:`invest_pipeline.personal_daily_cli` (which only seeds the
``--trade-date`` argparse default). Both preservation guarantees are
pinned by source-level checks in the same suite.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import dagster as dg
import invest_storage
from invest_pipeline import assets
from invest_pipeline.adapters.fixture_dev.adapter import (
    FixtureDevInstrumentProvider,
)

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


def _body_calls_name(name: str) -> ast.FunctionDef:
    """Return the top-level :class:`ast.FunctionDef` for ``name`` in ``assets.py``."""

    tree = ast.parse(_assets_source())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"top-level function {name!r} not found in assets.py")


def _body_uses_date_today(name: str) -> bool:
    """Return ``True`` if the executable body of ``name`` calls ``date.today()``.

    Substring / regex checks over the raw source would misfire on
    docstring prose such as "no ``date.today()`` fallback". Walking
    the AST and inspecting only :class:`ast.Call` nodes whose
    function resolves to ``date.today`` keeps the check precise: a
    future refactor that re-introduces ``date.today()`` as a real
    call in the historical-rerun path is what we want to surface,
    not a docstring mention.
    """

    func = _body_calls_name(name)
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if (
            isinstance(called, ast.Attribute)
            and called.attr == "today"
            and isinstance(called.value, ast.Name)
            and called.value.id == "date"
        ):
            return True
    return False


def _underlying_callable(asset_name: str):
    """Return the unwrapped Python callable the Dagster ``@asset`` decorator wraps."""

    assets_def = getattr(assets, asset_name)
    return assets_def.op.compute_fn.decorated_fn


class EtfInstrumentsPartitionsDefTest(unittest.TestCase):
    """The two production ETF master-data assets share the daily partition definition."""

    def test_etf_instruments_raw_is_partitioned_with_daily_definition(self) -> None:
        self.assertIsInstance(
            assets.etf_instruments_raw.partitions_def,
            dg.DailyPartitionsDefinition,
        )

    def test_etf_instruments_is_partitioned_with_daily_definition(self) -> None:
        self.assertIsInstance(
            assets.etf_instruments.partitions_def,
            dg.DailyPartitionsDefinition,
        )

    def test_both_assets_share_same_partitions_def_instance(self) -> None:
        # Reusing the same _ETF_INPUT_SNAPSHOT_PARTITIONS instance
        # (rather than constructing two equivalent ``DailyPartitionsDefinition``
        # objects) keeps the start date, timezone and partition-fn
        # byte-equal across the slice. Plain attribute comparison isn't
        # supported on the TimestampWithTimezone-backed definition so
        # we compare against the canonical object the rest of the
        # daily slice uses.
        raw_def = assets.etf_instruments_raw.partitions_def
        upsert_def = assets.etf_instruments.partitions_def
        self.assertIs(raw_def, upsert_def)
        self.assertIs(raw_def, assets.etf_daily_bars_raw.partitions_def)
        self.assertIs(raw_def, assets.etf_daily_bars.partitions_def)
        self.assertIs(raw_def, assets.etf_input_snapshot.partitions_def)
        self.assertIs(
            raw_def, assets.personal_candidate_pool.partitions_def
        )


class EtfInstrumentsRawPartitionDateTest(unittest.TestCase):
    """``etf_instruments_raw`` passes the historical partition key to the service.

    The asset body must read ``as_of`` from ``context.partition_key``
    only (no ``date.today()`` fallback) and hand the resulting
    :class:`datetime.date` to
    :func:`invest_pipeline.etf_instruments.write_etf_instruments_raw`.
    The service in turn stamps the persisted
    ``raw.provider_requests`` row with
    ``request_key=instruments-{as_of}`` and
    ``request_params={"as_of": as_of.isoformat()}``, so a back-fill run
    for ``2026-07-31`` writes that exact logical key instead of
    silently re-targeting today's data.
    """

    def _patch_engine(self) -> MagicMock:
        engine = MagicMock(name="Engine")
        self._engine = engine
        return engine

    def _invoke_raw(self, captured: dict[str, Any]) -> Any:
        engine = self._patch_engine()
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(
                assets, "build_provider", lambda _settings: MagicMock()
            ),
        ):
            return _underlying_callable("etf_instruments_raw")(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )

    def test_raw_asset_body_reads_partition_key_and_calls_write_with_that_date(
        self,
    ) -> None:
        body = _asset_body("etf_instruments_raw")
        # The partition key must be the sole source of truth for the
        # business date in this asset; ``date.today()`` must not leak
        # into the executable body of the historical-rerun path
        # (docstring mentions are filtered out below).
        self.assertIn("date.fromisoformat(context.partition_key)", body)
        self.assertFalse(
            _body_uses_date_today("etf_instruments_raw"),
            "etf_instruments_raw must derive ``as_of`` from the "
            "partition key only, with no ``date.today()`` fallback",
        )

    def test_raw_asset_invokes_write_with_historical_partition_date(self) -> None:
        captured: dict[str, Any] = {}

        def _fake_write(
            provider: Any,
            session_factory: Any,
            *,
            as_of: date,
            unit_of_work_factory: Any = None,
        ) -> Any:
            captured["provider"] = provider
            captured["session_factory"] = session_factory
            captured["as_of"] = as_of
            # The fake UoW must return a real RawEtlResult-shaped
            # object so the asset body can build the
            # MaterializeResult without AttributeError.
            return _build_raw_etl_result()

        with patch.object(assets, "write_etf_instruments_raw", _fake_write):
            result = self._invoke_raw(captured)

        self.assertEqual(captured["as_of"], _HISTORICAL_DATE)
        self.assertEqual(result.metadata["as_of"], _HISTORICAL_PARTITION)
        self.assertEqual(result.metadata["partition_key"], _HISTORICAL_PARTITION)
        self._engine.dispose.assert_called_once_with()

    def test_raw_asset_does_not_fall_back_to_today_for_historical_partition(
        self,
    ) -> None:
        """Pin: the raw asset must not call ``date.today()`` in the new body.

        The PR-01 contract replaces the legacy
        ``as_of=date.today()`` call with the partition-derived
        ``as_of``. A future refactor that re-introduces ``date.today()``
        in the raw asset body would silently break historical back-fills
        (the raw write would always target today). Guarding the body
        keeps that regression loud.
        """

        self.assertFalse(
            _body_uses_date_today("etf_instruments_raw"),
            "etf_instruments_raw body must not call date.today(); "
            "back-fill runs would silently re-target today's data",
        )


class EtfInstrumentsPartitionDateTest(unittest.TestCase):
    """``etf_instruments`` reads the historical partition key for the upsert.

    The asset must derive ``as_of`` from ``context.partition_key`` and
    use that date in *both* the upstream
    ``provider_requests.get_by_logical_key`` lookup
    (``request_key=instruments-{as_of}``) and the call to
    :func:`invest_pipeline.etf_instruments.upsert_etf_instruments`.
    A back-fill run for ``2026-07-31`` therefore upserts the
    attempt the partitioned raw write persisted for that exact date
    instead of silently re-targeting today's data.
    """

    def _patch_engine(self) -> MagicMock:
        engine = MagicMock(name="Engine")
        self._engine = engine
        return engine

    def _set_up_lookup(
        self, status: str = "succeeded"
    ) -> tuple[dict[str, Any], MagicMock]:
        captured: dict[str, Any] = {}
        stored_request = MagicMock(name="StoredProviderRequest")
        stored_request.status = status

        uow = MagicMock(name="UnitOfWork")
        uow.__enter__ = MagicMock(return_value=uow)
        uow.__exit__ = MagicMock(return_value=False)

        def _get_by_logical_key(
            *, provider_key: str, dataset_key: str, request_key: str
        ) -> Any:
            captured["lookup_provider_key"] = provider_key
            captured["lookup_dataset_key"] = dataset_key
            captured["lookup_request_key"] = request_key
            return stored_request

        uow.provider_requests.get_by_logical_key = MagicMock(
            side_effect=_get_by_logical_key
        )
        return captured, uow

    def _invoke_upsert(self, captured: dict[str, Any], uow: Any) -> Any:
        engine = self._patch_engine()
        provider = MagicMock()
        provider.provider_key = "fixture_dev"
        with (
            patch.object(assets, "build_engine", lambda _url: engine),
            patch.object(assets, "session_factory", lambda _engine: MagicMock()),
            patch.object(assets, "build_provider", lambda _settings: provider),
            patch.object(invest_storage, "SqlAlchemyUnitOfWork", lambda _f: uow),
        ):
            return _underlying_callable("etf_instruments")(
                dg.build_asset_context(partition_key=_HISTORICAL_PARTITION)
            )

    def test_upsert_asset_body_reads_partition_key_and_calls_service_with_that_date(
        self,
    ) -> None:
        body = _asset_body("etf_instruments")
        self.assertIn("date.fromisoformat(context.partition_key)", body)
        self.assertFalse(
            _body_uses_date_today("etf_instruments"),
            "etf_instruments must derive ``as_of`` from the partition "
            "key only, with no ``date.today()`` fallback",
        )

    def test_upsert_asset_uses_partition_date_for_request_lookup(self) -> None:
        captured, uow = self._set_up_lookup()

        with patch.object(assets, "upsert_etf_instruments", return_value=3):
            result = self._invoke_upsert(captured, uow)

        # The upstream lookup must use the partition-derived ``as_of``,
        # not today's date, so a back-fill run for 2026-07-31 resolves
        # the attempt the raw asset persisted for that date.
        self.assertEqual(
            captured["lookup_request_key"],
            f"instruments-{_HISTORICAL_DATE.isoformat()}",
        )
        self.assertEqual(captured["lookup_dataset_key"], "etf_instruments")
        self.assertEqual(result.metadata["as_of"], _HISTORICAL_PARTITION)
        self.assertEqual(result.metadata["partition_key"], _HISTORICAL_PARTITION)
        self._engine.dispose.assert_called_once_with()

    def test_upsert_asset_invokes_service_with_historical_partition_date(
        self,
    ) -> None:
        captured, uow = self._set_up_lookup()

        def _fake_upsert(
            session_factory: Any,
            *,
            as_of: date,
            provider_key: str = "fixture_dev",
            dataset_key: str = "etf_instruments",
            unit_of_work_factory: Any = None,
        ) -> int:
            captured["upsert_as_of"] = as_of
            captured["upsert_provider_key"] = provider_key
            captured["upsert_dataset_key"] = dataset_key
            return 5

        with patch.object(assets, "upsert_etf_instruments", _fake_upsert):
            result = self._invoke_upsert(captured, uow)

        self.assertEqual(captured["upsert_as_of"], _HISTORICAL_DATE)
        self.assertEqual(captured["upsert_dataset_key"], "etf_instruments")
        self.assertEqual(result.metadata["row_count"], 5)
        self._engine.dispose.assert_called_once_with()

    def test_upsert_asset_does_not_fall_back_to_today_for_historical_partition(
        self,
    ) -> None:
        self.assertFalse(
            _body_uses_date_today("etf_instruments"),
            "etf_instruments body must not call date.today(); "
            "back-fill runs would silently re-target today's data",
        )


class EtfInstrumentsPartitionConsistencyTest(unittest.TestCase):
    """The two assets share the same partition key and ``as_of`` for the same run.

    A daily Dagster run materialises a single partition key across
    every asset in the slice. If the raw and the upsert assets drift
    (one uses ``date.today()`` and the other uses
    ``context.partition_key``) the upstream lookup misses and the
    upsert surfaces a ``LookupError``. The contract the slice must
    guarantee: both assets derive the *same* ``as_of`` from the
    *same* ``context.partition_key`` for any partition the daily
    schedule fires.
    """

    def test_both_assets_derive_as_of_from_context_partition_key(self) -> None:
        raw_body = _asset_body("etf_instruments_raw")
        upsert_body = _asset_body("etf_instruments")
        # Both asset bodies must convert ``context.partition_key`` to a
        # ``date`` via ``date.fromisoformat`` and call the matching
        # service with ``as_of=as_of`` (the local variable).
        for body, label in (
            (raw_body, "etf_instruments_raw"),
            (upsert_body, "etf_instruments"),
        ):
            with self.subTest(asset=label):
                self.assertIn("date.fromisoformat(context.partition_key)", body)
                self.assertRegex(body, r"as_of\s*=\s*as_of")

    def test_both_assets_have_identical_dependency_and_partitions_metadata(
        self,
    ) -> None:
        # The raw asset is partitioned independently of the upsert
        # asset's ``deps=[etf_instruments_raw]`` declaration: the
        # upsert asset must keep ``etf_instruments_raw`` as a dep so
        # Dagster refuses to schedule the upsert before the raw run
        # for the same partition.
        self.assertIs(
            assets.etf_instruments_raw.partitions_def,
            assets.etf_instruments.partitions_def,
        )
        self.assertIn(
            dg.AssetKey("etf_instruments_raw"),
            assets.etf_instruments.dependency_keys,
        )


class EtfInstrumentsPreservationTest(unittest.TestCase):
    """``seed_instruments`` stays untouched while CLI dates use market time.

    PR-01 explicitly preserves the legacy ``seed_instruments`` asset
    (it must keep its direct ``FixtureDevInstrumentProvider()`` call
    and stay non-partitioned). PR-03 separately standardises the CLI
    default on the Asia/Shanghai market clock. Both guarantees are
    pinned at the source / import level.
    """

    def test_seed_instruments_keeps_legacy_fixture_construction(self) -> None:
        body = _asset_body("seed_instruments")
        self.assertIn("FixtureDevInstrumentProvider()", body)
        self.assertIn("date.today()", body)
        # The legacy asset is not part of the daily partition slice.
        self.assertIsNone(
            getattr(assets.seed_instruments, "partitions_def", None)
        )

    def test_personal_daily_cli_default_trade_date_uses_market_today(self) -> None:
        from invest_pipeline import personal_daily_cli

        source = Path(inspect.getsourcefile(personal_daily_cli) or "").resolve()
        text = source.read_text(encoding="utf-8")
        self.assertIn("parse_trade_date(args.trade_date, market_today())", text)


def _build_raw_etl_result() -> Any:
    """Return a ``RawEtlResult``-shaped object the asset body can read from.

    The raw asset reads the storage-assigned UUIDs and the
    ``request_status`` / ``record_count`` off the result. Building a
    minimal namespace avoids re-instantiating the real dataclass while
    still satisfying the asset's metadata contract.
    """

    from uuid import uuid4

    return MagicMock(
        name="RawEtlResult",
        request_id=uuid4(),
        attempt_id=uuid4(),
        batch_id=uuid4(),
        request_status="succeeded",
        attempt_status="succeeded",
        record_count=len(FixtureDevInstrumentProvider().list_instruments()),
    )


if __name__ == "__main__":
    unittest.main()
