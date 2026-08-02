from __future__ import annotations

import json
from pathlib import Path

import yaml
from invest_pipeline.personal_universe import load_personal_universe


def test_configured_personal_universe_symbols_are_covered_by_fixture() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    config_path = repo_root / "config" / "personal-universe.yaml"
    instruments_path = (
        repo_root
        / "apps"
        / "pipeline"
        / "src"
        / "invest_pipeline"
        / "adapters"
        / "fixture_dev"
        / "etf_instruments.json"
    )
    bars_path = instruments_path.with_name("etf_daily_bars.json")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    universe = load_personal_universe(config_path)
    instruments = json.loads(instruments_path.read_text(encoding="utf-8"))
    bars = json.loads(bars_path.read_text(encoding="utf-8"))

    configured_symbols = set(universe.symbols)
    instrument_by_symbol = {record["symbol"]: record for record in instruments}
    bar_symbols = {record["symbol"] for record in bars}

    assert configured_symbols == {
        symbol
        for group in config["enabled_groups"]
        for symbol in config["groups"][group]
    }
    assert configured_symbols <= instrument_by_symbol.keys()
    assert configured_symbols <= bar_symbols
    assert all(
        instrument_by_symbol[symbol]["exchange"] in {"SSE", "SZSE"}
        for symbol in configured_symbols
    )
