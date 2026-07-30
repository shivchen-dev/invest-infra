"""Backward-compatibility shim for pre-M1 domain Port imports.

The canonical ``InstrumentProvider`` Protocol now lives in
:mod:`invest_domain.market_data.ports` (the domain port for ETF market
data). This module re-exports that same class object so that legacy
import paths (``from invest_domain.ports import InstrumentProvider``) keep
working and ``isinstance`` checks against either path refer to the
identical type.

``InstrumentRepository`` is the historical storage-layer Protocol that
pre-dates the repository-per-bounded-context split. The new M1 storage
increments will replace it with a dedicated
``invest_storage.repositories.instruments.SqlAlchemyInstrumentRepository``
plus a domain-side Protocol in ``invest_storage.repositories.protocols``;
this increment does NOT migrate it. The Protocol remains here for
backward compatibility only and is marked for future storage cleanup.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from invest_domain.instruments import Instrument
from invest_domain.market_data.ports import InstrumentProvider as _CanonicalInstrumentProvider

# Re-export the canonical Protocol under its historical name. Both
# ``invest_domain.ports.InstrumentProvider`` and
# ``invest_domain.market_data.ports.InstrumentProvider`` reference the
# same class object.
InstrumentProvider = _CanonicalInstrumentProvider

__all__ = ["InstrumentProvider", "InstrumentRepository"]


# TODO(storage-cleanup): replace with a dedicated Protocol in
# ``invest_storage.repositories.protocols`` once M1 storage migrations
# land. Do not extend this Protocol in place; new repositories should
# implement the storage-side Protocol instead.
class InstrumentRepository(Protocol):
    def upsert_many(self, instruments: Sequence[Instrument]) -> int: ...

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]: ...
