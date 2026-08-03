"""RssCast MCP read-only response models (PR-04).

These dataclasses are the *only* shape the RssCast adapter exposes to
the application layer. They are deliberately **not** mapped to
:class:`invest_domain.market_data.models.DailyBar` (PR-04 scope, matrix
§3 / §5.4 / §9): the catalog declares RssCast as ``out_of_scope_for_etf``
with capabilities ``RESEARCH`` and ``INDEX_DAILY_BARS``, and the plan
forbids RssCast responses from becoming production ``core.daily_bars``
rows or from claiming ``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA``.

Design rules:

- Every model is a frozen, ``slots=True`` dataclass so the response
  hashes used by ``ProviderBatch.raw_payload_hash`` remain stable across
  re-runs and accidental mutation is impossible.
- ``request_params_hash`` is the hex SHA-256 of the canonicalised JSON
  ``params`` payload and ``response_hash`` is the hex SHA-256 of the
  canonicalised JSON ``result`` payload. The canonicalisation (sorted
  keys, compact separators, UTF-8) matches
  :func:`invest_pipeline.adapters.cifang.adapter._canonical_payload_hash`
  and :func:`invest_pipeline.adapters.quicktiny_mcp.models._canonical_payload_hash`
  so digest comparisons across adapters stay deterministic.
- The token is scrubbed from every textual / structured field via the
  allow-list pattern documented by ADR-0010 §5 / §6; the model itself
  never holds the secret because the client owns the bearer header.
- No model imports ``httpx``; the client owns the transport so the
  models stay testable with plain Python fixtures.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from json import dumps as _json_dumps
from typing import Any

from invest_pipeline.adapters.rsscast.config import RssCastMcpSettings

_PROVIDER_NAME = "rsscast"

# ETF DailyBar-shaped tool names are explicitly rejected by the client
# before they reach this model (see ``RssCastMcpClient.call_tool``).
# The pattern matches names that combine an ``etf`` / ``fund`` prefix
# with any of the daily-bar / history / kline / bar tokens commonly
# used by upstream ETF data sources (AkShare's ``fund_etf_hist_em``
# family, CifangQuant's ``fund_hist_em`` family, etc.). Generic stock
# / index / news tools that happen to contain a "daily" word (e.g.
# ``daily_snapshot`` for a single instrument) are *not* rejected because
# the prefix anchor ``(?:etf|fund|fund_etf)`` keeps the guard scoped to
# ETF-shaped contracts.
_FORBIDDEN_TOOL_NAME_PATTERN = re.compile(
    r"^(?:etf|fund|fund_etf)[._-].*?(?:daily|history|hist|kline|bar)",
    re.IGNORECASE,
)


def is_forbidden_tool_name(name: str) -> bool:
    """Return ``True`` when ``name`` looks like an ETF DailyBar tool.

    PR-04 is research / index only (matrix §3 / §5.4); the plan forbids
    RssCast responses from becoming production ``core.daily_bars`` rows
    and the catalog declaration explicitly excludes ``ETF_DAILY_BARS``.
    The helper is exposed so the client can reject upstream tools /
    calls that look like ETF daily bars and so tests can assert the
    rejection contract end-to-end.
    """

    if not isinstance(name, str) or not name:
        return False
    return bool(_FORBIDDEN_TOOL_NAME_PATTERN.search(name))


def _canonical_payload_hash(payload: Any) -> str:
    """Return a stable SHA-256 of a JSON-compatible payload.

    Mirrors :func:`invest_pipeline.adapters.cifang.adapter._canonical_payload_hash`
    and
    :func:`invest_pipeline.adapters.quicktiny_mcp.models._canonical_payload_hash`
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


