"""Pure, versioned price-limit policy for ordinary A-share stocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Board(StrEnum):
    MAIN = "main"
    GEM = "gem"
    STAR = "star"
    BSE = "bse"


class ListingStatus(StrEnum):
    NORMAL = "normal"
    RISK_WARNING = "risk_warning"
    SPECIAL_TREATMENT = "special_treatment"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class PriceLimitRegime:
    """One immutable rule version; ``effective_to`` is exclusive."""

    regime_id: str
    market: str
    board: Board | str
    effective_from: date
    effective_to: date | None
    normal_ratio: Decimal | None
    risk_warning_ratio: Decimal | None
    ipo_unlimited_sessions: int
    tick_size: Decimal = Decimal("0.01")
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.regime_id.strip() or not self.market.strip():
            raise ValueError("regime_id and market must not be empty")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        if self.ipo_unlimited_sessions < 0:
            raise ValueError("ipo_unlimited_sessions must not be negative")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        for ratio in (self.normal_ratio, self.risk_warning_ratio):
            if ratio is not None and not Decimal("0") <= ratio <= Decimal("1"):
                raise ValueError("price-limit ratios must be between zero and one")


@dataclass(frozen=True, slots=True)
class PriceLimitInput:
    """All facts required to calculate one trading-day price limit."""

    instrument_id: str | None = None
    market: str | None = None
    board: Board | str | None = None
    trade_date: date | None = None
    listed_trade_session_no: int | None = None
    listing_status: ListingStatus | str | None = None
    reference_price: Decimal | None = None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnownPriceLimit:
    limit_up_price: Decimal
    limit_down_price: Decimal
    regime_id: str
    reference_price: Decimal
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnlimitedPriceLimit:
    regime_id: str
    session_no: int
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnknownPriceLimit:
    reason: str
    required_fields: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()


type PriceLimitResult = KnownPriceLimit | UnlimitedPriceLimit | UnknownPriceLimit


def _regime(
    regime_id: str,
    market: str,
    board: Board,
    effective_from: date,
    normal_ratio: str,
    risk_warning_ratio: str | None,
    ipo_unlimited_sessions: int,
) -> PriceLimitRegime:
    return PriceLimitRegime(
        regime_id=regime_id,
        market=market,
        board=board,
        effective_from=effective_from,
        effective_to=None,
        normal_ratio=Decimal(normal_ratio),
        risk_warning_ratio=(
            None if risk_warning_ratio is None else Decimal(risk_warning_ratio)
        ),
        ipo_unlimited_sessions=ipo_unlimited_sessions,
        source_refs=(f"official-rule:{regime_id}",),
    )


DEFAULT_PRICE_LIMIT_REGIMES: tuple[PriceLimitRegime, ...] = (
    _regime("SSE_MAIN_2023_04_10", "SSE", Board.MAIN, date(2023, 4, 10), "0.10", "0.05", 5),
    _regime("SZSE_MAIN_2023_04_10", "SZSE", Board.MAIN, date(2023, 4, 10), "0.10", "0.05", 5),
    _regime("SZSE_GEM_2020_08_24", "SZSE", Board.GEM, date(2020, 8, 24), "0.20", "0.20", 5),
    _regime("SSE_STAR_2019_07_22", "SSE", Board.STAR, date(2019, 7, 22), "0.20", "0.20", 5),
    _regime("BSE_BSE_2021_11_15", "BSE", Board.BSE, date(2021, 11, 15), "0.30", None, 1),
)


def _combined_sources(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for group in groups for item in group))


@dataclass(frozen=True, slots=True)
class PriceLimitPolicy:
    """Select exactly one rule version and calculate its public result."""

    regimes: tuple[PriceLimitRegime, ...] = DEFAULT_PRICE_LIMIT_REGIMES

    def __post_init__(self) -> None:
        object.__setattr__(self, "regimes", tuple(self.regimes))

    def evaluate(self, facts: PriceLimitInput) -> PriceLimitResult:
        missing = tuple(
            name
            for name, value in (
                ("instrument_id", facts.instrument_id),
                ("market", facts.market),
                ("board", facts.board),
                ("trade_date", facts.trade_date),
                ("listed_trade_session_no", facts.listed_trade_session_no),
                ("listing_status", facts.listing_status),
                ("reference_price", facts.reference_price),
                ("source_refs", facts.source_refs),
            )
            if value is None or value == "" or value == ()
        )
        if missing:
            return UnknownPriceLimit("missing required input", missing)
        if facts.listed_trade_session_no is None or facts.listed_trade_session_no < 1:
            return UnknownPriceLimit("invalid listed trade session", ("listed_trade_session_no",))
        if facts.reference_price is None or facts.reference_price <= 0:
            return UnknownPriceLimit("invalid reference price", ("reference_price",))
        if facts.market not in {"SSE", "SZSE", "BSE"}:
            return UnknownPriceLimit("unknown market", ("market",), facts.source_refs)
        if not isinstance(facts.board, Board):
            try:
                board = Board(facts.board)
            except ValueError:
                return UnknownPriceLimit("unknown board", ("board",), facts.source_refs)
        else:
            board = facts.board
        try:
            status = ListingStatus(facts.listing_status)
        except ValueError:
            return UnknownPriceLimit(
                "unknown listing status", ("listing_status",), facts.source_refs
            )
        if status in {
            ListingStatus.UNKNOWN,
            ListingStatus.CONFLICT,
            ListingStatus.SPECIAL_TREATMENT,
        }:
            return UnknownPriceLimit(
                "unsupported or conflicting listing status",
                ("listing_status",),
                facts.source_refs,
            )

        matching = tuple(
            regime
            for regime in self.regimes
            if regime.market == facts.market
            and regime.board == board
            and regime.effective_from <= facts.trade_date
            and (regime.effective_to is None or facts.trade_date < regime.effective_to)
        )
        if len(matching) != 1:
            return UnknownPriceLimit(
                "regime is missing or not unique", ("regime_id",), facts.source_refs
            )
        regime = matching[0]
        if not regime.source_refs:
            return UnknownPriceLimit("regime has no source", ("source_refs",), facts.source_refs)
        if status is ListingStatus.RISK_WARNING and regime.risk_warning_ratio is None:
            return UnknownPriceLimit(
                "risk-warning ratio is unknown", ("listing_status",), facts.source_refs
            )

        sources = _combined_sources(facts.source_refs, regime.source_refs)
        session_no = facts.listed_trade_session_no
        if session_no <= regime.ipo_unlimited_sessions:
            return UnlimitedPriceLimit(regime.regime_id, session_no, sources)
        ratio = (
            regime.risk_warning_ratio
            if status is ListingStatus.RISK_WARNING
            else regime.normal_ratio
        )
        if ratio is None:
            return UnknownPriceLimit("price-limit ratio is unknown", ("listing_status",), sources)
        up = (facts.reference_price * (Decimal("1") + ratio)).quantize(
            regime.tick_size, rounding=ROUND_HALF_UP
        )
        down = (facts.reference_price * (Decimal("1") - ratio)).quantize(
            regime.tick_size, rounding=ROUND_HALF_UP
        )
        return KnownPriceLimit(up, down, regime.regime_id, facts.reference_price, sources)


__all__ = [
    "Board",
    "DEFAULT_PRICE_LIMIT_REGIMES",
    "KnownPriceLimit",
    "ListingStatus",
    "PriceLimitInput",
    "PriceLimitPolicy",
    "PriceLimitRegime",
    "PriceLimitResult",
    "UnknownPriceLimit",
    "UnlimitedPriceLimit",
]
