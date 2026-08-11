"""Behavioral tests for the pure A-share price-limit policy."""

from datetime import date
from decimal import Decimal

from invest_domain.market_data.price_limits import (
    DEFAULT_PRICE_LIMIT_REGIMES,
    Board,
    ListingStatus,
    PriceLimitInput,
    PriceLimitPolicy,
    PriceLimitRegime,
    UnknownPriceLimit,
)


def _input(**overrides: object) -> PriceLimitInput:
    values: dict[str, object] = {
        "instrument_id": "600000",
        "market": "SSE",
        "board": Board.MAIN,
        "trade_date": date(2026, 8, 11),
        "listed_trade_session_no": 100,
        "listing_status": ListingStatus.NORMAL,
        "reference_price": Decimal("10.00"),
        "source_refs": ("quote-source:2026-08-11",),
    }
    values.update(overrides)
    return PriceLimitInput(**values)  # type: ignore[arg-type]


def test_main_stock_returns_known_limits_and_regime_id() -> None:
    result = PriceLimitPolicy().evaluate(_input())

    assert result.limit_up_price == Decimal("11.00")
    assert result.limit_down_price == Decimal("9.00")
    assert result.regime_id == "SSE_MAIN_2023_04_10"
    assert result.reference_price == Decimal("10.00")


def test_main_risk_warning_uses_five_percent() -> None:
    result = PriceLimitPolicy().evaluate(
        _input(listing_status=ListingStatus.RISK_WARNING)
    )

    assert result.limit_up_price == Decimal("10.50")
    assert result.limit_down_price == Decimal("9.50")


def test_gem_star_and_bse_use_their_board_ratios() -> None:
    cases = [
        ("SZSE", Board.GEM, "12.00", "8.00"),
        ("SSE", Board.STAR, "12.00", "8.00"),
        ("BSE", Board.BSE, "13.00", "7.00"),
    ]

    for market, board, upper, lower in cases:
        result = PriceLimitPolicy().evaluate(
            _input(market=market, board=board, reference_price=Decimal("10"))
        )
        assert result.limit_up_price == Decimal(upper)
        assert result.limit_down_price == Decimal(lower)


def test_ipo_unlimited_boundaries_are_last_unlimited_then_known() -> None:
    policy = PriceLimitPolicy()
    for board, market, regime_id in (
        (Board.MAIN, "SSE", "SSE_MAIN_2023_04_10"),
        (Board.GEM, "SZSE", "SZSE_GEM_2020_08_24"),
        (Board.STAR, "SSE", "SSE_STAR_2019_07_22"),
    ):
        unlimited = policy.evaluate(
            _input(board=board, market=market, listed_trade_session_no=5)
        )
        known = policy.evaluate(
            _input(board=board, market=market, listed_trade_session_no=6)
        )
        assert unlimited.regime_id == regime_id
        assert unlimited.session_no == 5
        assert known.regime_id == regime_id
        assert known.limit_up_price is not None

    bse_first = policy.evaluate(
        _input(market="BSE", board=Board.BSE, listed_trade_session_no=1)
    )
    bse_second = policy.evaluate(
        _input(market="BSE", board=Board.BSE, listed_trade_session_no=2)
    )
    assert bse_first.session_no == 1
    assert bse_second.limit_up_price == Decimal("13.00")


def test_limit_prices_round_half_up_to_tick_size() -> None:
    result = PriceLimitPolicy().evaluate(
        _input(reference_price=Decimal("10.05"))
    )

    assert result.limit_up_price == Decimal("11.06")
    assert result.limit_down_price == Decimal("9.05")


def test_missing_required_inputs_are_unknown() -> None:
    policy = PriceLimitPolicy()
    for missing in (
        {"reference_price": None},
        {"listed_trade_session_no": None},
        {"source_refs": ()},
        {"listing_status": None},
    ):
        result = policy.evaluate(_input(**missing))
        assert isinstance(result, UnknownPriceLimit)


def test_unknown_board_and_conflicting_status_are_unknown() -> None:
    policy = PriceLimitPolicy()
    assert isinstance(policy.evaluate(_input(board="UNKNOWN")), UnknownPriceLimit)
    assert isinstance(
        policy.evaluate(_input(listing_status=ListingStatus.CONFLICT)),
        UnknownPriceLimit,
    )


def test_bse_special_treatment_is_fail_closed() -> None:
    result = PriceLimitPolicy().evaluate(
        _input(market="BSE", board=Board.BSE, listing_status=ListingStatus.SPECIAL_TREATMENT)
    )
    assert isinstance(result, UnknownPriceLimit)


def test_historical_regime_is_selected_instead_of_current_regime() -> None:
    historical = PriceLimitRegime(
        regime_id="SSE_MAIN_HISTORICAL_2020",
        market="SSE",
        board=Board.MAIN,
        effective_from=date(2020, 1, 1),
        effective_to=date(2023, 4, 10),
        normal_ratio=Decimal("0.05"),
        risk_warning_ratio=Decimal("0.05"),
        ipo_unlimited_sessions=1,
        source_refs=("sse-rule:2020",),
    )
    policy = PriceLimitPolicy((historical, *DEFAULT_PRICE_LIMIT_REGIMES))

    result = policy.evaluate(_input(trade_date=date(2022, 1, 4)))

    assert result.regime_id == "SSE_MAIN_HISTORICAL_2020"
    assert result.limit_up_price == Decimal("10.50")


def test_missing_or_overlapping_regime_is_fail_closed() -> None:
    no_regime = PriceLimitPolicy(()).evaluate(_input())
    assert isinstance(no_regime, UnknownPriceLimit)

    overlapping = PriceLimitRegime(
        regime_id="SSE_MAIN_OVERLAP",
        market="SSE",
        board=Board.MAIN,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        normal_ratio=Decimal("0.10"),
        risk_warning_ratio=Decimal("0.05"),
        ipo_unlimited_sessions=5,
        source_refs=("sse-rule:overlap",),
    )
    result = PriceLimitPolicy((*DEFAULT_PRICE_LIMIT_REGIMES, overlapping)).evaluate(_input())
    assert isinstance(result, UnknownPriceLimit)


def test_regime_without_source_is_fail_closed() -> None:
    regime_without_source = PriceLimitRegime(
        regime_id="SSE_MAIN_WITHOUT_SOURCE",
        market="SSE",
        board=Board.MAIN,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        normal_ratio=Decimal("0.10"),
        risk_warning_ratio=Decimal("0.05"),
        ipo_unlimited_sessions=5,
    )

    result = PriceLimitPolicy((regime_without_source,)).evaluate(_input())

    assert isinstance(result, UnknownPriceLimit)
