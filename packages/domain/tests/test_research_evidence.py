from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from invest_domain.instruments import InstrumentId
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus
from invest_domain.research import (
    FACTOR_KEYS,
    FACTOR_SET_KEY,
    FACTOR_SET_VERSION,
    SCHEMA_VERSION,
    CandidateContext,
    CaseContext,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    QualityGateStatus,
    QualityStatus,
    SourceReference,
    calculate_market_state_factors,
    canonical_pack_json,
    evaluate_quality_gate,
    pack_content_projection,
    pack_view,
)

_INSTRUMENT_ID = InstrumentId(
    UUID("12345678-1234-5678-9234-567812345678")
)
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=timezone.utc),
)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"


def _bars(
    count: int,
    *,
    amount_missing: bool = False,
    suspended_indexes: frozenset[int] = frozenset(),
) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    result: list[DailyBar] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        if index in suspended_indexes:
            result.append(
                DailyBar.build(
                    instrument_id=_INSTRUMENT_ID,
                    trade_date=trade_date,
                    open=None,
                    high=None,
                    low=None,
                    close=None,
                    prev_close=None,
                    volume=None,
                    amount=None,
                    adjustment=Adjust.NONE,
                    trading_status=TradingStatus.SUSPENDED,
                    source=_SOURCE,
                    revision=1,
                )
            )
            continue
        close = Decimal(100 + index)
        result.append(
            DailyBar.build(
                instrument_id=_INSTRUMENT_ID,
                trade_date=trade_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                prev_close=None if index == 0 else Decimal(99 + index),
                volume=Decimal(1000 + index),
                amount=None if amount_missing else Decimal(1_000_000 + index * 1000),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=_SOURCE,
                revision=1,
            )
        )
    return tuple(result)


def _calculation(bars: tuple[DailyBar, ...]):
    as_of = bars[-1].trade_date if bars else date(2026, 3, 6)
    return calculate_market_state_factors(
        bars,
        as_of_date=as_of,
        instrument_id=_INSTRUMENT_ID,
    )


def _pack(
    bars: tuple[DailyBar, ...] | None = None,
    *,
    case_id: str | None = "case-runtime-a",
    pack_id: UUID | None = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    pipeline_run_id: UUID | None = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
    request_id: str | None = "request-runtime-a",
    session_id: str | None = "session-runtime-a",
    generated_at: datetime | None = datetime(2026, 3, 6, 9, tzinfo=timezone.utc),
    workspace_path: str | None = "/runtime/workspace/a",
    warnings: tuple[str, ...] | None = None,
    source_refs: tuple[SourceReference, ...] | None = None,
) -> EvidencePack:
    selected = _bars(65) if bars is None else bars
    calculation = _calculation(selected)
    refs = source_refs or (
        SourceReference(
            source_kind="daily_bar",
            source_ref="core.daily_bars:2026-03-06",
            observed_date=date(2026, 3, 6),
            revision=1,
        ),
        SourceReference(
            source_kind="instrument",
            source_ref="core.instruments:510300",
            observed_date=date(2026, 3, 6),
        ),
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=date(2026, 3, 6),
            question=_QUESTION,
            case_id=case_id,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        candidate_context=CandidateContext(
            included=True,
            rank=2,
            total_score=Decimal("0.8750"),
            exclusion_codes=("zeta", "alpha"),
        ),
        market_snapshot=calculation.market_snapshot,
        factors=tuple(reversed(calculation.factors)),
        data_quality=calculation.data_quality,
        missing_fields=calculation.missing_fields,
        warnings=warnings or calculation.warnings,
        source_refs=tuple(reversed(refs)),
        pack_id=pack_id,
        pipeline_run_id=pipeline_run_id,
        e2a_request_id=request_id,
        e2a_session_id=session_id,
        generated_at=generated_at,
        workspace_path=workspace_path,
    )


def _factor_values(result) -> dict[str, Decimal | None]:
    return {item.factor_key: item.value for item in result.factors}


