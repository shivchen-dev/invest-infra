"""BaoStock adapter (Slice-1 of PR-08)."""

from invest_pipeline.adapters.baostock.adapter import (
    DATASET_KEY,
    PROVIDER_KEY,
    BaostockEtfDailyBarsAdapter,
)
from invest_pipeline.adapters.baostock.client import BaostockClient, BaostockResponse
from invest_pipeline.adapters.baostock.config import BaostockSettings
from invest_pipeline.adapters.baostock.mapper import (
    BaostockDailyBarsMappingResult,
    map_query_history_k_data_plus,
)

__all__ = [
    "BaostockClient",
    "BaostockDailyBarsMappingResult",
    "BaostockEtfDailyBarsAdapter",
    "BaostockResponse",
    "BaostockSettings",
    "DATASET_KEY",
    "PROVIDER_KEY",
    "map_query_history_k_data_plus",
]
