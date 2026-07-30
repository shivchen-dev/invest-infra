"""Domain Port (Protocol) for the ``candidate_pool`` bounded context.

The calculator is a pure function (ADR-0008 / plan §9.4). The Port
exists to:

- Lock the call signature in a place the storage / pipeline layers can
  import without depending on a specific implementation.
- Document the inputs the calculator MUST receive explicitly (no
  ``datetime.now()``, no ``os.environ``, no global config).
- Allow the M4 implementation to live in ``apps/pipeline`` and be
  wired in via a Port implementation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TYPE_CHECKING, runtime_checkable

from invest_domain.candidate_pool.models import (
    CalculationContext,
    CandidatePoolPolicy,
    CandidatePoolResult,
)
from invest_domain.instruments.models import Instrument, InstrumentId

if TYPE_CHECKING:
    from invest_domain.market_data.models import DailyBar


@runtime_checkable
class CandidatePoolCalculator(Protocol):
    """Protocol for a pure candidate-pool calculator.

    Implementations MUST NOT:

    - read or write any database;
    - perform HTTP / SDK calls;
    - read ``os.environ`` or any global settings object;
    - call ``datetime.now()`` or any other implicit time source;
    - write log files or send notifications.

    Everything the calculator needs is passed in via the four parameters.
    The function is expected to be deterministic: same input, same
    output. The application service is responsible for persisting the
    returned :class:`CandidatePoolResult`.
    """

    def build_candidate_pool(
        self,
        instruments: Sequence[Instrument],
        histories: Mapping[InstrumentId, Sequence["DailyBar"]],
        policy: CandidatePoolPolicy,
        context: CalculationContext,
    ) -> CandidatePoolResult: ...