def _scrub_payload(payload: Any, token: str | None) -> Any:
    """Replace any literal token substring inside ``payload`` with ``"***"``.

    The scrubber is recursive so nested dict / list structures cannot
    leak the bearer token via a deep field. ``token`` is empty in the
    default settings, so the helper is a no-op in tests / offline mode
    and only fires when the adapter is actually enabled.
    """

    if not token:
        return payload
    if isinstance(payload, Mapping):
        return {
            key: _scrub_payload(value, token)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        scrubbed = [_scrub_payload(item, token) for item in payload]
        return type(payload)(scrubbed)
    if isinstance(payload, str):
        scrubbed = payload.replace(token, "***")
        bearer = f"Bearer {token}"
        if bearer in scrubbed:
            scrubbed = scrubbed.replace(bearer, "Bearer ***")
        return scrubbed
    return payload


@dataclass(frozen=True, slots=True)
class RssCastMcpResponse:
    """A single successful MCP HTTP exchange.

    Mirrors :class:`invest_pipeline.adapters.quicktiny_mcp.models.QuickTinyMcpResponse`
    in shape (request URL, request params, raw payload, raw payload
    hash) so the two adapters' evidence rows stay interchangeable. The
    dataclass is intentionally generic — the adapter maps it into
    :class:`RssCastMcpResearchResponse` based on the MCP method.
    """

    request_url: str
    request_params: tuple[tuple[str, Any], ...]
    raw_payload: Mapping[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class RssCastMcpToolDescriptor:
    """A single entry from the MCP ``tools/list`` response.

    The MCP spec exposes ``name`` / ``description`` / ``inputSchema``.
    RssCast returns a flat string ``description`` plus an optional
    schema dict; the dataclass is the minimum surface the application
    layer needs to advertise tool availability (research_only feature
    discovery).
    """

    name: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RssCastMcpToolListResult:
    """Result of a ``tools/list`` MCP call.

    ``tools`` is the ordered tuple returned by the server; ``raw_payload``
    is the decoded JSON ``result`` block from the JSON-RPC envelope so
    callers can introspect the un-mapped tool metadata without losing
    fidelity. ``raw_payload_hash`` carries the canonical SHA-256 of that
    payload for evidence rows.
    """

    tools: tuple[RssCastMcpToolDescriptor, ...]
    raw_payload: Mapping[str, Any]
    raw_payload_hash: str


@dataclass(frozen=True, slots=True)
class RssCastMcpResearchResponse:
    """Normalised redacted research response for the RssCast MCP adapter.

    The model is the single normalised shape PR-04 exposes to the
    application layer for ``initialize``, ``tools/list`` and read-only
    ``tools/call`` invocations. The fields cover the audit trail called
    out by the V2 all-data-sources plan §3 ("统一记录工具名、参数哈希、
    响应哈希、错误和限流状态"):

    - ``provider_name`` — stable lower_snake_case provider identifier
      (``"rsscast"``).
    - ``tool_name`` — the MCP tool identifier for ``tools/call``; ``None``
      for ``initialize`` / ``tools/list``.
    - ``request_params_hash`` — canonical SHA-256 of the JSON-RPC
      ``params`` object. Stable across runs and whitespace differences.
    - ``response_hash`` — canonical SHA-256 of the JSON-RPC ``result``
      block. Stable across runs and whitespace differences.
    - ``payload`` — the decoded JSON-RPC ``result`` block, scrubbed of
      any literal token substring so the token cannot leak via repr /
      evidence rows / logs.
    - ``is_error`` — ``True`` when the upstream returned the MCP
      ``isError`` flag (or the JSON-RPC ``error`` envelope).
    - ``error_message`` — human-readable error message; ``None`` on
      success. The text is scrubbed of the token.
    - ``rate_limited`` — ``True`` when the upstream returned HTTP 429;
      downstream evidence rows can short-circuit retries.
    - ``request_url`` — the fully-qualified request URL captured by the
      transport, included for diagnostics.

    The model is frozen / ``slots=True`` so accidental mutation cannot
    break the canonical hash and so accidental token injection into a
    dataclass field is impossible.
    """

    provider_name: str
    tool_name: str | None
    request_params_hash: str
    response_hash: str
    payload: Mapping[str, Any]
    is_error: bool
    error_message: str | None
    rate_limited: bool
    request_url: str

    @classmethod
    def from_response(
        cls,
        *,
        response: RssCastMcpResponse,
        settings: RssCastMcpSettings,
        tool_name: str | None,
        is_error: bool,
        error_message: str | None,
        rate_limited: bool,
        arguments: Mapping[str, Any] | None = None,
    ) -> RssCastMcpResearchResponse:
        """Build a :class:`RssCastMcpResearchResponse` from a raw response.

        The token is scrubbed from both ``payload`` and ``error_message``
        before they reach the dataclass so the secret can never leak
        via repr, evidence rows or log payloads. The ``params`` block is
        normalised from the request side so its hash is independent of
        dict ordering. ``arguments`` is propagated so the
        ``request_params_hash`` reflects the full MCP ``params`` object
        (tool name + arguments) rather than just the tool name.
        """

        token = settings.token.get_secret_value() or None
        params_mapping: dict[str, Any]
        if tool_name is None:
            params_mapping = {}
        else:
            params_mapping = {
                "name": tool_name,
                "arguments": dict(arguments or {}),
            }
        scrubbed_payload = _scrub_payload(response.raw_payload, token)
        scrubbed_message: str | None
        if error_message is None:
            scrubbed_message = None
        elif isinstance(error_message, str):
            scrubbed_message = _scrub_payload(error_message, token)
        else:
            scrubbed_message = str(error_message)
        return cls(
            provider_name=_PROVIDER_NAME,
            tool_name=tool_name,
            request_params_hash=_canonical_payload_hash(params_mapping),
            response_hash=response.raw_payload_hash,
            payload=dict(scrubbed_payload) if isinstance(scrubbed_payload, Mapping) else {},
            is_error=bool(is_error),
            error_message=scrubbed_message,
            rate_limited=bool(rate_limited),
            request_url=response.request_url,
        )

    def record_to_mapping(self) -> dict[str, Any]:
        """Return a JSON-compatible view of the normalised response.

        The mapping is used by downstream evidence rows so every field
        declared above survives the round-trip through the canonical
        SHA-256 (a future maintainer who adds a field cannot silently
        leave the hash stale).
        """

        return {
            "provider_name": self.provider_name,
            "tool_name": self.tool_name,
            "request_params_hash": self.request_params_hash,
            "response_hash": self.response_hash,
            "payload": dict(self.payload),
            "is_error": self.is_error,
            "error_message": self.error_message,
            "rate_limited": self.rate_limited,
            "request_url": self.request_url,
        }


def hash_research_responses(
    responses: Sequence[RssCastMcpResearchResponse],
) -> str:
    """Return a deterministic hash of an ordered ``responses`` collection.

    The helper exists so a downstream evidence row can fingerprint the
    full batch of normalised responses without depending on Python's
    default ``repr`` (which would change the moment a future maintainer
    adds a field). Responses are serialised via
    :func:`record_to_mapping` so the digest reflects the entire
    dataclass surface.
    """

    payload = [response.record_to_mapping() for response in responses]
    return _canonical_payload_hash(payload)


def normalise_tool_list(
    *,
    raw_payload: Mapping[str, Any],
    raw_payload_hash: str,
) -> RssCastMcpToolListResult:
    """Translate a ``tools/list`` ``result`` block into descriptors.

    The provider returns a JSON object with a ``tools`` array; the
    helper applies the documented MCP field aliases and silently drops
    entries whose ``name`` is missing or empty. ETF DailyBar-shaped
    tool names are *not* filtered here — the client rejects them
    upstream so a regression that bypasses the client surfaces
    immediately rather than at evidence-persist time.
    """

    raw_tools = raw_payload.get("tools")
    if not isinstance(raw_tools, list):
        raw_tools = []
    descriptors: list[RssCastMcpToolDescriptor] = []
    for entry in raw_tools:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = entry.get("description")
        if not isinstance(description, str):
            description = ""
        schema = entry.get("inputSchema")
        if not isinstance(schema, Mapping):
            schema = {}
        descriptors.append(
            RssCastMcpToolDescriptor(
                name=name,
                description=description,
                input_schema=dict(schema),
            )
        )
    return RssCastMcpToolListResult(
        tools=tuple(descriptors),
        raw_payload=raw_payload,
        raw_payload_hash=raw_payload_hash,
    )


__all__ = [
    "RssCastMcpResearchResponse",
    "RssCastMcpResponse",
    "RssCastMcpToolDescriptor",
    "RssCastMcpToolListResult",
    "hash_research_responses",
    "is_forbidden_tool_name",
    "normalise_tool_list",
]