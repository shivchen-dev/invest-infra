"""Backward-compatibility shim.

The domain has moved to a subpackage (``invest_domain.instruments.*``) so
that ``Instrument`` can grow new fields without breaking every caller. This
module re-exports the public symbols that were originally defined here so
existing import paths (``from invest_domain.instruments import Instrument,
InstrumentType``) keep working.
"""

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.instruments.values import InstrumentStatus

__all__ = ["Instrument", "InstrumentId", "InstrumentStatus", "InstrumentType"]
