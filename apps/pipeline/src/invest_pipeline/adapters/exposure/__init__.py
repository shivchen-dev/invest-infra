"""Index/ETF exposure adapter package (DC-3B vertical slice).

This package contains the AKShare exposure adapter plus the pure
mapping helpers that translate a standardized payload into the
``invest_domain.exposure`` value objects. The slice is intentionally
minimal:

* no network, no storage, no ContextPack, no API;
* no DAGster asset, no DB migration, no dependency additions;
* the AKShare adapter defaults to ``enabled=False`` and never touches
  the network at construction or fetch when disabled;
* mapping functions are pure and accept the standardized payload
  directly so that tests can inject a fake client or a loaded fixture
  without any I/O.
"""

from invest_pipeline.adapters.exposure.akshare_adapter import (
    AKShareExposureAdapter,
    AkShareExposureClientProtocol,
    AKShareExposureConfig,
    AKShareExposurePayload,
    fetch_akshare_exposure_payload,
)
from invest_pipeline.adapters.exposure.mapping import (
    AKShareExposureMappingError,
    AKShareExposureStandardizedPayload,
    map_etf_holding_snapshot,
    map_etf_index_mapping,
    map_index_constituent_snapshot,
    map_index_profile,
    map_standardized_payload,
)

__all__ = [
    "AKShareExposureAdapter",
    "AKShareExposureConfig",
    "AKShareExposureMappingError",
    "AKShareExposurePayload",
    "AKShareExposureStandardizedPayload",
    "AkShareExposureClientProtocol",
    "fetch_akshare_exposure_payload",
    "map_etf_holding_snapshot",
    "map_etf_index_mapping",
    "map_index_constituent_snapshot",
    "map_index_profile",
    "map_standardized_payload",
]
