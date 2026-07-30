from __future__ import annotations

from collections.abc import Sequence

from invest_domain.instruments import Instrument, InstrumentType


class MockInstrumentProvider:
    """开发用 Provider。真实数据源适配器应放在同一层，而不是领域层。"""

    def list_instruments(self) -> Sequence[Instrument]:
        return [
            Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF),
            Instrument("510500", "中证500ETF", "SSE", InstrumentType.ETF),
            Instrument("159915", "创业板ETF", "SZSE", InstrumentType.ETF),
        ]
