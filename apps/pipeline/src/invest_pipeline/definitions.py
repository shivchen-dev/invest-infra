from __future__ import annotations

import dagster as dg

from invest_pipeline.assets import seed_instruments


defs = dg.Definitions(assets=[seed_instruments])
