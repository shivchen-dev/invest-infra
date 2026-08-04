"""Focused unit tests for ``invest_pipeline.provider_coverage_plan``.

The module is a tiny, pure, side-effect-free planning helper on top of
:class:`invest_pipeline.provider_coverage_report.CoverageReportModel`.
These tests cover:

* ``select_active_etf_symbols`` — filtering by instrument kind, active
  flag, lifecycle status and exchange allow-list, plus the ambiguity
  guard that protects callers from silently picking the wrong row.
* ``BackfillPlanItem`` — the frozen slots dataclass contract and its
  ``dataclasses.asdict`` JSON compatibility.
* ``build_backfill_plan`` — exclusion of complete, error-free rows;
  reason labelling for failed probes vs missing/partial coverage; and
  deterministic priority ordering using the
  ``(provider_priority, 0/1, symbol)`` tuple.

The tests construct dataclasses directly; they never touch the network,
the database, or the filesystem.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date

import pytest
from invest_domain.instruments.models import Instrument, InstrumentType
from invest_domain.instruments.values import InstrumentStatus
from invest_domain.shared.values import Exchange
from invest_pipeline.provider_coverage_plan import (
    ActiveUniverseAmbiguityError,
    BackfillPlanItem,
    build_backfill_plan,
    select_active_etf_symbols,
)
from invest_pipeline.provider_coverage_report import (
    CoverageError,
    CoverageReportModel,
    ProviderCoverageRow,
    SymbolCoverageRow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument(
    *,
    symbol: str,
    exchange: str = Exchange.SSE,
    instrument_type: InstrumentType = InstrumentType.ETF,
    is_active: bool = True,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
    list_date: date | None = None,
    delist_date: date | None = None,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"name-{symbol}",
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        status=status,
        list_date=list_date,
        delist_date=delist_date,
    )


def _make_symbol_row(
    *,
    symbol: str,
    fields: tuple[str, ...] = (),
    requested_fields: tuple[str, ...] | None = None,
    errors: tuple[CoverageError, ...] = (),
    record_count: int = 0,
) -> SymbolCoverageRow:
    return SymbolCoverageRow(
        symbol=symbol,
        requested_start=None,
        requested_end=None,
        covered_start=None,
        covered_end=None,
        record_count=record_count,
        fields=fields,
        requested_fields=requested_fields,
        warnings=(),
        errors=errors,
    )


def _make_provider_row(
    *,
    provider_key: str,
    symbols: tuple[SymbolCoverageRow, ...],
    requested_fields: tuple[str, ...] | None = None,
) -> ProviderCoverageRow:
    return ProviderCoverageRow(
        provider_key=provider_key,
        symbols=symbols,
        requested_start=None,
        requested_end=None,
        requested_fields=requested_fields,
        raw_payload_hash=None,
    )


def _make_report(
    providers: tuple[ProviderCoverageRow, ...],
) -> CoverageReportModel:
    return CoverageReportModel(
        schema_version=1,
        generated_at="2026-08-04T00:00:00+00:00",
        content_hash="placeholder",
        providers=tuple(sorted(providers, key=lambda provider: provider.provider_key)),
    )


# ---------------------------------------------------------------------------
# select_active_etf_symbols
# ---------------------------------------------------------------------------


def test_select_active_etf_symbols_returns_tuple_of_filtered_sorted_symbols() -> None:
    instruments = (
        _make_instrument(symbol="510300"),
        _make_instrument(symbol="159915"),
        _make_instrument(symbol="510500"),
        # Dropped: not ETF
        _make_instrument(
            symbol="600000",
            instrument_type=InstrumentType.STOCK,
        ),
        # Dropped: not active
        _make_instrument(symbol="510310", is_active=False),
        # Dropped: suspended
        _make_instrument(
            symbol="510320",
            status=InstrumentStatus.SUSPENDED,
        ),
        # Dropped: delisted
        _make_instrument(
            symbol="510330",
            status=InstrumentStatus.DELISTED,
            delist_date=date(2026, 1, 1),
        ),
    )

    result = select_active_etf_symbols(instruments)

    assert result == ("159915", "510300", "510500")
    assert isinstance(result, tuple)


def test_select_active_etf_symbols_keeps_both_sse_and_szse() -> None:
    instruments = (
        _make_instrument(symbol="510300", exchange=Exchange.SSE),
        _make_instrument(symbol="159915", exchange=Exchange.SZSE),
    )

    result = select_active_etf_symbols(instruments)

    assert result == ("159915", "510300")


def test_select_active_etf_symbols_handles_empty_input() -> None:
    assert select_active_etf_symbols(()) == ()


def test_select_active_etf_symbols_raises_on_cross_exchange_ambiguity() -> None:
    instruments = (
        _make_instrument(symbol="510300", exchange=Exchange.SSE),
        _make_instrument(symbol="510300", exchange=Exchange.SZSE),
    )

    with pytest.raises(ActiveUniverseAmbiguityError) as exc_info:
        select_active_etf_symbols(instruments)

    assert "510300" in str(exc_info.value)
    # Both exchanges are mentioned in the error.
    message = str(exc_info.value)
    assert Exchange.SSE in message
    assert Exchange.SZSE in message


def test_active_universe_ambiguity_error_is_value_error_subclass() -> None:
    assert issubclass(ActiveUniverseAmbiguityError, ValueError)
    # Constructible; usable as a normal exception.
    err = ActiveUniverseAmbiguityError("oops")
    assert isinstance(err, ValueError)
    assert str(err) == "oops"


def test_select_active_etf_symbols_preserves_no_window_behavior() -> None:
    """``start_date=None`` and ``end_date=None`` keep the legacy result.

    The inclusive window is purely additive: omitting both dates (the
    default signature) must yield exactly the same tuple as the
    historical implementation so legacy callers stay bit-identical.
    """

    instruments = (
        # Within window by definition (no window supplied).
        _make_instrument(symbol="510300"),
        # ``list_date`` is set but the window is None → keeps.
        _make_instrument(
            symbol="159915",
            exchange=Exchange.SZSE,
            list_date=date(2030, 1, 1),
        ),
        # ``delist_date`` is set but ``status`` is still ACTIVE → the
        # pre-window logic kept it; with no window supplied the post-
        # window logic must also keep it.
        _make_instrument(
            symbol="510310",
            delist_date=date(2030, 1, 1),
        ),
    )

    baseline = select_active_etf_symbols(instruments)

    assert baseline == ("159915", "510300", "510310")
    # Calling with explicit ``None`` arguments produces the same tuple.
    assert select_active_etf_symbols(
        instruments, start_date=None, end_date=None
    ) == baseline
    # Same call without the keyword arguments also matches: this is the
    # one form every legacy caller relied on, so it must be bit-stable.
    assert select_active_etf_symbols(instruments) == baseline
    # Instruments with ``list_date`` / ``delist_date`` set to ``None``
    # pass the matching check unchanged when the corresponding date
    # argument is supplied, so adding a date that no instrument's
    # recorded lifecycle crosses still matches the baseline.
    instruments_no_listing = (
        _make_instrument(symbol="510300"),
        _make_instrument(symbol="159915", exchange=Exchange.SZSE),
    )
    assert (
        select_active_etf_symbols(
            instruments_no_listing,
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
        )
        == ("159915", "510300")
    )


def test_select_active_etf_symbols_excludes_pre_listing_instruments() -> None:
    """Instruments with ``list_date > end_date`` are excluded from the window."""

    instruments = (
        # Listed well before the window → kept.
        _make_instrument(
            symbol="510300",
            list_date=date(2010, 1, 1),
        ),
        # Listed exactly on ``end_date`` → inclusive boundary, kept.
        _make_instrument(
            symbol="510500",
            list_date=date(2026, 7, 30),
        ),
        # ``list_date`` one day after ``end_date`` → excluded.
        _make_instrument(
            symbol="510510",
            list_date=date(2026, 7, 31),
        ),
        # Far-future listing → excluded.
        _make_instrument(
            symbol="159915",
            exchange=Exchange.SZSE,
            list_date=date(2030, 1, 1),
        ),
    )

    result = select_active_etf_symbols(
        instruments,
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
    )

    assert result == ("510300", "510500")


def test_select_active_etf_symbols_excludes_post_delisting_instruments() -> None:
    """Instruments with ``delist_date < start_date`` are excluded from the window.

    The pre-window ``status=ACTIVE`` filter used to keep these rows in
    the universe; the new window logic drops them so coverage probing
    never asks a Provider about an instrument that had already been
    delisted before the window opened.
    """

    instruments = (
        # ``delist_date`` far in the future → kept.
        _make_instrument(
            symbol="510300",
            delist_date=date(2030, 1, 1),
        ),
        # ``delist_date`` exactly on ``start_date`` → inclusive
        # boundary, kept.
        _make_instrument(
            symbol="510500",
            delist_date=date(2026, 7, 23),
        ),
        # ``delist_date`` one day before ``start_date`` → excluded.
        _make_instrument(
            symbol="510510",
            delist_date=date(2026, 7, 22),
        ),
        # Long-delisted → excluded.
        _make_instrument(
            symbol="159915",
            exchange=Exchange.SZSE,
            delist_date=date(2020, 1, 1),
        ),
    )

    result = select_active_etf_symbols(
        instruments,
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
    )

    assert result == ("510300", "510500")


# ---------------------------------------------------------------------------
# BackfillPlanItem
# ---------------------------------------------------------------------------


def test_backfill_plan_item_is_frozen_slots_dataclass() -> None:
    item = BackfillPlanItem(
        provider_key="akshare",
        symbol="510300",
        priority=(10, 0, "510300"),
        reason="failed_probe",
    )

    # Slot-based dataclass: no __dict__.
    assert not hasattr(item, "__dict__")
    # Frozen: mutation is rejected.
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.symbol = "510500"  # type: ignore[misc]


def test_backfill_plan_item_supports_asdict_and_json_round_trip() -> None:
    item = BackfillPlanItem(
        provider_key="akshare",
        symbol="510300",
        priority=(10, 0, "510300"),
        reason="failed_probe",
    )

    as_dict = dataclasses.asdict(item)
    assert as_dict == {
        "provider_key": "akshare",
        "symbol": "510300",
            "priority": (10, 0, "510300"),
        "reason": "failed_probe",
    }
    # The dict is JSON-serialisable; JSON represents tuples as arrays.
    round_tripped = json.loads(json.dumps(as_dict))
    assert round_tripped["priority"] == list(as_dict["priority"])
    assert round_tripped | {"priority": as_dict["priority"]} == as_dict


# ---------------------------------------------------------------------------
# build_backfill_plan
# ---------------------------------------------------------------------------


def test_build_backfill_plan_excludes_complete_error_free_rows() -> None:
    fields = ("open", "high", "low", "close", "volume")
    provider = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(
            # Complete, no errors → excluded.
            _make_symbol_row(symbol="510300", fields=fields, record_count=5),
            # Complete, no errors → excluded.
            _make_symbol_row(symbol="510500", fields=fields, record_count=5),
        ),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 10})

    assert plan == ()


def test_build_backfill_plan_includes_failed_probes_with_correct_reason() -> None:
    fields = ("open", "high", "low", "close", "volume")
    error = CoverageError(
        provider_key="akshare",
        symbol="510300",
        code="TIMEOUT",
        message="request timed out",
    )
    provider = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(
            _make_symbol_row(
                symbol="510300",
                fields=fields,
                record_count=5,
                errors=(error,),
            ),
        ),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 10})

    assert len(plan) == 1
    assert plan[0].provider_key == "akshare"
    assert plan[0].symbol == "510300"
    assert plan[0].reason == "failed_probe"
    # 0 = error flag (failed probes sort ahead of missing rows).
    assert plan[0].priority[1] == 0


def test_build_backfill_plan_includes_missing_or_partial_coverage() -> None:
    fields = ("open", "high", "low", "close", "volume")
    provider = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(
            # Partial coverage, no errors.
            _make_symbol_row(
                symbol="510300",
                fields=("open", "close"),
                record_count=2,
            ),
            # Empty coverage, no errors.
            _make_symbol_row(symbol="510500", fields=(), record_count=0),
        ),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 10})

    assert len(plan) == 2
    assert {item.symbol for item in plan} == {"510300", "510500"}
    for item in plan:
        assert item.reason == "missing_or_partial_coverage"
        # 1 = no errors (still needs backfill but not a failed probe).
        assert item.priority[1] == 1


def test_build_backfill_plan_orders_failed_above_missing_within_provider() -> None:
    fields = ("open", "high", "low", "close", "volume")
    error = CoverageError(
        provider_key="akshare",
        symbol="510500",
        code="TIMEOUT",
        message="request timed out",
    )
    provider = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(
            # Missing coverage, no error → reason=missing_or_partial_coverage.
            _make_symbol_row(symbol="510300", fields=(), record_count=0),
            # Failed probe → reason=failed_probe (sorts first).
            _make_symbol_row(
                symbol="510500",
                fields=(),
                record_count=0,
                errors=(error,),
            ),
        ),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 10})

    assert [item.symbol for item in plan] == ["510500", "510300"]
    assert plan[0].reason == "failed_probe"
    assert plan[1].reason == "missing_or_partial_coverage"


def test_build_backfill_plan_orders_by_provider_priority_then_symbol() -> None:
    fields = ("open", "high", "low", "close", "volume")
    eastmoney = _make_provider_row(
        provider_key="eastmoney",
        requested_fields=fields,
        symbols=(_make_symbol_row(symbol="510300", fields=(), record_count=0),),
    )
    akshare = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(_make_symbol_row(symbol="510300", fields=(), record_count=0),),
    )
    report = _make_report((eastmoney, akshare))

    plan = build_backfill_plan(
        report,
        provider_priority={"akshare": 5, "eastmoney": 20},
    )

    # Lower provider_priority sorts first; symbol is the final tie-breaker.
    assert [item.provider_key for item in plan] == ["akshare", "eastmoney"]
    assert [item.priority[0] for item in plan] == [5, 20]
    assert [item.priority[2] for item in plan] == ["510300", "510300"]


def test_build_backfill_plan_uses_default_priority_when_provider_missing() -> None:
    fields = ("open", "high", "low", "close", "volume")
    provider = _make_provider_row(
        provider_key="unknown_provider",
        requested_fields=fields,
        symbols=(_make_symbol_row(symbol="510300", fields=(), record_count=0),),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 5})

    assert len(plan) == 1
    assert plan[0].provider_key == "unknown_provider"
    # Default 1000 when no explicit priority is supplied.
    assert plan[0].priority[0] == 1000


def test_build_backfill_plan_ignores_requested_fields_when_none() -> None:
    # When requested_fields is None the runner has no field-set contract,
    # so any row that recorded at least one field and has no errors is
    # treated as complete (no backfill needed).
    provider = _make_provider_row(
        provider_key="akshare",
        requested_fields=None,
        symbols=(
            _make_symbol_row(
                symbol="510300",
                fields=("open",),
                record_count=1,
            ),
        ),
    )
    report = _make_report((provider,))

    plan = build_backfill_plan(report, provider_priority={"akshare": 10})

    assert plan == ()


def test_build_backfill_plan_is_deterministic_across_calls() -> None:
    fields = ("open", "high", "low", "close", "volume")
    error = CoverageError(
        provider_key="eastmoney",
        symbol="159915",
        code="TIMEOUT",
        message="request timed out",
    )
    eastmoney = _make_provider_row(
        provider_key="eastmoney",
        requested_fields=fields,
        symbols=(
            _make_symbol_row(
                symbol="159915",
                fields=(),
                record_count=0,
                errors=(error,),
            ),
            _make_symbol_row(symbol="510300", fields=("open",), record_count=1),
        ),
    )
    akshare = _make_provider_row(
        provider_key="akshare",
        requested_fields=fields,
        symbols=(
            _make_symbol_row(symbol="510300", fields=(), record_count=0),
        ),
    )
    # The order of providers in the report is intentionally NOT alphabetical
    # to confirm the plan sorts by priority, not by input order.
    report = _make_report((eastmoney, akshare))

    first = build_backfill_plan(
        report, provider_priority={"akshare": 5, "eastmoney": 20}
    )
    second = build_backfill_plan(
        report, provider_priority={"akshare": 5, "eastmoney": 20}
    )

    assert first == second
    # And the plan itself is a tuple (immutable).
    assert isinstance(first, tuple)
    # Ordering: akshare(5) → eastmoney(20); within eastmoney, the failed
    # probe (159915) sorts before the missing row (510300) by error flag.
    assert [(item.provider_key, item.symbol) for item in first] == [
        ("akshare", "510300"),
        ("eastmoney", "159915"),
        ("eastmoney", "510300"),
    ]
