from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from invest_domain.instruments.models import Instrument, InstrumentType
from invest_domain.instruments.values import InstrumentStatus
from invest_domain.market_data.models import ProviderAttemptStatus
from invest_domain.shared.values import Exchange
from invest_pipeline import provider_coverage_cli as cli
from invest_pipeline.provider_coverage_plan import (
    ActiveUniverseAmbiguityError,
    select_active_etf_symbols,
)
from invest_pipeline.provider_coverage_report import (
    default_daily_bars_field_set,
    serialize_coverage_report,
)


class StubProvider:
    provider_key = "fixture_dev"

    def __init__(self, records_by_symbol):
        self.records_by_symbol = records_by_symbol
        self.calls = []
        self.closed = False

    def fetch_daily_bars(self, symbols, start_date, end_date):
        symbol = symbols[0]
        self.calls.append((symbol, start_date, end_date))
        records = [
            SimpleNamespace(trade_date=trade_date)
            for trade_date in self.records_by_symbol.get(symbol, ())
        ]
        request = SimpleNamespace()
        attempt = SimpleNamespace(status=ProviderAttemptStatus.SUCCEEDED)
        batch = SimpleNamespace(
            status=SimpleNamespace(),
            records=records,
            raw_payload_hash="payload-hash",
            warnings=(),
        )
        return request, attempt, batch

    def close(self):
        self.closed = True


def make_runner(provider, generated_at="2026-08-04T00:00:00+00:00"):
    return cli.ProviderCoverageRunner(
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
        symbols=("510300", "510500"),
        provider=provider,
        generated_at=generated_at,
    )


def test_serialization_and_content_hash_are_deterministic():
    records = {"510300": (date(2026, 7, 23),), "510500": ()}
    first = make_runner(StubProvider(records), "2026-08-04T00:00:00+00:00").run()
    second = make_runner(StubProvider(records), "2026-08-05T00:00:00+00:00").run()

    assert first.content_hash == second.content_hash
    assert serialize_coverage_report(first) == serialize_coverage_report(first)
    assert json.loads(serialize_coverage_report(first))["content_hash"] == first.content_hash


def test_runner_isolates_symbols_with_and_without_records():
    provider = StubProvider({"510300": (date(2026, 7, 24),), "510500": ()})

    report = make_runner(provider).run()
    rows = {row.symbol: row for row in report.providers[0].symbols}

    assert [call[0] for call in provider.calls] == ["510300", "510500"]
    assert rows["510300"].record_count == 1
    assert rows["510300"].covered_start == date(2026, 7, 23)
    assert rows["510500"].record_count == 0
    assert rows["510500"].covered_start is None
    assert rows["510500"].fields == ()


