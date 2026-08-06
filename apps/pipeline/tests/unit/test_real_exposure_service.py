"""Atomic-sliced unit tests for :mod:`invest_pipeline.real_exposure_service`.

These tests drive :func:`collect_and_persist_real_exposure` through the
public surface using fake client/UoW/repository doubles — no network,
no database. The slice's contract:

* Validate explicit inputs (typed errors) before any I/O.
* Two-phase UoW usage: a **short lookup UoW** (never committed, no
  network while it is open) to resolve the ETF instrument, then a
  **persistence UoW** that commits exactly once.
* CSIndex constituents and AkShare reported ETF holdings are fetched
  via the injected client ``Protocol`` between the two UoWs.
* Persistence rechecks the business key inside the persistence UoW
  and rejects on disappearance or identity change.
* The ``EtfIndexMapping`` is built with explicit effective dates,
  stable ``index_id`` from :meth:`uow.index_identities.add`, and
  ``operator_controlled`` / ``etf_index_mapping`` provenance. The
  effective date is NEVER derived from ``observed_at`` or upstream
  payload text.
* Both raw ``AkshareResponse.raw_payload_hash`` values are returned
  so the next slice can persist audit rows without conflating
  transactions.
"""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from invest_domain.exposure import (
    EtfIndexMapping,
    ExposureProvenance,
)
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_pipeline.adapters.akshare import exposure_mapper as _exposure_mapper_module
from invest_pipeline.adapters.akshare import holding_mapper as _holding_mapper_module
from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.real_exposure_service import (
    HoldingEtfIdMismatchError,
    IndexCodeMismatchError,
    InstrumentIdMissingError,
    InstrumentNotFoundError,
    InstrumentResolutionMismatchError,
    InvalidExchangeError,
    InvalidHoldingYearError,
    InvalidIndexCodeError,
    InvalidMappingDateError,
    InvalidSymbolError,
    NaiveObservedAtError,
    NonEtfInstrumentError,
    RealExposurePersistResult,
    RealExposureServiceError,
    collect_and_persist_real_exposure,
)

_MISSING: Any = object()


def _is_missing(value: Any) -> bool:
    return isinstance(value, _MISSING.__class__) and value is _MISSING

_ETF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ETF_ID_CHANGED = UUID("f0000000-0000-4000-8000-000000000001")
_INDEX_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
_PROFILE_ID = UUID("11111111-1111-4111-8111-111111111111")
_CONSTITUENT_ID = UUID("22222222-2222-4222-8222-222222222222")
_MAPPING_ID = UUID("33333333-3333-4333-8333-333333333333")
_HOLDING_ID = UUID("44444444-4444-4444-8444-444444444444")
_INDEX_CODE = "000300"
_ETF_SYMBOL = "510300"
_ETF_EXCHANGE = "SSE"
_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_EFFECTIVE_FROM = date(2026, 1, 1)
_EFFECTIVE_TO = date(2026, 12, 31)
_RAW_INDEX_HASH = "a" * 64
_RAW_HOLDINGS_HASH = "b" * 64


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------


@dataclass
class _FakeStored:
    id: UUID
    content_hash: str


class _FakeUoW:
    """In-memory UoW stand-in supporting both short and persistence roles."""

    instruments: Any
    index_identities: Any
    index_profiles: Any
    index_constituent_snapshots: Any
    etf_index_mappings: Any
    etf_holding_snapshots: Any
    commit_count: int = 0
    rollback_count: int = 0
    # Network records whether any client fetch happened while this UoW
    # was open. The slice asserts no network while an UoW is open.
    network_calls_during_session: int = 0

    def __init__(self) -> None:
        self.instruments = SimpleNamespace(
            get_by_business_key=MagicMock(),
            get_by_id=MagicMock(return_value=None),
        )
        self.index_identities = SimpleNamespace(add=MagicMock())
        self.index_profiles = SimpleNamespace(add=MagicMock())
        self.index_constituent_snapshots = SimpleNamespace(add=MagicMock())
        self.etf_index_mappings = SimpleNamespace(add=MagicMock())
        self.etf_holding_snapshots = SimpleNamespace(add=MagicMock())

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


