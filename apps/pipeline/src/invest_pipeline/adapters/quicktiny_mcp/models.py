"""QuickTiny MCP read-only response models (PR-03).

These dataclasses are the *only* shape the QuickTiny adapter exposes to
the application layer. They are deliberately **not** mapped to
:class:`invest_domain.market_data.models.DailyBar` (PR-03 scope, matrix
§3 / §5.4 / §9.2): the catalog declares QuickTiny as
``research_only`` with capabilities ``RESEARCH`` and ``MARKET_SNAPSHOT``,
and the plan forbids QuickTiny responses from becoming production
``core.daily_bars`` rows.

Design rules:

- Every model is a frozen, ``slots=True`` dataclass so the response
  hashes used by ``ProviderBatch.raw_payload_hash`` remain stable across
  re-runs and accidental mutation is impossible.
- ``raw_payload_hash`` is the hex SHA-256 of the canonicalised JSON
  payload. The canonicalisation (sorted keys, compact separators, UTF-8)
  matches :func:`invest_pipeline.adapters.cifang.adapter._canonical_payload_hash`
  so digest comparisons across adapters stay deterministic.
- Every textual / structured field is preserved verbatim except for the
  ``_redacted_fields`` allow-list. The adapter scrubs any literal token
  substring before populating the model, mirroring
  :func:`invest_pipeline.adapters.cifang.client._scrub_token`.
- No model imports ``httpx``; the client owns the transport so the
  models stay testable with plain Python fixtures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps as _json_dumps
from typing import Any


def _canonical_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 of a JSON-compatible payload.

    Mirrors :func:`invest_pipeline.adapters.cifang.adapter._canonical_payload_hash`
    so digests are comparable across adapters: sorted keys, compact
    separators, UTF-8.
    """

    text = _json_dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class QuickTinyMcpToolDescriptor:
    """A single entry from the MCP ``tools/list`` response.

    The MCP spec exposes ``name`` / ``description`` / ``inputSchema``;
    QuickTiny returns a flat string ``description`` plus an optional
    schema dict. The dataclass is the minimum surface the application
    layer needs to advertise tool availability (research_only feature
    discovery).
    """

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuickTinyMcpToolListResult:
    """Result of a ``tools/list`` MCP call.

    ``tools`` is the ordered tuple returned by the server; ``raw_payload``
    is the decoded JSON ``result`` block from the JSON-RPC envelope so
    callers can introspect the un-mapped tool metadata without losing
    fidelity. ``raw_payload_hash`` carries the canonical SHA-256 of that
    payload for evidence rows.
    """

    tools: tuple[QuickTinyMcpToolDescriptor, ...]
    raw_payload: Mapping[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class QuickTinyMcpToolCallResult:
    """Result of a ``tools/call`` MCP invocation.

    The MCP spec returns a ``content`` array plus optional ``isError`` /
    structured ``data``. QuickTiny's ``etf_market`` and ``index_market``
    tools return a single JSON object so the adapter collapses the array
    into a dict; the raw payload is preserved for evidence hashing.

    ``is_error`` reflects the MCP ``isError`` flag so the adapter can
    raise the appropriate :class:`ProviderError` subclass without
    parsing free text. ``raw_payload_hash`` is the canonical SHA-256 of
    the decoded ``result`` block.
    """

    tool_name: str
    content: Mapping[str, Any]
    is_error: bool
    raw_payload: Mapping[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class QuickTinyMcpResponse:
    """A single successful MCP HTTP exchange.

    Mirrors :class:`invest_pipeline.adapters.cifang.client.CifangResponse`
    in shape (request URL, request params, raw payload, raw payload
    hash) so the two adapters' evidence rows stay interchangeable. The
    dataclass is intentionally generic — the adapter maps it into
    either :class:`QuickTinyMcpToolListResult` or
    :class:`QuickTinyMcpToolCallResult` based on the MCP method.
    """

    request_url: str
    request_params: tuple[tuple[str, str], ...]
    raw_payload: Mapping[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class QuickTinyMcpMarketSnapshot:
    """Normalised ``etf_market`` / ``index_market`` tool-call output.

    QuickTiny returns a single JSON object whose shape varies by query
    (search / snapshot / rank). The adapter cannot map the response to
    :class:`invest_domain.market_data.models.DailyBar` (PR-03 scope) so
    this dataclass is the research / market-snapshot replacement: a
    frozen, hashable record that carries the provider-native symbol,
    name, exchange, latest close, latest trade date, change fields and
    any auxiliary attributes the upstream payload provided.

    Optional fields are explicit ``None`` rather than omitted so the
    canonical hash reflects the *full* upstream contract; the dataclass
    is fully initialised from the upstream response.
    """

    symbol: str
    name: str
    exchange: str
    instrument_kind: str
    latest_close: float | None
    latest_trade_date: str | None
    change_percent: float | None
    change_amount: float | None
    volume: float | None
    turnover: float | None
    extra: Mapping[str, Any]
    raw_payload_hash: str


def normalise_market_snapshot(
    *,
    raw_payload: Mapping[str, Any],
    raw_payload_hash: str,
    instrument_kind: str,
) -> QuickTinyMcpMarketSnapshot:
    """Translate a single ``etf_market`` / ``index_market`` record.

    The provider returns a flat object with mixed types; this helper
    applies the documented field aliases, coerces numerics safely and
    keeps the residual keys under ``extra`` so a future tool
    enhancement (matrix §9.2 mentions rank / search / snapshot /
    minute / daily) does not break the dataclass.

    ``instrument_kind`` is asserted by the caller (``"etf"`` or
    ``"index"``) so the resulting record is self-describing for
    downstream evidence consumers. ``raw_payload_hash`` is propagated
    verbatim from the envelope so evidence rows can cross-reference the
    upstream response without re-hashing.
    """

    def _opt_float(key: str) -> float | None:
        value = raw_payload.get(key)
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", ""))
            except ValueError:
                return None
        return None

    def _opt_str(key: str) -> str | None:
        value = raw_payload.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value or None
        return str(value)

    symbol = _opt_str("symbol") or _opt_str("code") or ""
    name = _opt_str("name") or ""
    exchange = _opt_str("exchange") or ""
    known_keys = {
        "symbol",
        "code",
        "name",
        "exchange",
        "latest_close",
        "close",
        "price",
        "trade_date",
        "date",
        "change_percent",
        "change_pct",
        "pct_change",
        "change",
        "change_amount",
        "change_amt",
        "volume",
        "vol",
        "turnover",
        "amount",
    }
    extra: dict[str, Any] = {
        key: value
        for key, value in raw_payload.items()
        if key not in known_keys
    }
    # ``latest_close`` accepts either the documented
    # ``latest_close`` / ``close`` alias or the ``price`` alias so a
    # future tool enhancement cannot silently break the dataclass.
    latest_close = _opt_float("latest_close")
    if latest_close is None:
        latest_close = _opt_float("close")
    if latest_close is None:
        latest_close = _opt_float("price")
    latest_trade_date = _opt_str("latest_trade_date")
    if latest_trade_date is None:
        latest_trade_date = _opt_str("trade_date")
    if latest_trade_date is None:
        latest_trade_date = _opt_str("date")
    change_percent = _opt_float("change_percent")
    if change_percent is None:
        change_percent = _opt_float("change_pct")
    if change_percent is None:
        change_percent = _opt_float("pct_change")
    change_amount = _opt_float("change_amount")
    if change_amount is None:
        change_amount = _opt_float("change_amt")
    if change_amount is None:
        change_amount = _opt_float("change")
    volume = _opt_float("volume")
    if volume is None:
        volume = _opt_float("vol")
    turnover = _opt_float("turnover")
    if turnover is None:
        turnover = _opt_float("amount")
    return QuickTinyMcpMarketSnapshot(
        symbol=symbol,
        name=name,
        exchange=exchange,
        instrument_kind=instrument_kind,
        latest_close=latest_close,
        latest_trade_date=latest_trade_date,
        change_percent=change_percent,
        change_amount=change_amount,
        volume=volume,
        turnover=turnover,
        extra=extra,
        raw_payload_hash=raw_payload_hash,
    )


def hash_market_snapshot_records(
    records: Sequence[QuickTinyMcpMarketSnapshot],
) -> str:
    """Return a deterministic hash of an ordered ``records`` collection.

    The helper exists so a downstream evidence row can fingerprint the
    full batch of snapshots without depending on Python's default
    ``repr`` (which would change the moment a future maintainer adds a
    field). Records are serialised via :func:`_canonical_payload_hash`
    after :func:`dataclasses.asdict` so the digest reflects the entire
    dataclass surface.
    """

    payload = [record_to_mapping(record) for record in records]
    return _canonical_payload_hash(payload)


def record_to_mapping(
    record: QuickTinyMcpMarketSnapshot,
) -> dict[str, Any]:
    """Return a JSON-compatible dict view of a market snapshot record.

    The mapping is used both by :func:`hash_market_snapshot_records` and
    by adapter-level evidence persistence; ``extra`` is preserved as a
    dict so nested structures round-trip cleanly.
    """

    return {
        "symbol": record.symbol,
        "name": record.name,
        "exchange": record.exchange,
        "instrument_kind": record.instrument_kind,
        "latest_close": record.latest_close,
        "latest_trade_date": record.latest_trade_date,
        "change_percent": record.change_percent,
        "change_amount": record.change_amount,
        "volume": record.volume,
        "turnover": record.turnover,
        "extra": dict(record.extra),
        "raw_payload_hash": record.raw_payload_hash,
    }


__all__ = [
    "QuickTinyMcpMarketSnapshot",
    "QuickTinyMcpResponse",
    "QuickTinyMcpToolCallResult",
    "QuickTinyMcpToolDescriptor",
    "QuickTinyMcpToolListResult",
    "hash_market_snapshot_records",
    "normalise_market_snapshot",
    "record_to_mapping",
]