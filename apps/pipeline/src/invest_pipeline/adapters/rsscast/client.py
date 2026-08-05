"""RssCast MCP HTTP / JSON-RPC client (PR-04, matrix §3 / §5.4).

This module owns all transport concerns for the RssCast MCP adapter:

- JSON-RPC 2.0 envelope construction (``initialize`` / ``tools/list``
  / ``tools/call``) per the official MCP spec.
- Bearer-token injection via the ``Authorization`` header — never as a
  query parameter.
- Bounded request budget via an ``httpx.Timeout`` derived from
  :attr:`RssCastMcpSettings.timeout_seconds`.
- Error classification into the typed categories declared in
  :mod:`invest_pipeline.adapters.errors` (auth, rate limit, timeout,
  unavailable, bad response, contract).
- A token-redaction scrubber applied to every error message and to the
  normalised :class:`RssCastMcpResearchResponse` payload, mirroring
  :func:`invest_pipeline.adapters.cifang.client._scrub_token`.
- Explicit rejection of ETF DailyBar-shaped tool names per the plan
  PR-04 "不实现 ETF DailyBar 适配" constraint; the
  :func:`invest_pipeline.adapters.rsscast.models.is_forbidden_tool_name`
  helper is the canonical guard.

All transport side effects are injected so CI never reaches the
network. The client never touches the domain layer; it returns a
:class:`RssCastMcpResearchResponse` (or raises a typed error) and lets
the application layer decide how to route the normalised research row.

The client itself does not consult ``settings.enabled``; the
adapter (intentionally not implemented in PR-04) would refuse to call
the client while ``enabled=False``. The gate lives at the settings
layer so the client stays a thin transport.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import suppress
from hashlib import sha256
from typing import Any
from uuid import uuid4

import httpx

from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from invest_pipeline.adapters.rsscast.config import RssCastMcpSettings
from invest_pipeline.adapters.rsscast.models import (
    RssCastMcpResearchResponse,
    RssCastMcpResponse,
    RssCastMcpToolListResult,
    is_forbidden_tool_name,
    normalise_tool_list,
)

_PROVIDER_KEY = "rsscast"
_PROVIDER_NAME = "rsscast"
_AUTH_HEADER = "Authorization"
_AUTH_SCHEME = "Bearer"
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_FAILURE_HTTP_STATUS = frozenset({401, 403})
_RATE_LIMIT_HTTP_STATUS = frozenset({429})
_MAX_ATTEMPTS = 1
_JSONRPC_VERSION = "2.0"


def _redact_token(message: str, token: str | None) -> str:
    """Replace any literal token substring with ``"***"``.

    Belt-and-braces redaction for error messages. The token itself is
    only ever held inside the request headers dict on the live
    ``Client``; this scrubber defends against custom transports that
    may echo the ``Authorization`` header into exceptions.
    """

    if not token:
        return message
    scrubbed = message.replace(token, "***")
    bearer = f"{_AUTH_SCHEME} {token}"
    if bearer in scrubbed:
        scrubbed = scrubbed.replace(bearer, f"{_AUTH_SCHEME} ***")
    return scrubbed


class RssCastMcpClient:
    """Thin, injectable HTTP wrapper around the RssCast MCP endpoint.

    Parameters
    ----------
    settings:
        The (redacted) configuration object. ``enabled`` is **not**
        consulted by the client; the adapter refuses to call the
        client while ``enabled=False``. The client is purely a
        transport. ``settings.base_url`` is only required when the
        adapter is actually enabled and reaches the network; the
        client is constructed with the configured value (or the
        empty default per matrix §1) and uses the transport if one
        was injected.
    transport:
        Optional ``httpx.BaseTransport`` (typically a ``MockTransport``
        in tests). When omitted, an ``httpx.Client`` is constructed with
        a bounded timeout derived from
        :attr:`RssCastMcpSettings.timeout_seconds`.
    id_factory:
        Callable returning a fresh JSON-RPC ``id``. The default uses
        :func:`uuid.uuid4`; tests inject a deterministic counter so
        replay assertions stay stable.
    max_attempts:
        Upper bound on retry attempts (including the first try). The
        client is single-attempt by default; tests that need retry
        behaviour can override.
    """

    def __init__(
        self,
        settings: RssCastMcpSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        id_factory: Callable[[], str] | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        if not isinstance(settings, RssCastMcpSettings):
            raise TypeError(
                "RssCastMcpClient requires a RssCastMcpSettings "
                f"instance (got {type(settings).__name__})"
            )
        if max_attempts < 1:
            raise ValueError(
                f"RssCastMcpClient.max_attempts must be >= 1, "
                f"got {max_attempts}"
            )
        self._settings = settings
        self._id_factory: Callable[[], str] = (
            id_factory if id_factory is not None else _default_id_factory
        )
        self._max_attempts = max_attempts
        timeout = httpx.Timeout(
            connect=settings.timeout_seconds,
            read=settings.timeout_seconds,
            write=settings.timeout_seconds,
            pool=settings.timeout_seconds,
        )
        self._client = httpx.Client(
            base_url=settings.base_url,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": "invest-pipeline/rsscast"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying ``httpx.Client`` and release the transport."""

        self._client.close()

    def initialize(self) -> RssCastMcpResearchResponse:
        """Send the MCP ``initialize`` request and return the normalised response.

        The result carries the server's ``protocolVersion``,
        ``serverInfo`` and ``capabilities``. PR-04 does not validate
        those fields — the adapter only needs the call to succeed so a
        stale token / network failure surfaces before any tool call.
        """

        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "invest-pipeline", "version": "0.1.0"},
        }
        response, is_error, error_message, rate_limited = self._send_rpc(
            "initialize", params=params
        )
        return RssCastMcpResearchResponse.from_response(
            response=response,
            settings=self._settings,
            tool_name=None,
            is_error=is_error,
            error_message=error_message,
            rate_limited=rate_limited,
        )

    def list_tools(self) -> RssCastMcpToolListResult:
        """Send the MCP ``tools/list`` request and return the parsed result.

        The raw :class:`RssCastMcpResponse` envelope is decoded and the
        ``tools`` array is normalised into
        :class:`RssCastMcpToolDescriptor` rows. ETF DailyBar-shaped tool
        names are *not* filtered here — the client rejected them
        upstream (via :func:`is_forbidden_tool_name`) so any leakage
        from the upstream ``tools/list`` would surface immediately.
        """

        response, _is_error, _error_message, _rate_limited = self._send_rpc(
            "tools/list", params={}
        )
        return normalise_tool_list(
            raw_payload=response.raw_payload,
            raw_payload_hash=response.raw_payload_hash,
        )

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> RssCastMcpResearchResponse:
        """Send a generic read-only MCP ``tools/call`` request.

        ``name`` is the tool identifier exposed by ``tools/list``. The
        helper is intentionally generic — PR-04 is research / index
        only — so callers (the future adapter layer) can forward any
        stock / index / news tool. ETF DailyBar-shaped tool names are
        rejected up-front via
        :func:`invest_pipeline.adapters.rsscast.models.is_forbidden_tool_name`
        so a misconfigured caller cannot trick the adapter into
        mapping an upstream ``etf_daily_bars``-style response into a
        production ``core.daily_bars`` row.

        ``arguments`` is the JSON object forwarded verbatim to the
        server; an empty / ``None`` value is normalised to ``{}`` so
        the request always carries an object payload. ``arguments``
        is also reflected in the normalised
        :attr:`RssCastMcpResearchResponse.request_params_hash` so two
        calls with the same tool name but different arguments
        produce different audit digests.
        """

        if not isinstance(name, str) or not name:
            raise ValueError("tool name must be a non-empty string")
        if is_forbidden_tool_name(name):
            raise ProviderDataContractError(
                "RSSCAST_ETF_DAILY_BARS_FORBIDDEN",
                f"RssCast MCP refuses ETF DailyBar-shaped tool name "
                f"{name!r} (PR-04 / matrix §5.4)",
                provider_key=_PROVIDER_KEY,
            )
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        response, is_error, error_message, rate_limited = self._send_rpc(
            "tools/call", params=params
        )
        return RssCastMcpResearchResponse.from_response(
            response=response,
            settings=self._settings,
            tool_name=name,
            is_error=is_error,
            error_message=error_message,
            rate_limited=rate_limited,
            arguments=arguments,
        )

    # ------------------------------------------------------------------
    # Internal: JSON-RPC envelope + retry
    # ------------------------------------------------------------------

    def _send_rpc(
        self,
        method: str,
        *,
        params: Mapping[str, Any],
    ) -> tuple[
        RssCastMcpResponse,
        bool,
        str | None,
        bool,
    ]:
        payload = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._id_factory(),
            "method": method,
            "params": dict(params),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = _build_auth_headers(self._settings)
        token = self._settings.resolved_token() or None
        attempts = 0
        last_error: ProviderError | None = None
        while attempts < self._max_attempts:
            attempts += 1
            try:
                response = self._client.post("", content=body, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeoutError(
                    _PROVIDER_KEY, _redact_token(str(exc), token)
                )
                continue
            except httpx.TransportError as exc:
                last_error = _classify_transport_error(exc, token)
                continue

            permanent = _classify_status(response.status_code)
            if permanent is not None:
                raise permanent
            if response.status_code in _RETRYABLE_HTTP_STATUS:
                last_error = _http_status_to_error(response.status_code)
                if response.status_code in _RATE_LIMIT_HTTP_STATUS:
                    raise last_error
                continue
            if 400 <= response.status_code < 500:
                raise ProviderBadResponseError(
                    _PROVIDER_KEY,
                    f"HTTP {response.status_code} (client error)",
                )

            decoded = _decode_response(
                response,
                request_url=str(response.request.url),
            )
            is_error = bool(decoded.raw_payload.get("isError", False))
            error_message = _extract_error_message(decoded.raw_payload)
            return decoded, is_error, error_message, False

        assert last_error is not None
        raise last_error


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _default_id_factory() -> str:
    return uuid4().hex


def _build_auth_headers(settings: RssCastMcpSettings) -> dict[str, str]:
    """Build the bearer-token header map.

    The token is never placed in query parameters, fixtures, exception
    text or evidence payloads (ADR-0010 §5 / §6). When ``token`` is
    empty (the default for the placeholder settings) the header is
    omitted so a misconfigured environment cannot accidentally send a
    literal ``"Bearer None"`` header.
    """

    token = settings.resolved_token()
    if not token:
        return {}
    return {f"{_AUTH_HEADER}": f"{_AUTH_SCHEME} {token}"}


def _classify_status(status_code: int) -> ProviderError | None:
    """Return a permanent error for 4xx auth failures; ``None`` otherwise."""

    if status_code in _AUTH_FAILURE_HTTP_STATUS:
        return ProviderAuthenticationError(
            _PROVIDER_KEY,
            f"HTTP {status_code} (authentication rejected)",
        )
    return None


def _http_status_to_error(status_code: int) -> ProviderError:
    if status_code == 429:
        return ProviderRateLimitError(
            _PROVIDER_KEY, f"HTTP {status_code} (rate limited)"
        )
    if 500 <= status_code < 600:
        return ProviderUnavailableError(
            _PROVIDER_KEY, f"HTTP {status_code} (server unavailable)"
        )
    return ProviderBadResponseError(
        _PROVIDER_KEY, f"HTTP {status_code} (unexpected)"
    )


def _classify_transport_error(
    exc: httpx.TransportError, token: str | None = None
) -> ProviderError:
    """Map an ``httpx`` transport exception to the typed Provider error."""

    name = type(exc).__name__
    raw = _redact_token(str(exc), token)
    return ProviderUnavailableError(
        _PROVIDER_KEY,
        f"transport error ({name}): {raw}",
    )


def _extract_error_message(result: Mapping[str, Any]) -> str | None:
    """Best-effort extract of the MCP ``isError`` ``message`` text.

    The MCP spec lets ``tools/call`` return either an ``isError`` flag
    on its own or alongside a ``content`` array with a textual entry.
    The helper picks the first textual content entry so downstream
    evidence rows can record a human-readable message without
    re-parsing the upstream payload.
    """

    if not result.get("isError"):
        return None
    content = result.get("content")
    if isinstance(content, list):
        for entry in content:
            if isinstance(entry, Mapping):
                text = entry.get("text")
                if isinstance(text, str) and text:
                    return text
                message = entry.get("message")
                if isinstance(message, str) and message:
                    return message
    message = result.get("message")
    if isinstance(message, str) and message:
        return message
    return "MCP tool returned isError"


def _decode_response(
    response: httpx.Response,
    *,
    request_url: str,
) -> RssCastMcpResponse:
    """Decode a 2xx response into a :class:`RssCastMcpResponse`.

    The JSON body must be a JSON-RPC 2.0 envelope with a ``result``
    block. JSON-RPC ``error`` envelopes raise
    :class:`ProviderDataContractError` so the adapter can surface a
    typed failure without re-parsing the upstream message. JSON
    decoding failures raise
    :class:`ProviderBadResponseError`. The ``result`` block is hashed
    canonically so the digest is stable across whitespace differences.
    """

    raw_bytes = response.content
    try:
        envelope = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"non-JSON response from {_PROVIDER_KEY}: {exc}",
        ) from exc

    if not isinstance(envelope, Mapping):
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"non-object envelope from {_PROVIDER_KEY}",
        )
    if "error" in envelope and envelope["error"] is not None:
        raise _envelope_error_to_provider_error(envelope["error"])
    result = envelope.get("result")
    if result is None:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"missing 'result' in JSON-RPC envelope from {_PROVIDER_KEY}",
        )
    if not isinstance(result, Mapping):
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"'result' block must be an object (got {type(result).__name__})",
        )
    raw_hash = _hash_envelope(raw_bytes, result)
    return RssCastMcpResponse(
        request_url=request_url,
        request_params=(),
        raw_payload=result,
        raw_payload_hash=raw_hash,
    )