@dataclass
class _FakeClient:
    """Client double respecting the Protocol shape."""

    index_response: AkshareResponse
    holdings_response: AkshareResponse
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def fetch_index_stock_cons_weight_csindex(
        self, *, index_code: str
    ) -> AkshareResponse:
        self.calls.append(("fetch_index_stock_cons_weight_csindex", {"index_code": index_code}))
        return self.index_response

    def fetch_fund_portfolio_hold_em(self, *, etf_code: str, year: str) -> AkshareResponse:
        self.calls.append(("fetch_fund_portfolio_hold_em", {"etf_code": etf_code, "year": year}))
        return self.holdings_response


# ----------------------------------------------------------------------
# Default fixtures / builders
# ----------------------------------------------------------------------


def _instrument(
    *,
    symbol: str = _ETF_SYMBOL,
    exchange: str = _ETF_EXCHANGE,
    instrument_id: Any = _MISSING,
    instrument_type: InstrumentType = InstrumentType.ETF,
    is_active: bool = True,
) -> Instrument:
    if _is_missing(instrument_id):
        resolved_id: InstrumentId | None = InstrumentId(_ETF_ID)
    else:
        resolved_id = instrument_id
    return Instrument(
        symbol=symbol,
        name="华泰柏瑞沪深300ETF",
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        instrument_id=resolved_id,
    )


def _index_payload() -> list[dict[str, Any]]:
    return [
        {
            "日期": date(2026, 7, 31).isoformat(),
            "指数代码": _INDEX_CODE,
            "指数名称": "沪深300",
            "成分券代码": "600519",
            "权重": "12.5",
        },
        {
            "日期": date(2026, 7, 31).isoformat(),
            "指数代码": _INDEX_CODE,
            "指数名称": "沪深300",
            "成分券代码": "601318",
            "权重": "5.0",
        },
    ]


def _holdings_payload() -> list[dict[str, Any]]:
    return [
        {
            "股票代码": "600519",
            "占净值比例": "12.5",
            "季度": "2026年2季度",
        },
        {
            "股票代码": "601318",
            "占净值比例": "5.0",
            "季度": "2026年2季度",
        },
    ]


def _make_response(
    payload: Any, *, operation: str, raw_hash: str
) -> AkshareResponse:
    return AkshareResponse(
        operation=operation,
        raw_payload=payload,
        raw_payload_hash=raw_hash,
    )


def _wire_uow(
    uow: _FakeUoW,
    *,
    lookup: Any = _MISSING,
    index_identity_id: UUID = _INDEX_ID,
    profile_result: _FakeStored | None = None,
    constituent_result: _FakeStored | None = None,
    mapping_result: _FakeStored | None = None,
    holding_result: _FakeStored | None = None,
) -> None:
    """Configure a UoW so every repository stub returns success values.

    Pass ``lookup=None`` to make ``get_by_business_key`` return ``None``
    (i.e. no instrument). The default is a valid active ETF.
    """
    if _is_missing(lookup):
        instrument: Instrument | None = _instrument()
    else:
        instrument = lookup
    uow.instruments.get_by_business_key.return_value = instrument
    uow.index_identities.add.return_value = SimpleNamespace(id=index_identity_id)
    uow.index_profiles.add.return_value = SimpleNamespace(
        id=(profile_result or _FakeStored(_PROFILE_ID, "p_hash")).id,
        content_hash=(profile_result or _FakeStored(_PROFILE_ID, "p_hash")).content_hash,
    )
    uow.index_constituent_snapshots.add.return_value = SimpleNamespace(
        id=(constituent_result or _FakeStored(_CONSTITUENT_ID, "c_hash")).id,
        content_hash=(constituent_result or _FakeStored(_CONSTITUENT_ID, "c_hash")).content_hash,
    )
    uow.etf_index_mappings.add.return_value = SimpleNamespace(
        id=(mapping_result or _FakeStored(_MAPPING_ID, "m_hash")).id,
        content_hash=(mapping_result or _FakeStored(_MAPPING_ID, "m_hash")).content_hash,
    )
    uow.etf_holding_snapshots.add.return_value = SimpleNamespace(
        id=(holding_result or _FakeStored(_HOLDING_ID, "h_hash")).id,
        content_hash=(holding_result or _FakeStored(_HOLDING_ID, "h_hash")).content_hash,
    )


def _make_client() -> _FakeClient:
    return _FakeClient(
        index_response=_make_response(
            _index_payload(),
            operation="index_stock_cons_weight_csindex",
            raw_hash=_RAW_INDEX_HASH,
        ),
        holdings_response=_make_response(
            _holdings_payload(),
            operation="fund_portfolio_hold_em",
            raw_hash=_RAW_HOLDINGS_HASH,
        ),
    )