def test_contract_shape_and_versions_are_fixed() -> None:
    pack = _pack()
    payload = pack_view(pack)
    assert pack.schema_version == SCHEMA_VERSION == "1.0.0"
    assert pack.factor_set.key == FACTOR_SET_KEY == "etf_market_state_daily"
    assert pack.factor_set.version == FACTOR_SET_VERSION == "1.0.0"
    assert set(payload) >= {
        "schema_version",
        "factor_set",
        "case",
        "instrument",
        "candidate_context",
        "market_snapshot",
        "factors",
        "data_quality",
        "missing_fields",
        "warnings",
        "source_refs",
        "pack_hash",
    }
    assert {item["factor_key"] for item in payload["factors"]} == set(FACTOR_KEYS)


def test_canonical_projection_sorts_unordered_values_and_excludes_runtime_fields() -> None:
    first = _pack(warnings=("z-warning", "a-warning"))
    second = _pack(
        case_id="case-runtime-b",
        pack_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        pipeline_run_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        request_id="request-runtime-b",
        session_id="session-runtime-b",
        generated_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        workspace_path="/different/runtime/path",
        warnings=("a-warning", "z-warning", "a-warning"),
        source_refs=tuple(reversed(first.source_refs)),
    )
    assert canonical_pack_json(first) == canonical_pack_json(second)
    assert first.pack_hash == second.pack_hash
    canonical = canonical_pack_json(first)
    for excluded in (
        "case-runtime-a",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "request-runtime-a",
        "session-runtime-a",
        "/runtime/workspace/a",
        "evidence_id",
    ):
        assert excluded not in canonical


def test_pack_item_hashes_and_evidence_ids_are_stable_and_non_circular() -> None:
    first = _pack()
    second = _pack(case_id="other", request_id="other")
    assert first.pack_hash == second.pack_hash
    assert [item.item_hash for item in first.factors] == [
        item.item_hash for item in second.factors
    ]
    assert [item.evidence_id for item in first.factors] == [
        item.evidence_id for item in second.factors
    ]
    for item in first.factors:
        assert item.evidence_id == (
            f"evi:{first.pack_hash[:12]}:{item.evidence_key}:{item.item_hash[:12]}"
        )
        assert item.evidence_id not in canonical_pack_json(first)


def test_business_content_change_changes_item_and_pack_hashes() -> None:
    original = _pack()
    changed_bars = list(_bars(65))
    last = changed_bars[-1]
    changed_bars[-1] = DailyBar.build(
        instrument_id=last.instrument_id,
        trade_date=last.trade_date,
        open=Decimal("166"),
        high=Decimal("167"),
        low=Decimal("165"),
        close=Decimal("166"),
        prev_close=last.prev_close,
        volume=last.volume,
        amount=last.amount,
        adjustment=last.adjustment,
        trading_status=last.trading_status,
        source=last.source,
        revision=2,
    )
    changed = _pack(tuple(changed_bars))
    assert original.pack_hash != changed.pack_hash
    original_items = {item.factor_key: item.item_hash for item in original.factors}
    changed_items = {item.factor_key: item.item_hash for item in changed.factors}
    assert original_items["return_20d"] != changed_items["return_20d"]


def test_65_day_fixture_produces_all_eight_rounded_decimal_factors() -> None:
    result = _calculation(_bars(65))
    values = _factor_values(result)
    assert tuple(sorted(values)) == tuple(sorted(FACTOR_KEYS))
    assert values == {
        "return_20d": Decimal("0.13888889"),
        "return_60d": Decimal("0.57692308"),
        "distance_ma20": Decimal("0.06148867"),
        "distance_ma60": Decimal("0.21933086"),
        "realized_volatility_20d": Decimal("0.00389695"),
        "max_drawdown_60d": Decimal("0E-8"),
        "avg_turnover_amount_20d": Decimal("1054500.00000000"),
        "data_completeness_60d": Decimal("1.00000000"),
    }
    assert all(item.quality_status is QualityStatus.COMPLETE for item in result.factors)


