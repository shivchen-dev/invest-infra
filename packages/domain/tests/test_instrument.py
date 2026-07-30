"""Tests for the ``instruments`` bounded context."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from invest_domain.instruments.models import (
    Instrument,
    InstrumentId,
    InstrumentType,
)
from invest_domain.instruments.values import InstrumentStatus


class TestInstrumentId:
    def test_generate_returns_unique_ids(self) -> None:
        first = InstrumentId.generate()
        second = InstrumentId.generate()
        assert first != second
        assert isinstance(first.value, UUID)

    def test_from_string_accepts_canonical_form(self) -> None:
        iid = InstrumentId.from_string("12345678-1234-5678-1234-567812345678")
        assert str(iid) == "12345678-1234-5678-1234-567812345678"

    def test_from_string_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            InstrumentId.from_string("   ")

    def test_from_string_rejects_malformed(self) -> None:
        with pytest.raises(ValueError):
            InstrumentId.from_string("not-a-uuid")

    def test_nil_uuid_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            InstrumentId.from_string("00000000-0000-0000-0000-000000000000")

    def test_non_uuid_type_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            InstrumentId("not-a-uuid")  # type: ignore[arg-type]


class TestInstrument:
    def test_legacy_constructor_still_works(self) -> None:
        item = Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF)
        assert item.symbol == "510300"
        assert item.is_active is True
        assert item.instrument_id is None
        assert item.currency.value == "CNY"
        assert item.status is InstrumentStatus.ACTIVE

    def test_empty_symbol_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Instrument("", "沪深300ETF", "SSE", InstrumentType.ETF)

    def test_empty_name_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Instrument("510300", "   ", "SSE", InstrumentType.ETF)

    def test_empty_exchange_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Instrument("510300", "沪深300ETF", "", InstrumentType.ETF)

    @pytest.mark.parametrize("bad_exchange", ["NYSE", "HKEX", "BSE", "BVC", "sse", "Szse"])
    def test_non_allowed_exchange_is_rejected(self, bad_exchange: str) -> None:
        with pytest.raises(ValueError, match="ADR-0004 allow-list"):
            Instrument("510300", "沪深300ETF", bad_exchange, InstrumentType.ETF)

    def test_delist_before_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be on or after"):
            Instrument(
                "510300",
                "沪深300ETF",
                "SSE",
                InstrumentType.ETF,
                list_date=date(2024, 1, 1),
                delist_date=date(2023, 1, 1),
            )

    def test_valid_to_before_valid_from_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="valid_to"):
            Instrument(
                "510300",
                "沪深300ETF",
                "SSE",
                InstrumentType.ETF,
                valid_from=date(2024, 1, 1),
                valid_to=date(2023, 1, 1),
            )

    def test_delisted_requires_delist_date(self) -> None:
        with pytest.raises(ValueError, match="DELISTED requires a delist_date"):
            Instrument(
                "510300",
                "沪深300ETF",
                "SSE",
                InstrumentType.ETF,
                status=InstrumentStatus.DELISTED,
            )

    def test_delisted_with_delist_date_is_accepted(self) -> None:
        item = Instrument(
            "510300",
            "沪深300ETF",
            "SSE",
            InstrumentType.ETF,
            status=InstrumentStatus.DELISTED,
            delist_date=date(2025, 6, 30),
        )
        assert item.status is InstrumentStatus.DELISTED

    def test_business_key_combines_exchange_and_symbol(self) -> None:
        item = Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF)
        assert item.business_key == ("SSE", "510300")

    def test_provider_symbol_map_must_be_dict(self) -> None:
        with pytest.raises(ValueError, match="provider_symbol_map"):
            Instrument(
                "510300",
                "沪深300ETF",
                "SSE",
                InstrumentType.ETF,
                provider_symbol_map="not-a-dict",  # type: ignore[arg-type]
            )

    def test_instrument_with_explicit_id_round_trips(self) -> None:
        iid = InstrumentId.generate()
        item = Instrument(
            "510300",
            "沪深300ETF",
            "SSE",
            InstrumentType.ETF,
            instrument_id=iid,
        )
        assert item.instrument_id is iid