def _factories() -> tuple[Callable[[], UUID], Callable[[], datetime]]:
    return (lambda: UUID("99999999-9999-4999-8999-999999999999"), lambda: _NOW)


# ----------------------------------------------------------------------
# Validation (no I/O)
# ----------------------------------------------------------------------


class ValidationTest(unittest.TestCase):
    """Typed validation errors raised BEFORE any I/O."""

    def test_invalid_symbol_raises(self) -> None:
        with self.assertRaises(InvalidSymbolError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol="abc",
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_short_symbol_raises(self) -> None:
        with self.assertRaises(InvalidSymbolError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol="51030",
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_empty_exchange_raises(self) -> None:
        with self.assertRaises(InvalidExchangeError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange="   ",
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_invalid_index_code_raises(self) -> None:
        with self.assertRaises(InvalidIndexCodeError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code="ABCXYZ",
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_invalid_holding_year_raises(self) -> None:
        with self.assertRaises(InvalidHoldingYearError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
                holding_year="202a",
            )

    def test_non_date_effective_from_raises(self) -> None:
        with self.assertRaises(InvalidMappingDateError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from="2026-01-01",  # type: ignore[arg-type]
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_effective_to_before_from_raises(self) -> None:
        with self.assertRaises(InvalidMappingDateError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                mapping_effective_to=date(2025, 1, 1),
                observed_at=_NOW,
                uow_factory=lambda: _FakeUoW(),
            )

    def test_naive_observed_at_raises(self) -> None:
        with self.assertRaises(NaiveObservedAtError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=datetime(2026, 8, 1),
                uow_factory=lambda: _FakeUoW(),
            )

    def test_validation_does_not_open_uow(self) -> None:
        factory = MagicMock(return_value=_FakeUoW())
        with self.assertRaises(InvalidSymbolError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol="bad",
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=factory,
            )
        factory.assert_not_called()


# ----------------------------------------------------------------------
# Instrument resolution (lookup UoW)
# ----------------------------------------------------------------------


class InstrumentResolutionTest(unittest.TestCase):
    """Resolve the ETF by business key; reject missing / non-ETF / no-id."""

    def test_happy_lookup_uses_business_key(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        result = collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        uow.instruments.get_by_business_key.assert_called_with(
            exchange=_ETF_EXCHANGE, symbol=_ETF_SYMBOL
        )
        self.assertEqual(result.etf_id, _ETF_ID)

    def test_missing_instrument_rejected_before_network(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow, lookup=None)
        client = _make_client()
        with self.assertRaises(InstrumentNotFoundError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        # No client fetch must have happened.
        self.assertEqual(client.calls, [])

    def test_non_etf_rejected_before_network(self) -> None:
        uow = _FakeUoW()
        _wire_uow(
            uow,
            lookup=_instrument(instrument_type=InstrumentType.STOCK),
        )
        client = _make_client()
        with self.assertRaises(NonEtfInstrumentError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(client.calls, [])

    def test_missing_instrument_id_rejected_before_network(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow, lookup=_instrument(instrument_id=None))
        client = _make_client()
        with self.assertRaises(InstrumentIdMissingError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(client.calls, [])

    def test_lookup_uow_is_not_committed(self) -> None:
        # Use separate UoWs for lookup and persistence phases so we can
        # verify the lookup UoW was never committed even when both
        # roles are exercised.
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)
        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=_factory,
        )
        self.assertEqual(lookup_uow.commit_count, 0)
        self.assertGreaterEqual(lookup_uow.rollback_count, 1)
        self.assertEqual(persistence_uow.commit_count, 1)


# ----------------------------------------------------------------------
# Network ordering
# ----------------------------------------------------------------------


class NetworkOrderingTest(unittest.TestCase):
    """No network while a UoW is open; fetches happen between phases."""

    def test_network_after_lookup_exit_before_persistence_enter(self) -> None:
        lookup_uow = _FakeUoW()
        persistence_uow = _FakeUoW()
        _wire_uow(lookup_uow)
        _wire_uow(persistence_uow)

        class _TrackingFactory:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self) -> _FakeUoW:
                self.calls += 1
                if self.calls == 1:
                    return lookup_uow
                return persistence_uow

        factory = _TrackingFactory()

        class _TrackingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch_index_stock_cons_weight_csindex(self, *, index_code: str) -> AkshareResponse:
                self.calls.append("index")
                return _make_response(
                    _index_payload(),
                    operation="index_stock_cons_weight_csindex",
                    raw_hash=_RAW_INDEX_HASH,
                )

            def fetch_fund_portfolio_hold_em(self, *, etf_code: str, year: str) -> AkshareResponse:
                self.calls.append("holdings")
                return _make_response(
                    _holdings_payload(),
                    operation="fund_portfolio_hold_em",
                    raw_hash=_RAW_HOLDINGS_HASH,
                )

        client = _TrackingClient()
        collect_and_persist_real_exposure(
            client=client,
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=factory,
        )
        # Two UoW open/close cycles, two fetches in between.
        self.assertEqual(client.calls, ["index", "holdings"])
        # Second UoW (persistence) committed; lookup did not.
        self.assertEqual(persistence_uow.commit_count, 1)
        self.assertEqual(lookup_uow.commit_count, 0)
        self.assertGreaterEqual(lookup_uow.rollback_count, 1)

    def test_exact_client_args(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        client = _make_client()
        collect_and_persist_real_exposure(
            client=client,
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        self.assertEqual(
            client.calls[0],
            ("fetch_index_stock_cons_weight_csindex", {"index_code": _INDEX_CODE}),
        )
        self.assertEqual(
            client.calls[1],
            ("fetch_fund_portfolio_hold_em", {"etf_code": _ETF_SYMBOL, "year": ""}),
        )

    def test_holding_year_passed_through(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        client = _make_client()
        collect_and_persist_real_exposure(
            client=client,
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
            holding_year="2024",
        )
        self.assertEqual(client.calls[1][1]["year"], "2024")


# ----------------------------------------------------------------------
# Persistence ordering / mapping construction
# ----------------------------------------------------------------------


class MappingAndPersistenceTest(unittest.TestCase):
    """All four repos called, single commit, mapping built with explicit
    inputs and operator-controlled provenance."""

    def test_persistence_order_and_single_commit(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        uow.index_identities.add.assert_called_once()
        uow.index_profiles.add.assert_called_once()
        uow.index_constituent_snapshots.add.assert_called_once()
        uow.etf_index_mappings.add.assert_called_once()
        uow.etf_holding_snapshots.add.assert_called_once()
        self.assertEqual(uow.commit_count, 1)

    def test_index_identity_called_with_payload_fields(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        kwargs = uow.index_identities.add.call_args.kwargs
        self.assertEqual(kwargs["index_code"], _INDEX_CODE)
        self.assertEqual(kwargs["index_name"], "沪深300")
        self.assertIsNone(kwargs["category"])

    def test_mapping_uses_explicit_effective_dates_and_stable_index_id(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            mapping_effective_to=_EFFECTIVE_TO,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        mapping: EtfIndexMapping = uow.etf_index_mappings.add.call_args.args[0]
        self.assertEqual(mapping.index_id, _INDEX_ID)
        self.assertEqual(mapping.etf_id, _ETF_ID)
        self.assertEqual(mapping.effective_from, _EFFECTIVE_FROM)
        self.assertEqual(mapping.effective_to, _EFFECTIVE_TO)
        self.assertEqual(mapping.observed_at, _NOW)
        self.assertEqual(mapping.provenance.provider_key, "operator_controlled")
        self.assertEqual(mapping.provenance.dataset_key, "etf_index_mapping")
        self.assertEqual(mapping.provenance.observed_at, _NOW)
        self.assertEqual(mapping.provenance.revision, 1)
        self.assertEqual(mapping.provenance.confidence, Decimal("1"))

    def test_mapping_provenance_carries_source_batch_revision_confidence(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        batch_id = UUID("77777777-7777-4777-8777-777777777777")
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
            revision=3,
            confidence=Decimal("0.85"),
            mapping_source_batch_id=batch_id,
        )
        mapping: EtfIndexMapping = uow.etf_index_mappings.add.call_args.args[0]
        self.assertEqual(mapping.provenance.source_batch_id, batch_id)
        self.assertEqual(mapping.provenance.revision, 3)
        self.assertEqual(mapping.provenance.confidence, Decimal("0.85"))

    def test_effective_from_not_derived_from_observed_at(self) -> None:
        observed_at = datetime(2099, 9, 9, tzinfo=UTC)
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=observed_at,
            uow_factory=lambda: uow,
        )
        mapping: EtfIndexMapping = uow.etf_index_mappings.add.call_args.args[0]
        self.assertEqual(mapping.effective_from, _EFFECTIVE_FROM)
        self.assertNotEqual(mapping.effective_from, observed_at.date())

    def test_holding_provenance_confidence_revision_propagated(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
            revision=2,
            confidence=Decimal("0.5"),
        )
        holding = uow.etf_holding_snapshots.add.call_args.args[0]
        self.assertEqual(holding.provenance.revision, 2)
        self.assertEqual(holding.provenance.confidence, Decimal("0.5"))


# ----------------------------------------------------------------------
# Cross-section and persistence-recheck
# ----------------------------------------------------------------------


class CrossSectionValidationTest(unittest.TestCase):
    """Mapped bundle must agree with requested identifiers."""

    def test_index_code_mismatch_raises(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        client = _FakeClient(
            index_response=_make_response(
                [
                    {
                        "日期": date(2026, 7, 31).isoformat(),
                        "指数代码": "000999",  # DIFFERENT
                        "指数名称": "Other",
                        "成分券代码": "600519",
                        "权重": "12.5",
                    },
                ],
                operation="index_stock_cons_weight_csindex",
                raw_hash=_RAW_INDEX_HASH,
            ),
            holdings_response=_make_response(
                _holdings_payload(),
                operation="fund_portfolio_hold_em",
                raw_hash=_RAW_HOLDINGS_HASH,
            ),
        )
        with self.assertRaises(IndexCodeMismatchError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(uow.commit_count, 0)

    def test_holding_etf_id_mismatch_raises_when_mapper_uses_wrong_uuid(self) -> None:
        # Patch the holding mapper to emit a snapshot with a different
        # etf_id. Validates that the slice detects the drift and aborts.
        uow = _FakeUoW()
        _wire_uow(uow)

        wrong_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

        def _wrong_mapper(*args: Any, **kwargs: Any) -> Any:
            from invest_domain.exposure import (
                EtfHolding,
                EtfHoldingSnapshot,
            )

            return EtfHoldingSnapshot.create(
                etf_id=wrong_id,
                as_of_date=date(2026, 6, 30),
                observed_at=_NOW,
                holdings=(EtfHolding(stock_code="600519", weight=Decimal("0.125"), industry=None),),
                provenance=ExposureProvenance(
                    provider_key="akshare",
                    dataset_key="fund_portfolio_hold_em:reported_portfolio_holdings",
                    observed_at=_NOW,
                ),
            )

        with patch(
            "invest_pipeline.real_exposure_service.map_reported_etf_holdings",
            side_effect=_wrong_mapper,
        ), self.assertRaises(HoldingEtfIdMismatchError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(uow.commit_count, 0)


class PersistenceRecheckTest(unittest.TestCase):
    """The persistence UoW re-resolves the business key; mismatch aborts."""

    def test_lookup_uses_one_uow_persistence_uses_second(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        # Same business key returns the same UUID; happy case.
        _wire_uow(persistence_uow)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=_factory,
        )
        self.assertEqual(persistence_uow.instruments.get_by_business_key.call_count, 1)
        self.assertEqual(persistence_uow.commit_count, 1)

    def test_disappearance_in_persistence_uow_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow, lookup=None)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with self.assertRaises(InstrumentNotFoundError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)
        persistence_uow.index_identities.add.assert_not_called()
        persistence_uow.index_profiles.add.assert_not_called()

    def test_uuid_change_in_persistence_uow_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        changed = _instrument(instrument_id=InstrumentId(_ETF_ID_CHANGED))
        _wire_uow(persistence_uow, lookup=changed)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with self.assertRaises(InstrumentResolutionMismatchError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)
        persistence_uow.index_identities.add.assert_not_called()


# ----------------------------------------------------------------------
# Exceptions: no commit
# ----------------------------------------------------------------------


class ExceptionNoCommitTest(unittest.TestCase):
    """Mapper / client / persistence exceptions abort without commit."""

    def test_client_exception_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        class _ExplodingClient:
            def fetch_index_stock_cons_weight_csindex(self, *, index_code: str) -> AkshareResponse:
                raise RuntimeError("upstream 503")

            def fetch_fund_portfolio_hold_em(self, *, etf_code: str, year: str) -> AkshareResponse:
                raise AssertionError("must not be called")

        with self.assertRaises(RuntimeError):
            collect_and_persist_real_exposure(
                client=_ExplodingClient(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)

    def test_mapper_exception_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with patch(
            "invest_pipeline.real_exposure_service.map_csindex_constituent_weights",
            side_effect=ValueError("mapper broke"),
        ), self.assertRaises(ValueError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)

    def test_persistence_repository_exception_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow)
        persistence_uow.index_profiles.add.side_effect = RuntimeError("db boom")

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with self.assertRaises(RuntimeError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)


# ----------------------------------------------------------------------
# Happy path result shape and raw hashes
# ----------------------------------------------------------------------


class HappyPathResultTest(unittest.TestCase):
    """The returned frozen result carries every required identifier / hash."""

    def test_result_has_frozen_payload(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        result = collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            mapping_effective_to=_EFFECTIVE_TO,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        self.assertIsInstance(result, RealExposurePersistResult)
        self.assertEqual(result.etf_id, _ETF_ID)
        self.assertEqual(result.index_id, _INDEX_ID)
        self.assertEqual(result.profile_id, _PROFILE_ID)
        self.assertEqual(result.profile_content_hash, "p_hash")
        self.assertEqual(result.constituent_snapshot_id, _CONSTITUENT_ID)
        self.assertEqual(result.constituent_content_hash, "c_hash")
        self.assertEqual(result.mapping_id, _MAPPING_ID)
        self.assertEqual(result.mapping_content_hash, "m_hash")
        self.assertEqual(result.holding_snapshot_id, _HOLDING_ID)
        self.assertEqual(result.holding_content_hash, "h_hash")
        self.assertEqual(result.constituents_raw_payload_hash, _RAW_INDEX_HASH)
        self.assertEqual(result.holdings_raw_payload_hash, _RAW_HOLDINGS_HASH)
        with self.assertRaises((AttributeError, dataclasses.FrozenInstanceError)):
            result.etf_id = uuid4()  # frozen dataclass raises on mutation


class IdempotentStoredReturnsTest(unittest.TestCase):
    """Repository ``add`` may short-circuit to a stored row; the slice
    respects the repository's returned identifiers/hashes."""

    def test_respects_returned_stored_identifiers(self) -> None:
        uow = _FakeUoW()
        new_profile_id = UUID("a1111111-1111-4111-8111-111111111111")
        _wire_uow(
            uow,
            profile_result=_FakeStored(new_profile_id, "new_prof_hash"),
        )
        result = collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_NOW,
            uow_factory=lambda: uow,
        )
        self.assertEqual(result.profile_id, new_profile_id)
        self.assertEqual(result.profile_content_hash, "new_prof_hash")


class ServiceErrorHierarchyTest(unittest.TestCase):
    """All exposed errors inherit from RealExposureServiceError."""

    def test_all_errors_are_service_errors(self) -> None:
        self.assertTrue(issubclass(InvalidSymbolError, RealExposureServiceError))
        self.assertTrue(issubclass(InvalidExchangeError, RealExposureServiceError))
        self.assertTrue(issubclass(InvalidIndexCodeError, RealExposureServiceError))
        self.assertTrue(issubclass(InvalidMappingDateError, RealExposureServiceError))
        self.assertTrue(issubclass(InvalidHoldingYearError, RealExposureServiceError))
        self.assertTrue(issubclass(NaiveObservedAtError, RealExposureServiceError))
        self.assertTrue(issubclass(InstrumentNotFoundError, RealExposureServiceError))
        self.assertTrue(issubclass(NonEtfInstrumentError, RealExposureServiceError))
        self.assertTrue(issubclass(InstrumentIdMissingError, RealExposureServiceError))
        self.assertTrue(issubclass(IndexCodeMismatchError, RealExposureServiceError))
        self.assertTrue(issubclass(HoldingEtfIdMismatchError, RealExposureServiceError))
        self.assertTrue(issubclass(InstrumentResolutionMismatchError, RealExposureServiceError))


class InactiveInitialLookupTest(unittest.TestCase):
    """Regression: the initial lookup UoW must reject an inactive instrument.

    The service resolves the ETF by ``(exchange, symbol)`` business key
    in a short lookup UoW and explicitly checks ``is_active`` before
    any network call. A real AkShare run must never be launched for an
    instrument that the core schema already marks as inactive, even if
    the business key still resolves a row.
    """

    def test_inactive_instrument_rejected_before_network(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow, lookup=_instrument(is_active=False))
        client = _make_client()
        with self.assertRaises(InstrumentResolutionMismatchError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(client.calls, [])

    def test_inactive_instrument_does_not_open_persistence_uow(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow, lookup=_instrument(is_active=False))
        persistence_uow = _FakeUoW()
        _wire_uow(persistence_uow)

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with self.assertRaises(InstrumentResolutionMismatchError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(state["n"], 1)
        self.assertEqual(lookup_uow.commit_count, 0)
        self.assertEqual(persistence_uow.commit_count, 0)
        persistence_uow.index_identities.add.assert_not_called()


class PrecommitValidationPreventsCommitTest(unittest.TestCase):
    """Regression: precommit validation must abort before ``commit()`` is called.

    The persistence UoW runs a recheck (instrument exists, is an ETF, is
    active, has the same UUID) and a cross-section validation before
    any of the four write repositories are invoked. When either check
    raises, the surrounding UoW context manager must roll back without
    ever invoking ``commit()`` so a partial persistence state cannot
    leak into the WAL stream.
    """

    def test_inactive_persistence_recheck_aborts_no_commit(self) -> None:
        lookup_uow = _FakeUoW()
        _wire_uow(lookup_uow)

        persistence_uow = _FakeUoW()
        _wire_uow(
            persistence_uow,
            lookup=_instrument(
                is_active=False,
                instrument_id=InstrumentId(_ETF_ID),
            ),
        )

        state = {"n": 0}

        def _factory() -> _FakeUoW:
            state["n"] += 1
            return lookup_uow if state["n"] == 1 else persistence_uow

        with self.assertRaises(InstrumentResolutionMismatchError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=_factory,
            )
        self.assertEqual(persistence_uow.commit_count, 0)
        persistence_uow.index_identities.add.assert_not_called()
        persistence_uow.index_profiles.add.assert_not_called()
        persistence_uow.etf_index_mappings.add.assert_not_called()
        persistence_uow.etf_holding_snapshots.add.assert_not_called()

    def test_cross_section_validation_aborts_no_commit(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        client = _FakeClient(
            index_response=_make_response(
                [
                    {
                        "日期": date(2026, 7, 31).isoformat(),
                        "指数代码": "000999",
                        "指数名称": "Other",
                        "成分券代码": "600519",
                        "权重": "12.5",
                    },
                ],
                operation="index_stock_cons_weight_csindex",
                raw_hash=_RAW_INDEX_HASH,
            ),
            holdings_response=_make_response(
                _holdings_payload(),
                operation="fund_portfolio_hold_em",
                raw_hash=_RAW_HOLDINGS_HASH,
            ),
        )
        with self.assertRaises(IndexCodeMismatchError):
            collect_and_persist_real_exposure(
                client=client,
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_NOW,
                uow_factory=lambda: uow,
            )
        self.assertEqual(uow.commit_count, 0)
        uow.index_identities.add.assert_not_called()
        uow.etf_index_mappings.add.assert_not_called()

    def test_effective_date_validation_prevents_factory_call(self) -> None:
        factory = MagicMock(return_value=_FakeUoW())
        with self.assertRaises(InvalidMappingDateError):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                mapping_effective_to=date(2025, 1, 1),
                observed_at=_NOW,
                uow_factory=factory,
            )
        factory.assert_not_called()


# ----------------------------------------------------------------------
# Observed-at UTC normalization (idempotency / hash stability)
# ----------------------------------------------------------------------


_PLUS_EIGHT = timezone(timedelta(hours=8))
_INSTANT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_INSTANT_PLUS_EIGHT = datetime(2026, 8, 1, 8, 0, 0, tzinfo=_PLUS_EIGHT)


class ObservedAtUtcNormalizationTest(unittest.TestCase):
    """Regression: timezone-aware ``observed_at`` must be normalized to UTC

    before it reaches the mappers or the operator :class:`EtfIndexMapping`.

    The canonical hash uses :func:`datetime.isoformat`, which preserves
    the input offset (``+08:00`` vs ``+00:00``). Two inputs that are the
    same instant but different offsets therefore produce different
    ``content_hash`` digests, so a re-collect after PostgreSQL
    reconstructs the timestamp in UTC would be treated as a new
    evidence row instead of an idempotent no-op. The slice must
    normalize to UTC right after validation so the mappers, the
    operator mapping, and the canonical hash are all offset-agnostic.
    """

    def test_constituents_mapper_receives_utc_normalized_observed_at(self) -> None:
        captured: dict[str, Any] = {}
        real_fn = _exposure_mapper_module.map_csindex_constituent_weights

        def _spy(*args: Any, **kwargs: Any) -> Any:
            captured["observed_at"] = kwargs["observed_at"]
            captured["args"] = args
            return real_fn(*args, **kwargs)

        uow = _FakeUoW()
        _wire_uow(uow)
        with patch(
            "invest_pipeline.real_exposure_service.map_csindex_constituent_weights",
            side_effect=_spy,
        ):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_INSTANT_PLUS_EIGHT,
                uow_factory=lambda: uow,
            )
        self.assertEqual(captured["observed_at"], _INSTANT_UTC)
        self.assertEqual(captured["observed_at"].utcoffset(), timedelta(0))

    def test_holding_mapper_receives_utc_normalized_observed_at(self) -> None:
        captured: dict[str, Any] = {}
        real_fn = _holding_mapper_module.map_reported_etf_holdings

        def _spy(*args: Any, **kwargs: Any) -> Any:
            captured["observed_at"] = kwargs["observed_at"]
            return real_fn(*args, **kwargs)

        uow = _FakeUoW()
        _wire_uow(uow)
        with patch(
            "invest_pipeline.real_exposure_service.map_reported_etf_holdings",
            side_effect=_spy,
        ):
            collect_and_persist_real_exposure(
                client=_make_client(),
                etf_symbol=_ETF_SYMBOL,
                etf_exchange=_ETF_EXCHANGE,
                index_code=_INDEX_CODE,
                mapping_effective_from=_EFFECTIVE_FROM,
                observed_at=_INSTANT_PLUS_EIGHT,
                uow_factory=lambda: uow,
            )
        self.assertEqual(captured["observed_at"], _INSTANT_UTC)
        self.assertEqual(captured["observed_at"].utcoffset(), timedelta(0))

    def test_mapping_observed_at_is_utc_normalized(self) -> None:
        uow = _FakeUoW()
        _wire_uow(uow)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_INSTANT_PLUS_EIGHT,
            uow_factory=lambda: uow,
        )
        mapping: EtfIndexMapping = uow.etf_index_mappings.add.call_args.args[0]
        self.assertEqual(mapping.observed_at, _INSTANT_UTC)
        self.assertEqual(mapping.observed_at.utcoffset(), timedelta(0))
        self.assertEqual(mapping.provenance.observed_at, _INSTANT_UTC)
        self.assertEqual(mapping.provenance.observed_at.utcoffset(), timedelta(0))

    def test_repeated_call_with_plus_eight_produces_stable_mapping_hash(self) -> None:
        uow_a = _FakeUoW()
        _wire_uow(uow_a)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_INSTANT_PLUS_EIGHT,
            uow_factory=lambda: uow_a,
        )
        mapping_a: EtfIndexMapping = uow_a.etf_index_mappings.add.call_args.args[0]

        uow_b = _FakeUoW()
        _wire_uow(uow_b)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_INSTANT_PLUS_EIGHT,
            uow_factory=lambda: uow_b,
        )
        mapping_b: EtfIndexMapping = uow_b.etf_index_mappings.add.call_args.args[0]

        self.assertEqual(mapping_a.content_hash, mapping_b.content_hash)

    def test_plus_eight_and_utc_representations_produce_same_mapping_hash(self) -> None:
        uow_plus_eight = _FakeUoW()
        _wire_uow(uow_plus_eight)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_INSTANT_PLUS_EIGHT,
            uow_factory=lambda: uow_plus_eight,
        )
        mapping_plus_eight: EtfIndexMapping = (
            uow_plus_eight.etf_index_mappings.add.call_args.args[0]
        )

        uow_utc = _FakeUoW()
        _wire_uow(uow_utc)
        collect_and_persist_real_exposure(
            client=_make_client(),
            etf_symbol=_ETF_SYMBOL,
            etf_exchange=_ETF_EXCHANGE,
            index_code=_INDEX_CODE,
            mapping_effective_from=_EFFECTIVE_FROM,
            observed_at=_INSTANT_UTC,
            uow_factory=lambda: uow_utc,
        )
        mapping_utc: EtfIndexMapping = uow_utc.etf_index_mappings.add.call_args.args[0]

        self.assertEqual(
            mapping_plus_eight.content_hash,
            mapping_utc.content_hash,
        )


if __name__ == "__main__":
    unittest.main()
