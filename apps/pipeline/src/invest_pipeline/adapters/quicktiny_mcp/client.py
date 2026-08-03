"""QuickTiny MCP HTTP / JSON-RPC client (PR-03, matrix §9.1 / §9.2).

This module owns all transport concerns for the QuickTiny MCP adapter:

- JSON-RPC 2.0 envelope construction (``initialize`` / ``tools/list``
  / ``tools/call``) per the official MCP spec.
- Bearer-token injection via the ``Authorization`` header — never as a
  query parameter.
- Bounded request budget via an ``httpx.Timeout`` derived from
  :attr:`QuickTinyMcpSettings.timeout_seconds`.
- Error classification into the typed categories declared in
  :mod:`invest_pipeline.adapters.errors` (auth, rate limit, timeout,
  unavailable, bad response, contract).
- A token-redaction scrubber applied to every error message before it
  leaves the client, mirroring
  :func:`invest_pipeline.adapters.cifang.client._scrub_token`.

All transport side effects are injected so CI never reaches the
network. The client never touches the domain layer; it returns a
:class:`QuickTinyMcpResponse` (or raises a typed error) and lets the
adapter map JSON-RPC results into read-only market-snapshot records.

The adapter (intentionally not implemented in PR-03) owns the
disabled-by-default gate (``RealProviderRequiresExplicitEnablementError``)
so the client itself stays a thin transport.
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
from invest_pipeline.adapters.quicktiny_mcp.config import QuickTinyMcpSettings
from invest_pipeline.adapters.quicktiny_mcp.models import QuickTinyMcpResponse

_PROVIDER_KEY = "quicktiny_mcp"
_AUTH_HEADER = "Authorization"
_AUTH_SCHEME = "Bearer"
_DEFAULT_TIMEOUT = 30.0
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_FAILURE_HTTP_STATUS = frozenset({401, 403})
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


class QuickTinyMcpClient:
    """Thin, injectable HTTP wrapper around the official QuickTiny MCP endpoint.

    Parameters
    ----------
    settings:
        The (redacted) configuration object. ``enabled`` is **not**
        consulted by the client; the adapter refuses to call the
        client while ``enabled=False``. The client is purely a
        transport.
    transport:
        Optional ``httpx.BaseTransport`` (typically a ``MockTransport``
        in tests). When omitted, an ``httpx.Client`` is constructed with
        a bounded timeout derived from
        :attr:`QuickTinyMcpSettings.timeout_seconds`.
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
        settings: QuickTinyMcpSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        id_factory: Callable[[], str] | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        if not isinstance(settings, QuickTinyMcpSettings):
            raise TypeError(
                "QuickTinyMcpClient requires a QuickTinyMcpSettings "
                f"instance (got {type(settings).__name__})"
            )
        if max_attempts < 1:
            raise ValueError(
                f"QuickTinyMcpClient.max_attempts must be >= 1, "
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
            headers={"User-Agent": "invest-pipeline/quicktiny_mcp"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying ``httpx.Client`` and release the transport."""

        self._client.close()

    def initialize(self) -> QuickTinyMcpResponse:
        """Send the MCP ``initialize`` request and return the raw response.

        The result carries the server's ``protocolVersion``,
        ``serverInfo`` and ``capabilities``. PR-03 does not validate
        those fields — the adapter only needs the call to succeed so a
        stale token / network failure surfaces before any tool call.
        """

        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "invest-pipeline", "version": "0.1.0"},
        }
        return self._send_rpc("initialize", params=params)

    def list_tools(self) -> QuickTinyMcpResponse:
        """Send the MCP ``tools/list`` request and return the raw response."""

        return self._send_rpc("tools/list", params={})

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> QuickTinyMcpResponse:
        """Send the MCP ``tools/call`` request and return the raw response.

        ``name`` is the tool identifier exposed by ``tools/list`` (e.g.
        ``"etf_market"`` / ``"index_market"``). ``arguments`` is the
        JSON object forwarded verbatim to the server; an empty / ``None``
        value is normalised to ``{}`` so the request always carries an
        object payload.
        """

        if not isinstance(name, str) or not name:
            raise ValueError("tool name must be a non-empty string")
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        return self._send_rpc("tools/call", params=params)

    # ------------------------------------------------------------------
    # Internal: JSON-RPC envelope + retry
    # ------------------------------------------------------------------

    def _send_rpc(
        self,
        method: str,
        *,
        params: Mapping[str, Any],
    ) -> QuickTinyMcpResponse:
        payload = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._id_factory(),
            "method": method,
            "params": dict(params),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = _build_auth_headers(self._settings)
        token = self._settings.token.get_secret_value() or None
        attempts = 0
        last_error: ProviderError | None = None
        while attempts < self._max_attempts:
            attempts += 1
            try:
                response = self._client.post(
                    "", content=body, headers=headers
                )
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
                continue
            if 400 <= response.status_code < 500:
                raise ProviderBadResponseError(
                    _PROVIDER_KEY,
                    f"HTTP {response.status_code} (client error)",
                )

            return _decode_response(
                response,
                request_url=str(response.request.url),
            )

        assert last_error is not None
        raise last_error


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _default_id_factory() -> str:
    return uuid4().hex


def _build_auth_headers(settings: QuickTinyMcpSettings) -> dict[str, str]:
    """Build the bearer-token header map.

    The token is never placed in query parameters, fixtures, exception
    text or evidence payloads (ADR-0010 §5 / §6). When ``token`` is
    empty (the default for the placeholder settings) the header is
    omitted so a misconfigured environment cannot accidentally send a
    literal ``"Bearer None"`` header.
    """

    token = settings.token.get_secret_value()
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


def _decode_response(
    response: httpx.Response,
    *,
    request_url: str,
) -> QuickTinyMcpResponse:
    """Decode a 2xx response into a :class:`QuickTinyMcpResponse`.

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
    return QuickTinyMcpResponse(
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
    # JSON-RPC reserved server-error range (-32099..-32000) and the
    # generic application-error codes (-32000..-32099) are mapped to
    # contract failures because the upstream returned a structured
    # business-level rejection that the adapter cannot recover from.
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
    comparable across adapters. The raw bytes are hashed as well to
    keep an audit trail of the upstream payload even when the decoded
    shape is unchanged.
    """

    canonical = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


__all__ = [
    "QuickTinyMcpClient",
]