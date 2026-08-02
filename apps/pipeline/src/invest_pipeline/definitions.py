from __future__ import annotations

import dagster as dg

from invest_pipeline.assets import (
    etf_daily_bars,
    etf_daily_bars_raw,
    etf_input_snapshot,
    etf_instruments,
    etf_instruments_raw,
    personal_candidate_pool,
    seed_instruments,
)

personal_etf_daily_job = dg.define_asset_job(
    name="personal_etf_daily_job",
    selection=[
        etf_instruments_raw,
        etf_instruments,
        etf_daily_bars_raw,
        etf_daily_bars,
        etf_input_snapshot,
        personal_candidate_pool,
    ],
)

defs = dg.Definitions(
    assets=[
        seed_instruments,
        etf_instruments_raw,
        etf_instruments,
        etf_input_snapshot,
        etf_daily_bars_raw,
        etf_daily_bars,
        personal_candidate_pool,
    ],
    jobs=[personal_etf_daily_job],
)