def test_committed_65_day_fixture_produces_complete_factors() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "research"
        / "etf_daily_bars_65d.json"
    )
    records = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(records) == 65
    bars = tuple(
        DailyBar.build(
            instrument_id=_INSTRUMENT_ID,
            trade_date=date.fromisoformat(record["trade_date"]),
            open=Decimal(record["open"]),
            high=Decimal(record["high"]),
            low=Decimal(record["low"]),
            close=Decimal(record["close"]),
            prev_close=Decimal(record["prev_close"]),
            volume=Decimal(record["volume"]),
            amount=Decimal(record["amount"]),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus(record["trading_status"]),
            source=_SOURCE,
            revision=1,
        )
        for record in records
    )

    result = calculate_market_state_factors(
        bars,
        as_of_date=bars[-1].trade_date,
        instrument_id=_INSTRUMENT_ID,
    )
    values = _factor_values(result)

    assert set(values) == set(FACTOR_KEYS)
    assert all(isinstance(value, Decimal) for value in values.values())
    assert result.data_quality.quality_status is QualityStatus.COMPLETE


@pytest.mark.parametrize(
    "count,available,missing",
    [
        (19, (), ("distance_ma20", "avg_turnover_amount_20d")),
        (20, ("distance_ma20", "avg_turnover_amount_20d"), ("return_20d", "realized_volatility_20d")),
        (21, ("return_20d", "realized_volatility_20d"), ()),
        (59, (), ("distance_ma60", "max_drawdown_60d")),
        (60, ("distance_ma60", "max_drawdown_60d"), ("return_60d",)),
        (61, ("return_60d",), ()),
    ],
)
def test_factor_window_boundaries(
    count: int, available: tuple[str, ...], missing: tuple[str, ...]
) -> None:
    values = _factor_values(_calculation(_bars(count)))
    for key in available:
        assert values[key] is not None
    for key in missing:
        assert values[key] is None


def test_missing_amount_and_suspended_data_are_partial() -> None:
    missing_amount = _pack(_bars(65, amount_missing=True))
    values = {item.factor_key: item for item in missing_amount.factors}
    assert values["avg_turnover_amount_20d"].value is None
    assert evaluate_quality_gate(missing_amount).status is QualityGateStatus.PARTIAL

    suspended = _pack(_bars(65, suspended_indexes=frozenset({64})))
    assert suspended.data_quality.freshness_status is FreshnessStatus.PARTIAL
    assert suspended.data_quality.suspended_days == 1
    assert evaluate_quality_gate(suspended).status is QualityGateStatus.PARTIAL


def test_invalid_data_empty_data_and_missing_instrument_fail_domain_gate() -> None:
    invalid_bars = list(_bars(65))
    object.__setattr__(invalid_bars[-1], "close", Decimal("-1"))
    invalid = _pack(tuple(invalid_bars))
    assert invalid.data_quality.quality_status is QualityStatus.INVALID
    assert evaluate_quality_gate(invalid).status is QualityGateStatus.FAILED
    assert evaluate_quality_gate(_pack(), instrument_exists=False).status is QualityGateStatus.FAILED

    empty_calculation = _calculation(())
    empty_pack = EvidencePack(
        case=CaseContext(_INSTRUMENT_ID, date(2026, 3, 6), _QUESTION),
        instrument=InstrumentSnapshot(_INSTRUMENT_ID, "510300", "沪深300ETF", "SSE"),
        market_snapshot=empty_calculation.market_snapshot,
        factors=empty_calculation.factors,
        data_quality=empty_calculation.data_quality,
        missing_fields=empty_calculation.missing_fields,
        warnings=empty_calculation.warnings,
    )
    assert evaluate_quality_gate(empty_pack).status is QualityGateStatus.FAILED


def test_complete_pack_passes_domain_quality_gate() -> None:
    result = evaluate_quality_gate(_pack())
    assert result.status is QualityGateStatus.COMPLETE
    assert result.reasons == ()


def test_future_bars_are_rejected() -> None:
    bars = _bars(65)
    with pytest.raises(ValueError, match="future"):
        calculate_market_state_factors(
            bars,
            as_of_date=bars[-2].trade_date,
            instrument_id=_INSTRUMENT_ID,
        )


