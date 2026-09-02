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


class TestZeroOrNegativePrice:
    """Finite non-positive OHLC values raise ``ZERO_OR_NEGATIVE_PRICE``.

    The Domain :class:`DailyBar` helper would otherwise raise a plain
    ``ValueError`` ("must be > 0") that escapes the mapper/adapter
    evidence boundary; the mapper MUST convert these into a
    ``ProviderDataContractError`` with a stable contract code so the
    application service can classify the failure as CONTRACT.
    """

    def test_zero_open_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(op="0.0")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "ZERO_OR_NEGATIVE_PRICE"

    def test_negative_close_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(close="-0.500")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "ZERO_OR_NEGATIVE_PRICE"

    def test_zero_high_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(hi="0.0")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "ZERO_OR_NEGATIVE_PRICE"

    def test_negative_low_raises_contract_error(self) -> None:
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(lo="-0.001")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "ZERO_OR_NEGATIVE_PRICE"

    def test_volume_zero_is_still_accepted(self) -> None:
        # Volume and amount follow a non-negative (``>= 0``) Domain
        # contract — the mapper must NOT widen ZERO_OR_NEGATIVE_PRICE
        # to volume/amount, otherwise suspended-session / half-day
        # fixtures would regress.
        result = map_query_history_k_data_plus(
            _response([_row(vol="0", amt="0")]),
            symbols=["sh.510300"], source=_source(UUID(int=1)),
        )
        assert len(result.bars) == 1
        assert result.bars[0].volume == Decimal("0")

    def test_non_finite_close_still_raises_invalid_numeric(self) -> None:
        # The non-finite / negative split must stay intact: ``NaN`` is
        # caught by ``INVALID_NUMERIC`` (the mapper's ``is_finite``
        # guard), not by the new OHLC strictness check.
        with pytest.raises(ProviderDataContractError) as exc:
            map_query_history_k_data_plus(
                _response([_row(close="NaN")]),
                symbols=["sh.510300"], source=_source(UUID(int=1)),
            )
        assert exc.value.code == "INVALID_NUMERIC"