def _envelope_error_to_provider_error(error: Any) -> ProviderError:
    """Map a JSON-RPC ``error`` block to the typed Provider hierarchy."""

    code = -32000
    message = "unknown JSON-RPC error"
    if isinstance(error, Mapping):
        with suppress(TypeError, ValueError):
            code = int(error.get("code", code))
        raw_message = error.get("message")
        if isinstance(raw_message, str) and raw_message:
            message = raw_message
    elif isinstance(error, str):
        message = error
    if code in {-32700, -32600, -32601, -32602, -32603} or -32100 <= code <= -32000:
        return ProviderDataContractError(
            f"JSONRPC_{code}",
            message,
            provider_key=_PROVIDER_KEY,
        )
    return ProviderBadResponseError(
        _PROVIDER_KEY,
        f"JSON-RPC error {code}: {message}",
    )


def _hash_envelope(
    raw_bytes: bytes, result: Mapping[str, Any]
) -> str:
    """Compute a canonical SHA-256 of the decoded ``result`` block.

    The canonical form mirrors
    :func:`invest_pipeline.adapters.cifang.adapter._canonical_payload_hash`
    (sorted keys, compact separators, UTF-8) so digests stay
    comparable across adapters. ``raw_bytes`` are accepted for parity
    with the QuickTiny client but only the canonical ``result`` digest
    is propagated, since the MCP envelope carries redundant fields
    (e.g. ``jsonrpc`` / ``id``) that do not affect the response.
    """

    canonical = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


__all__ = [
    "RssCastMcpClient",
]


# Re-export the provider name for downstream evidence consumers so a
# future maintainer cannot accidentally rename the canonical string.
_PROVIDER_NAME_PUBLIC = _PROVIDER_NAME
del _PROVIDER_NAME_PUBLIC
