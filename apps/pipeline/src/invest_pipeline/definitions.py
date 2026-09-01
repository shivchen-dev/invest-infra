from __future__ import annotations

import dagster as dg

from invest_pipeline.assets import (
    etf_akshare_daily_bars,
    etf_daily_bars,
    etf_daily_bars_raw,
    etf_input_snapshot,
    etf_instruments,
    etf_instruments_raw,
    market_breadth_snapshot,
    personal_candidate_pool,
    seed_instruments,
    stock_daily_bars,
    stock_daily_bars_raw,
    stock_input_snapshot,
    stock_instruments,
    stock_instruments_raw,
)
from invest_pipeline.real_exposure_asset import real_exposure
from invest_pipeline.schedules import personal_etf_daily_schedule
from invest_pipeline.workbuddy_dagster import (
    workbuddy_result_import_job,
    workbuddy_result_import_schedule,
)

personal_etf_daily_job = dg.define_asset_job(
    name="personal_etf_daily_job",
    selection=[
        etf_instruments_raw,
        etf_instruments,
        etf_daily_bars_raw,
        etf_daily_bars,
        etf_akshare_daily_bars,
        etf_input_snapshot,
        personal_candidate_pool,
    ],
)

stock_market_data_job = dg.define_asset_job(
    name="stock_market_data_job",
    selection=[
        stock_instruments_raw,
        stock_instruments,
        stock_daily_bars_raw,
        stock_daily_bars,
        stock_input_snapshot,
        market_breadth_snapshot,
    ],
)

real_exposure_job = dg.define_asset_job(
    name="real_exposure_job",
    selection=[real_exposure],
)

defs = dg.Definitions(
    assets=[
        seed_instruments,
        etf_instruments_raw,
        etf_instruments,
        etf_input_snapshot,
        etf_daily_bars_raw,
        etf_daily_bars,
        etf_akshare_daily_bars,
        personal_candidate_pool,
        real_exposure,
        stock_instruments_raw,
        stock_instruments,
        stock_daily_bars_raw,
        stock_daily_bars,
        stock_input_snapshot,
        market_breadth_snapshot,
    ],
    jobs=[
        personal_etf_daily_job,
        real_exposure_job,
        stock_market_data_job,
        workbuddy_result_import_job,
    ],
    schedules=[personal_etf_daily_schedule, workbuddy_result_import_schedule],
)
