"""Public re-exports for the ``etf_profile`` bounded context.

The ``etf_profile`` bounded context captures the static, mostly
provider-supplied attributes of a single ETF instrument (manager,
benchmark_index, category, inception_date, fund_type, fees, AUM,
shares). It is the foundation for the Stage DC-2 vertical slice: the
domain contract is fixed first, then the PostgreSQL persistence layer
lands on top in ``apps/migrations`` /
``packages/storage/src/invest_storage``.

Provider responses do not always disclose every field, so the domain
model keeps every non-key field nullable. The dataclass never
fabricates a default value; explicit ``None`` is the only acceptable
representation for ``unknown`` provider data so downstream analytics can
distinguish ``unknown`` from a real zero/empty value.
"""

from invest_domain.etf_profile.models import EtfProfile

__all__ = ["EtfProfile"]