def test_fixture_cli_main_succeeds_without_network(monkeypatch, capsys):
    provider = StubProvider({"510300": (date(2026, 7, 24),)})
    monkeypatch.setattr(cli, "_build_provider", lambda **_kwargs: provider)

    result = cli.main(
        [
            "--provider",
            "fixture_dev",
            "--symbols",
            "510300",
            "--generated-at",
            "2026-08-04T00:00:00+00:00",
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert json.loads(captured.out)["providers"][0]["provider_key"] == "fixture_dev"
    assert captured.err == ""
    assert provider.closed


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--symbols", "510300,,510500"], "empty entries"),
        (["--symbols", "510300", "--start-date", "2026/07/23"], "YYYY-MM-DD"),
        (
            [
                "--symbols",
                "510300",
                "--start-date",
                "2026-07-30",
                "--end-date",
                "2026-07-23",
            ],
            "must not be after",
        ),
    ],
)
def test_invalid_symbol_and_date_input(argv, message, capsys):
    assert cli.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_cifang_missing_opt_in_fails_closed(monkeypatch, capsys):
    built = False

    def unexpected_build(**_kwargs):
        nonlocal built
        built = True
        raise AssertionError("provider must not be built")

    monkeypatch.delenv("INVEST_PIPELINE_CIFANG_ENABLED", raising=False)
    monkeypatch.setattr(cli, "_build_provider", unexpected_build)

    assert cli.main(["--provider", "cifangquant", "--symbols", "510300"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("refused:")
    assert not built


def test_token_string_is_absent_from_output(monkeypatch, capsys):
    token = "super-secret-provider-token"
    provider = StubProvider({"510300": (date(2026, 7, 24),)})
    monkeypatch.setenv("INVEST_PIPELINE_CIFANG_API_KEY", token)
    monkeypatch.setattr(cli, "_build_provider", lambda **_kwargs: provider)

    assert cli.main(["--provider", "fixture_dev", "--symbols", "510300"]) == 0
    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err


# ---------------------------------------------------------------------------
# ProviderCoverageRunner.from_active_instruments bridge
# ---------------------------------------------------------------------------


def _make_instrument(
    *,
    symbol: str,
    exchange: str = Exchange.SSE,
    instrument_type: InstrumentType = InstrumentType.ETF,
    is_active: bool = True,
    status: InstrumentStatus = InstrumentStatus.ACTIVE,
    delist_date: date | None = None,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"name-{symbol}",
        exchange=exchange,
        instrument_type=instrument_type,
        is_active=is_active,
        status=status,
        delist_date=delist_date,
    )


def test_from_active_instruments_returns_sorted_active_etf_symbols():
    provider = StubProvider({})
    instruments = (
        _make_instrument(symbol="510500"),
        _make_instrument(symbol="159915"),
        _make_instrument(symbol="510300"),
    )

    runner = cli.ProviderCoverageRunner.from_active_instruments(
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
        instruments=instruments,
        provider=provider,
    )

    assert runner.symbols == ("159915", "510300", "510500")
    assert isinstance(runner.symbols, tuple)
    assert runner.symbols == select_active_etf_symbols(instruments)
    assert runner.start_date == date(2026, 7, 23)
    assert runner.end_date == date(2026, 7, 30)
    assert runner.provider is provider
    assert runner.requested_fields == default_daily_bars_field_set()
    assert runner.generated_at is None
    assert not provider.closed


def test_from_active_instruments_filters_through_bridge():
    provider = StubProvider({})
    instruments = (
        _make_instrument(symbol="510300"),
        _make_instrument(symbol="159915", exchange=Exchange.SZSE),
        _make_instrument(
            symbol="600000",
            instrument_type=InstrumentType.STOCK,
        ),
        _make_instrument(symbol="510310", is_active=False),
        _make_instrument(symbol="510320", status=InstrumentStatus.SUSPENDED),
        _make_instrument(
            symbol="510330",
            status=InstrumentStatus.DELISTED,
            delist_date=date(2026, 1, 1),
        ),
    )

    runner = cli.ProviderCoverageRunner.from_active_instruments(
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
        instruments=instruments,
        provider=provider,
    )

    assert runner.symbols == ("159915", "510300")


def test_from_active_instruments_propagates_cross_exchange_ambiguity():
    provider = StubProvider({})
    instruments = (
        _make_instrument(symbol="510300", exchange=Exchange.SSE),
        _make_instrument(symbol="510300", exchange=Exchange.SZSE),
    )

    with pytest.raises(ActiveUniverseAmbiguityError) as exc_info:
        cli.ProviderCoverageRunner.from_active_instruments(
            start_date=date(2026, 7, 23),
            end_date=date(2026, 7, 30),
            instruments=instruments,
            provider=provider,
        )

    assert "510300" in str(exc_info.value)
    assert Exchange.SSE in str(exc_info.value)
    assert Exchange.SZSE in str(exc_info.value)
    assert not provider.closed


def test_from_active_instruments_returns_empty_symbol_runner_for_empty_input():
    provider = StubProvider({})

    runner = cli.ProviderCoverageRunner.from_active_instruments(
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 30),
        instruments=(),
        provider=provider,
    )

    assert runner.symbols == ()
    assert isinstance(runner.symbols, tuple)
    assert runner.provider is provider
    assert runner.requested_fields == default_daily_bars_field_set()
    assert not provider.closed