def test_contract_has_no_recommendation_or_ai_conclusion_fields() -> None:
    forbidden = {
        "recommendation",
        "stance",
        "position",
        "buy",
        "sell",
        "target_price",
        "ai_conclusion",
    }
    model_fields = {
        model_field.name
        for model in (
            EvidencePack,
            CaseContext,
            InstrumentSnapshot,
            CandidateContext,
            type(_pack().market_snapshot),
            type(_pack().factors[0]),
            type(_pack().data_quality),
            SourceReference,
        )
        for model_field in fields(model)
    }
    assert forbidden.isdisjoint(model_fields)
    assert forbidden.isdisjoint(_all_keys(pack_content_projection(_pack())))


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_golden_canonical_payload_and_hash() -> None:
    pack = _pack()
    assert canonical_pack_json(pack) == '{"candidate_context":{"exclusion_codes":["alpha","zeta"],"included":true,"rank":2,"total_score":"0.875"},"case":{"as_of_date":"2026-03-06","horizon":"20-60d","instrument_id":"12345678-1234-5678-9234-567812345678","question":"评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"},"data_quality":{"conflict_detected":false,"freshness_status":"fresh","invalid_days":0,"observed_trading_days":65,"quality_status":"complete","suspended_days":0,"target_trading_days":60,"valid_price_days":65},"factor_set":{"key":"etf_market_state_daily","version":"1.0.0"},"factors":[{"factor_key":"avg_turnover_amount_20d","item_hash":"52a44955e3291c707d89d5c86e53655231d854bd1995ac88d472aa92fa85c7b3","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"CNY","value":"1054500","window":20},{"factor_key":"data_completeness_60d","item_hash":"cdccbb3eaf3dd35ad6c3a373d2ff1bb85d32e0a367b79a4af3cb09ef3f02b38d","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"1","window":60},{"factor_key":"distance_ma20","item_hash":"f40c6cc172b4f7a9bc41e3c809412a1cdcd5ed07c9052117f7a95285a8044916","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"0.06148867","window":20},{"factor_key":"distance_ma60","item_hash":"c29d0d3c99e5df298dbcc0dd3f929813b2153662dcc471b89331b77918bccf99","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"0.21933086","window":60},{"factor_key":"max_drawdown_60d","item_hash":"f1fce955f257083c982cf0fc710524e466b88565fe31b68798bf33267ee5822b","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"0","window":60},{"factor_key":"realized_volatility_20d","item_hash":"d929c8ac45befa87cc51ad1edec8de044297ba9cd08e2373a88bda4ff468e3be","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"annualized_ratio","value":"0.00389695","window":20},{"factor_key":"return_20d","item_hash":"aa171a3c8fb3611f2664e12fc43d417237b77ebd2b5af834370e620efe7d6456","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"0.13888889","window":20},{"factor_key":"return_60d","item_hash":"1704d5bfc8714e75ea918c98ca3f84fecaff2cb46842f6881aeeeaa787e0733f","observed_date":"2026-03-06","quality_status":"complete","source_kind":"daily_bar","source_ref":"standardized_daily_bars","unit":"ratio","value":"0.57692308","window":60}],"instrument":{"currency":"CNY","exchange":"SSE","instrument_id":"12345678-1234-5678-9234-567812345678","name":"沪深300ETF","symbol":"510300"},"market_snapshot":{"currency":"CNY","latest_close":"164","latest_trade_date":"2026-03-06","observed_trading_days":65,"suspended_days":0,"valid_price_days":65},"missing_fields":[],"schema_version":"1.0.0","source_refs":[{"observed_date":"2026-03-06","quality_status":"complete","revision":1,"source_kind":"daily_bar","source_ref":"core.daily_bars:2026-03-06"},{"observed_date":"2026-03-06","quality_status":"complete","revision":null,"source_kind":"instrument","source_ref":"core.instruments:510300"}],"warnings":[]}'
    assert pack.pack_hash == "737e32847a78c5504883626915a94efd456b21a48c8cc40ba5a426fd8606ee30"
