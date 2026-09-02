"""BaoStock field-mapper tests (Slice-1 of PR-08)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from invest_pipeline.adapters.baostock.client import BaostockResponse
from invest_pipeline.adapters.baostock.mapper import map_query_history_k_data_plus
from invest_pipeline.adapters.errors import ProviderDataContractError


def _source(source_batch_id):
    return SimpleNamespace(provider_key="baostock", source_batch_id=source_batch_id)


def _response(rows):
    return BaostockResponse(
        operation="query_history_k_data_plus", raw_payload=rows, raw_payload_hash="x" * 64,
    )


def _row(code="sh.510300", d="2026-01-05", op="1.000", hi="1.100", lo="0.950",
         close="1.050", vol="1000", amt="1050.000"):
    return {
        "code": code, "date": d, "open": op, "high": hi, "low": lo,
        "close": close, "volume": vol, "amount": amt,
    }


class TestExchangeAndBarShape:
    def test_native_codes_map_to_correct_exchange(self) -> None:
        rows = [
            _row(code="sh.510300"),
            _row(code="sz.159901", op="0.900", hi="1.000", lo="0.850", close="0.950"),
        ]
        result = map_query_history_k_data_plus(
            _response(rows), symbols=["sh.510300", "sz.159901"], source=_source(UUID(int=1)),
        )
        assert len(result.bars) == 2
        assert result.bars[0].trade_date == date(2026, 1, 5)
        assert result.bars[0].open == Decimal("1.000")
        assert result.bars[0].close == Decimal("1.050")
        assert result.bars[0].volume == Decimal("1000")
        assert result.bars[0].amount == Decimal("1050.000")
        assert all(b.source.provider_key == "baostock" for b in result.bars)

    def test_unsupported_native_prefix_is_rejected(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(code="bj.000001")]),
                symbols=["bj.000001"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "UNSUPPORTED_EXCHANGE"


class TestSafetyInvariants:
    def test_non_finite_numeric_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(close="NaN")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "INVALID_NUMERIC"

    def test_ohlc_invariant_violation_raises_contract_error(self) -> None:
        # high (1.000) < max(open=2.000, close=1.500) → invalid OHLC.
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(op="2.000", hi="1.000", lo="0.500", close="1.500")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "OHLC_INVARIANT"

    def test_invalid_date_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(d="not-a-date")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "INVALID_DATE"

    def test_instrument_id_is_deterministic(self) -> None:
        rows = [_row()]
        a = map_query_history_k_data_plus(
            _response(rows), symbols=["sh.510300"], source=_source(UUID(int=1)),
        )
        b = map_query_history_k_data_plus(
            _response(rows), symbols=["sh.510300"], source=_source(UUID(int=1)),
        )
        assert a.bars[0].instrument_id == b.bars[0].instrument_id
