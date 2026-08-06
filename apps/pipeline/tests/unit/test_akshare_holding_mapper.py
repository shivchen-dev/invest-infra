"""Focused tests for the DC-3 ``akshare.holding_mapper`` module.

Pins happy values, latest-quarter selection, provenance, quarter end,
latest-quarter duplicate fails closed); row-order-independent holdings
tuple / hash; Q1..Q4 quarter boundaries; wrong operation / empty /
malformed / missing-field payloads; invalid quarter / etf_id /
observed_at / 股票代码 / 占净值比例 (all parametrized).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from invest_domain.exposure import EtfHoldingSnapshot
from invest_pipeline.adapters.akshare.client import AkshareResponse
from invest_pipeline.adapters.akshare.holding_mapper import map_reported_etf_holdings
from invest_pipeline.adapters.errors import ProviderDataContractError

_OP = "fund_portfolio_hold_em"
_DS = "fund_portfolio_hold_em:reported_portfolio_holdings"
_ETF = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_ETF2 = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_ZERO_ETF = UUID("00000000-0000-0000-0000-000000000000")
_OBS = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
_OBS8 = datetime(2026, 7, 31, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
_NAIVE_OBS = datetime(2026, 7, 31, 12, 0, 0)
_SNAP_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
_CREATED = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_QA = "akshare"


def _ids() -> UUID:
    return _SNAP_ID


def _now() -> datetime:
    return _CREATED


def _resp(payload: Any, *, op: str = _OP) -> AkshareResponse:
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return AkshareResponse(
        operation=op,
        raw_payload=payload,
        raw_payload_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _row(
    *, code: Any = "600519", weight: Any = "12.5", quarter: str = "2024年4季度"
) -> dict[str, Any]:
    return {"股票代码": code, "占净值比例": weight, "季度": quarter}


def _std() -> list[dict[str, Any]]:
    return [
        _row(code="600519", weight="12.5"),
        _row(code="601318", weight="5.0"),
        _row(code="000858", weight="3.0"),
        _row(code="300750", weight="2.0"),
    ]


def _map(
    payload: list[dict[str, Any]] | None = None,
    *,
    op: str = _OP,
    obs: datetime = _OBS,
    etf: UUID = _ETF,
) -> EtfHoldingSnapshot:
    return map_reported_etf_holdings(
        _resp(payload if payload is not None else _std(), op=op),
        etf_id=etf,
        observed_at=obs,
        id_factory=_ids,
        now_factory=_now,
    )


def _assert_provider_error(info: pytest.ExceptionInfo, code: str) -> None:
    assert info.value.code == code
    assert info.value.provider_key == _QA


class TestHappyPath:
    def test_returns_etf_holding_snapshot(self) -> None:
        snap = _map()
        assert isinstance(snap, EtfHoldingSnapshot)
        assert snap.etf_id == _ETF

    def test_as_of_date_is_quarter_end(self) -> None:
        assert _map().as_of_date == datetime(2024, 12, 31).date()

    def test_weights_divided_by_100(self) -> None:
        by_code = {h.stock_code: h.weight for h in _map().holdings}
        assert by_code == {
            "600519": Decimal("0.125"),
            "601318": Decimal("0.05"),
            "000858": Decimal("0.03"),
            "300750": Decimal("0.02"),
        }

    def test_industry_is_none_on_every_holding(self) -> None:
        for h in _map().holdings:
            assert h.industry is None

    def test_provenance_metadata(self) -> None:
        prov = _map().provenance
        assert prov.provider_key == _QA
        assert prov.dataset_key == _DS
        assert prov.observed_at == _OBS
        assert prov.revision == 1
        assert prov.confidence == Decimal("1")
        assert prov.source_batch_id is None

    def test_snapshot_uses_injected_factories(self) -> None:
        snap = _map()
        assert snap.id == _SNAP_ID
        assert snap.created_at == _CREATED

    def test_utc_plus_eight_observed_at_accepted(self) -> None:
        assert _map(obs=_OBS8).provenance.observed_at == _OBS8

    def test_int_stock_code_zfilled_to_six_digits(self) -> None:
        snap = _map([_row(code=600519), _row(code="601318")])
        assert {h.stock_code for h in snap.holdings} == {"600519", "601318"}

    def test_explicit_etf_id_propagates(self) -> None:
        assert _map(etf=_ETF2).etf_id == _ETF2


class TestLatestQuarterSelection:
    def test_only_latest_quarter_rows_kept(self) -> None:
        snap = _map(
            [
                _row(code="600519", weight="10.0", quarter="2024年4季度"),
                _row(code="601318", weight="8.0", quarter="2024年4季度"),
                _row(code="600519", weight="9.0", quarter="2024年3季度"),
                _row(code="000858", weight="7.0", quarter="2024年2季度"),
            ]
        )
        assert {h.stock_code for h in snap.holdings} == {"600519", "601318"}
        by_code = {h.stock_code: h.weight for h in snap.holdings}
        assert by_code["600519"] == Decimal("0.10")
        assert by_code["601318"] == Decimal("0.08")

    def test_as_of_date_is_latest_quarter_end(self) -> None:
        snap = _map(
            [
                _row(quarter="2023年1季度"),
                _row(quarter="2024年2季度"),
                _row(quarter="2024年3季度"),
            ]
        )
        assert snap.as_of_date == datetime(2024, 9, 30).date()

    def test_same_stock_across_different_quarters_allowed(self) -> None:
        snap = _map(
            [
                _row(code="600519", weight="10.0", quarter="2024年4季度"),
                _row(code="600519", weight="9.0", quarter="2024年3季度"),
                _row(code="600519", weight="8.0", quarter="2024年2季度"),
            ]
        )
        assert len(snap.holdings) == 1
        assert snap.holdings[0].weight == Decimal("0.10")


class TestOrderIndependence:
    def test_holdings_sorted_by_stock_code(self) -> None:
        codes = [h.stock_code for h in _map().holdings]
        assert codes == sorted(codes, key=lambda c: (not c.startswith("6"), c))

    def test_reordered_payloads_yield_identical_hash(self) -> None:
        std = _std()
        h_orig = _map(std).content_hash
        h_rev = _map(list(reversed(std))).content_hash
        h_rot = _map([std[1], std[3], std[0], std[2]]).content_hash
        assert h_orig == h_rev == h_rot

    def test_content_hash_is_64_hex_chars(self) -> None:
        h = _map().content_hash
        assert len(h) == 64
        int(h, 16)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("2024年1季度", datetime(2024, 3, 31).date()),
        ("2024年2季度", datetime(2024, 6, 30).date()),
        ("2024年3季度", datetime(2024, 9, 30).date()),
        ("2024年4季度", datetime(2024, 12, 31).date()),
    ],
)
def test_quarter_boundaries(label: str, expected: Any) -> None:
    assert _map([_row(quarter=label)]).as_of_date == expected


class TestOperationAndPayload:
    def test_wrong_operation_raises(self) -> None:
        with pytest.raises(ProviderDataContractError) as info:
            _map(op="fund_etf_fund_info_em")
        _assert_provider_error(info, "WRONG_OPERATION")

    def test_empty_payload_raises(self) -> None:
        with pytest.raises(ProviderDataContractError) as info:
            _map([])
        _assert_provider_error(info, "EMPTY_PAYLOAD")

    def test_non_dict_row_raises(self) -> None:
        payload = _std()
        payload[1] = ["not", "a", "dict"]
        with pytest.raises(ProviderDataContractError) as info:
            _map(payload)
        _assert_provider_error(info, "MALFORMED_HOLDINGS_ROW")

    def test_non_akshare_response_raises(self) -> None:
        with pytest.raises(ProviderDataContractError):
            map_reported_etf_holdings(
                {"operation": _OP, "raw_payload": _std()},
                etf_id=_ETF,
                observed_at=_OBS,
            )

    def test_missing_required_field_raises(self) -> None:
        payload = _std()
        del payload[0]["季度"]
        with pytest.raises(ProviderDataContractError) as info:
            _map(payload)
        _assert_provider_error(info, "MISSING_REQUIRED_FIELD")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "2024-4Q",
        "2024年4Q",
        "2024年四季度",
        "2024年0季度",
        "2024年5季度",
        "2024年4 季度",
        "24年4季度",
        "2024年第4季度",
        "0000年1季度",
        "abc",
        "2024",
        20244,
    ],
)
def test_invalid_quarter_raises(bad: Any) -> None:
    with pytest.raises(ProviderDataContractError) as info:
        _map([_row(quarter=bad)])
    _assert_provider_error(info, "INVALID_QUARTER")


@pytest.mark.parametrize("bad", ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", None, 123, _ZERO_ETF])
def test_invalid_etf_id_raises(bad: Any) -> None:
    with pytest.raises(ProviderDataContractError) as info:
        _map(etf=bad)
    _assert_provider_error(info, "INVALID_ETF_ID")


@pytest.mark.parametrize("bad", [_NAIVE_OBS, "2026-07-31T12:00:00+00:00", 20260731, None])
def test_invalid_observed_at_raises(bad: Any) -> None:
    with pytest.raises(ProviderDataContractError) as info:
        _map(obs=bad)
    assert info.value.code in {"NAIVE_OBSERVED_AT", "INVALID_OBSERVED_AT"}
    assert info.value.provider_key == _QA


@pytest.mark.parametrize(
    "bad",
    [
        True,
        False,
        "",
        "   ",
        "12345",
        "1234567",
        "ABCDEF",
        "60051A",
        "600.19",
        -1,
        1000000,
        None,
        ["600519"],
    ],
)
def test_invalid_stock_code_raises(bad: Any) -> None:
    with pytest.raises(ProviderDataContractError) as info:
        _map([_row(code=bad)])
    _assert_provider_error(info, "INVALID_CODE")


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (True, "WEIGHT_IS_BOOL"),
        (False, "WEIGHT_IS_BOOL"),
        (float("inf"), "NON_FINITE_WEIGHT"),
        (float("-inf"), "NON_FINITE_WEIGHT"),
        (float("nan"), "NON_FINITE_WEIGHT"),
        ("NaN", "NON_FINITE_WEIGHT"),
        ("Infinity", "NON_FINITE_WEIGHT"),
        (Decimal("NaN"), "NON_FINITE_WEIGHT"),
        ("", "INVALID_WEIGHT"),
        ("   ", "INVALID_WEIGHT"),
        ("not-a-number", "INVALID_WEIGHT"),
        ("100.0001", "WEIGHT_OUT_OF_RANGE"),
        ("-0.1", "WEIGHT_OUT_OF_RANGE"),
        (None, "INVALID_WEIGHT"),
        ([1.0], "INVALID_WEIGHT"),
    ],
)
def test_invalid_weight_raises(bad: Any, code: str) -> None:
    with pytest.raises(ProviderDataContractError) as info:
        _map([_row(weight=bad)])
    _assert_provider_error(info, code)


@pytest.mark.parametrize("w", ["0", "0.0", "100", "100.0", Decimal("5.5"), 0, 100, 12.5, 5])
def test_weight_boundaries_and_numeric_types_accepted(w: Any) -> None:
    assert len(_map([_row(weight=w)]).holdings) == 1


class TestDuplicateHoldings:
    def test_duplicate_stock_in_latest_quarter_fails_closed(self) -> None:
        with pytest.raises(ProviderDataContractError) as info:
            _map([_row(code="600519", weight="10.0"), _row(code="600519", weight="8.0")])
        _assert_provider_error(info, "DUPLICATE_HOLDING")
