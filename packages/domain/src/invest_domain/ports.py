from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from invest_domain.instruments import Instrument


class InstrumentProvider(Protocol):
    def list_instruments(self) -> Sequence[Instrument]: ...


class InstrumentRepository(Protocol):
    def upsert_many(self, instruments: Sequence[Instrument]) -> int: ...

    def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[Instrument]: ...
