from __future__ import annotations

import dagster as dg

from invest_pipeline.assets import (
    etf_instruments,
    etf_instruments_raw,
    seed_instruments,
)

defs = dg.Definitions(
    assets=[seed_instruments, etf_instruments_raw, etf_instruments]
)
