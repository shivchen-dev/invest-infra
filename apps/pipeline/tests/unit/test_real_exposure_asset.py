"""Focused unit tests for the DC-3 real-exposure Dagster asset.

These tests pin the slice's *orchestration* contract:

* The default ``enabled=False`` config causes the asset to fail closed
  BEFORE the :class:`AkshareClient` is constructed and BEFORE any
  network call. A Dagster run that omits the opt-in flag must never
  touch the SDK or the database.
* When ``enabled=True`` every explicit operator input (``etf_symbol``,
  ``etf_exchange``, ``index_code``, ``mapping_effective_from``,
  ``observed_at`` and the optional ``holding_year`` /
  ``mapping_effective_to`` / ``revision`` / ``confidence`` fields) is
  forwarded verbatim to
  :func:`invest_pipeline.real_exposure_service.collect_and_persist_real_exposure`.
* The returned :class:`dagster.MaterializeResult` exposes every
  identifier, content hash and raw payload hash from the service
  result as Dagster metadata so the UI surfaces the persisted state.
* The SQLAlchemy engine is disposed even when the service raises.
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID

import dagster as dg
from invest_pipeline.real_exposure_asset import (
    RealExposureAssetConfig,
    RealExposureAssetDisabledError,
    real_exposure,
)
from invest_pipeline.real_exposure_service import (
    RealExposurePersistResult,
)

_ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_INDEX_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_PROFILE_ID = UUID("11111111-1111-4111-8111-111111111111")
_CONSTITUENT_ID = UUID("22222222-2222-4222-8222-222222222222")
_MAPPING_ID = UUID("33333333-3333-4333-8333-333333333333")
_HOLDING_ID = UUID("44444444-4444-4444-8444-444444444444")
_RAW_INDEX_HASH = "a" * 64
_RAW_HOLDINGS_HASH = "b" * 64
_EFFECTIVE_FROM_STR = "2026-01-01"
_EFFECTIVE_TO_STR = "2026-12-31"
_OBSERVED_AT_STR = "2026-08-01T00:00:00+00:00"
_EFFECTIVE_FROM_DATE = date(2026, 1, 1)
_EFFECTIVE_TO_DATE = date(2026, 12, 31)
_OBSERVED_AT_TZ = datetime.fromisoformat(_OBSERVED_AT_STR).tzinfo
_OBSERVED_AT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=_OBSERVED_AT_TZ)


def _result() -> RealExposurePersistResult:
    return RealExposurePersistResult(
        etf_id=_ETF_ID,
        index_id=_INDEX_ID,
        profile_id=_PROFILE_ID,
        profile_content_hash="profile_hash",
        constituent_snapshot_id=_CONSTITUENT_ID,
        constituent_content_hash="constituent_hash",
        mapping_id=_MAPPING_ID,
        mapping_content_hash="mapping_hash",
        holding_snapshot_id=_HOLDING_ID,
        holding_content_hash="holding_hash",
        constituents_raw_payload_hash=_RAW_INDEX_HASH,
        holdings_raw_payload_hash=_RAW_HOLDINGS_HASH,
    )


def _enabled_config(
    *,
    etf_symbol: str = "510300",
    etf_exchange: str = "SSE",
    index_code: str = "000300",
    mapping_effective_from: str = _EFFECTIVE_FROM_STR,
    observed_at: str = _OBSERVED_AT_STR,
    holding_year: str = "2024",
    mapping_effective_to: str | None = _EFFECTIVE_TO_STR,
    revision: int = 2,
    confidence: float = 0.75,
) -> RealExposureAssetConfig:
    return RealExposureAssetConfig(
        enabled=True,
        etf_symbol=etf_symbol,
        etf_exchange=etf_exchange,
        index_code=index_code,
        mapping_effective_from=mapping_effective_from,
        observed_at=observed_at,
        holding_year=holding_year,
        mapping_effective_to=mapping_effective_to,
        revision=revision,
        confidence=confidence,
    )


class DisabledByDefaultTest(unittest.TestCase):
    """The asset must fail closed when ``enabled`` is False (the default)."""

    def test_default_enabled_is_false(self) -> None:
        config = RealExposureAssetConfig(
            etf_symbol="510300",
            etf_exchange="SSE",
            index_code="000300",
            mapping_effective_from=_EFFECTIVE_FROM_STR,
            observed_at=_OBSERVED_AT_STR,
        )
        self.assertFalse(config.enabled)

    def test_disabled_raises_before_client_or_engine(self) -> None:
        context = dg.build_asset_context()
        config = RealExposureAssetConfig(
            enabled=False,
            etf_symbol="510300",
            etf_exchange="SSE",
            index_code="000300",
            mapping_effective_from=_EFFECTIVE_FROM_STR,
            observed_at=_OBSERVED_AT_STR,
        )
        with (
            patch(
                "invest_pipeline.real_exposure_asset._build_akshare_client"
            ) as build_client,
            patch(
                "invest_pipeline.real_exposure_asset.build_engine"
            ) as build_engine,
            patch(
                "invest_pipeline.real_exposure_asset.session_factory"
            ) as factory,
            patch(
                "invest_pipeline.real_exposure_asset.collect_and_persist_real_exposure"
            ) as service,
            self.assertRaises(RealExposureAssetDisabledError),
        ):
            real_exposure(context, config)
        build_client.assert_not_called()
        build_engine.assert_not_called()
        factory.assert_not_called()
        service.assert_not_called()

    def test_disabled_raises_via_asset_def(self) -> None:
        """The opt-out is enforced at the Dagster asset layer, not only in helpers."""

        context = dg.build_asset_context()
        config = RealExposureAssetConfig(
            etf_symbol="510300",
            etf_exchange="SSE",
            index_code="000300",
            mapping_effective_from=_EFFECTIVE_FROM_STR,
            observed_at=_OBSERVED_AT_STR,
        )
        with ExitStack() as stack:
            for target in (
                "invest_pipeline.real_exposure_asset._build_akshare_client",
                "invest_pipeline.real_exposure_asset.build_engine",
                "invest_pipeline.real_exposure_asset.collect_and_persist_real_exposure",
            ):
                stack.enter_context(patch(target))
            with self.assertRaises(RealExposureAssetDisabledError):
                real_exposure(context, config)


class EnabledAssetTest(unittest.TestCase):
    """The enabled asset forwards config and surfaces metadata."""

    def _run_with_capture(
        self, config: RealExposureAssetConfig
    ) -> tuple[dg.MaterializeResult, dict[str, object]]:
        context = dg.build_asset_context()
        fake_engine = MagicMock(name="engine")
        fake_session_factory = MagicMock(name="session_factory")
        captured: dict[str, object] = {}

        def _service(**kwargs: object) -> RealExposurePersistResult:
            captured.update(kwargs)
            return _result()

        with (
            patch(
                "invest_pipeline.real_exposure_asset._build_akshare_client"
            ) as build_client,
            patch(
                "invest_pipeline.real_exposure_asset.build_engine",
                return_value=fake_engine,
            ) as engine_builder,
            patch(
                "invest_pipeline.real_exposure_asset.session_factory",
                return_value=fake_session_factory,
            ) as session_builder,
            patch(
                "invest_pipeline.real_exposure_asset.collect_and_persist_real_exposure",
                side_effect=_service,
            ) as service,
        ):
            returned = real_exposure(context, config)

        build_client.assert_called_once_with()
        engine_builder.assert_called_once()
        session_builder.assert_called_once_with(fake_engine)
        self.assertEqual(fake_engine.dispose.call_count, 1)
        service.assert_called_once()
        return returned, captured

    def test_forwards_explicit_operator_inputs(self) -> None:
        config = _enabled_config()
        _, captured = self._run_with_capture(config)

        self.assertEqual(captured["etf_symbol"], "510300")
        self.assertEqual(captured["etf_exchange"], "SSE")
        self.assertEqual(captured["index_code"], "000300")
        self.assertEqual(captured["mapping_effective_from"], _EFFECTIVE_FROM_DATE)
        self.assertEqual(captured["observed_at"], _OBSERVED_AT_DT)
        self.assertEqual(captured["holding_year"], "2024")
        self.assertEqual(captured["mapping_effective_to"], _EFFECTIVE_TO_DATE)
        self.assertEqual(captured["revision"], 2)
        self.assertEqual(captured["confidence"], Decimal("0.75"))
        self.assertIsNotNone(captured["client"])
        self.assertIsNotNone(captured["uow_factory"])

    def test_default_optional_fields_when_only_required_provided(self) -> None:
        config = RealExposureAssetConfig(
            enabled=True,
            etf_symbol="510300",
            etf_exchange="SSE",
            index_code="000300",
            mapping_effective_from=_EFFECTIVE_FROM_STR,
            observed_at=_OBSERVED_AT_STR,
        )
        self.assertEqual(config.holding_year, "")
        self.assertIsNone(config.mapping_effective_to)
        self.assertEqual(config.revision, 1)
        self.assertEqual(config.confidence, 1.0)

        _, captured = self._run_with_capture(config)

        self.assertEqual(captured["holding_year"], "")
        self.assertIsNone(captured["mapping_effective_to"])
        self.assertEqual(captured["revision"], 1)
        self.assertEqual(captured["confidence"], Decimal("1"))

    def test_metadata_returns_all_identifiers_and_hashes(self) -> None:
        config = _enabled_config()
        result, _ = self._run_with_capture(config)
        metadata = result.metadata
        self.assertEqual(metadata["etf_id"], str(_ETF_ID))
        self.assertEqual(metadata["index_id"], str(_INDEX_ID))
        self.assertEqual(metadata["profile_id"], str(_PROFILE_ID))
        self.assertEqual(metadata["profile_content_hash"], "profile_hash")
        self.assertEqual(metadata["constituent_snapshot_id"], str(_CONSTITUENT_ID))
        self.assertEqual(metadata["constituent_content_hash"], "constituent_hash")
        self.assertEqual(metadata["mapping_id"], str(_MAPPING_ID))
        self.assertEqual(metadata["mapping_content_hash"], "mapping_hash")
        self.assertEqual(metadata["holding_snapshot_id"], str(_HOLDING_ID))
        self.assertEqual(metadata["holding_content_hash"], "holding_hash")
        self.assertEqual(metadata["constituents_raw_payload_hash"], _RAW_INDEX_HASH)
        self.assertEqual(metadata["holdings_raw_payload_hash"], _RAW_HOLDINGS_HASH)
        self.assertEqual(metadata["etf_symbol"], "510300")
        self.assertEqual(metadata["etf_exchange"], "SSE")
        self.assertEqual(metadata["index_code"], "000300")
        self.assertEqual(metadata["mapping_effective_from"], _EFFECTIVE_FROM_STR)
        self.assertEqual(metadata["mapping_effective_to"], _EFFECTIVE_TO_STR)
        self.assertEqual(metadata["observed_at"], _OBSERVED_AT_STR)
        self.assertEqual(metadata["holding_year"], "2024")
        self.assertEqual(metadata["revision"], 2)
        self.assertEqual(metadata["confidence"], "0.75")
        self.assertTrue(metadata["enabled"])

    def test_engine_disposed_even_on_service_exception(self) -> None:
        config = _enabled_config()
        fake_engine = MagicMock(name="engine")
        fake_session_factory = MagicMock(name="session_factory")
        with (
            patch(
                "invest_pipeline.real_exposure_asset._build_akshare_client"
            ),
            patch(
                "invest_pipeline.real_exposure_asset.build_engine",
                return_value=fake_engine,
            ),
            patch(
                "invest_pipeline.real_exposure_asset.session_factory",
                return_value=fake_session_factory,
            ),
            patch(
                "invest_pipeline.real_exposure_asset.collect_and_persist_real_exposure",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            real_exposure(dg.build_asset_context(), config)
        fake_engine.dispose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
