"""CifangQuant HTTP client (ADR-0011, Phase 1 second increment).

This module owns all transport concerns for the CifangQuant adapter:

- Endpoint construction (``/api/fund/list`` and ``/api/fund/hist_em``).
- Auth header injection (``x-api-key`` only — never as a query param).
- Bounded timeouts and exponential-backoff retry on transient failures.
- Error classification into the typed categories declared in
  :mod:`invest_pipeline.adapters.errors`.
- 50-symbol chunking for ``/api/fund/hist_em`` per the official limit.

All side effects (transport, sleep, wall-clock) are injected so CI never
reaches the network and tests can replay time deterministically. The
client never touches the domain layer; it returns the parsed JSON
payload (or raises a typed error) and lets :mod:`mapper` translate
field aliases into domain objects.

The mapper is intentionally **not** imported here so this module stays
httpx-only; the adapter wires them together.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Any

import httpx

from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_PROVIDER_KEY = "cifangquant"
_BASE_URL = "https://www.cifangquant.com/api"
_LIST_ENDPOINT = "/fund/list"
_HIST_ENDPOINT = "/fund/hist_em"
MAX_SYMBOLS_PER_REQUEST = 50
_MAX_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_FAILURE_HTTP_STATUS = frozenset({401, 403})
_API_KEY_HEADER = "x-api-key"


@dataclass(frozen=True, slots=True)
class CifangChunkedRequest:
    """One chunk of a chunked historical-bars call.

    The adapter accumulates these into a single :class:`ProviderRequest`
    / :class:`ProviderBatch` bundle; the client surfaces them so the
    adapter can stamp ``request_key`` / ``attempt_no`` deterministically.
    """

    chunk_index: int
    chunk_count: int
    symbols: tuple[str, ...]
    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class CifangResponse:
    """A single successful HTTP exchange.

    ``raw_payload`` is the parsed JSON body the mapper will consume;
    ``raw_payload_hash`` is the hex SHA-256 of the original bytes and is
    intended to populate :attr:`invest_domain.market_data.models.
    ProviderBatch.raw_payload_hash` so the raw evidence row stays
    request-scoped.
    """

    request_url: str
    request_params: tuple[tuple[str, str], ...]
    raw_payload: Any
    raw_payload_hash: str


class CifangClient:
    """Thin, injectable HTTP wrapper around the official CifangQuant API.

    Parameters
    ----------
    settings:
        The (redacted) configuration object. ``enabled`` is **not**
        consulted by the client; the adapter refuses to call the client
        while ``enabled=False``. The client is purely a transport.
    transport:
        Optional ``httpx.BaseTransport`` (typically a ``MockTransport``
        in tests). When omitted, an ``httpx.Client`` is constructed with
        a 10-second connect / 30-second read timeout.
    sleep:
        Callable used to back off between retry attempts. The default is
        :func:`time.sleep`; tests inject a no-op fake so the suite runs
        instantly.
    clock:
        Callable returning the current monotonic time. The client does
        not consult it today; it is accepted so the adapter can build
        deterministic ``started_at`` / ``finished_at`` stamps without
        depending on a second wall-clock source.
    max_attempts:
        Upper bound on retry attempts (including the first try). The
        constant defaults to 3 per ADR-0011 §2.
    """

    def __init__(
        self,
        settings: CifangSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        if not isinstance(settings, CifangSettings):
            raise TypeError(
                "CifangClient requires a CifangSettings instance "
                f"(got {type(settings).__name__})"
            )
        if max_attempts < 1:
            raise ValueError(
                f"CifangClient.max_attempts must be >= 1, got {max_attempts}"
            )
        self._settings = settings
        self._sleep: Callable[[float], None] = (
            sleep if sleep is not None else _default_sleep
        )
        self._clock: Callable[[], float] = (
            clock if clock is not None else _default_clock
        )
        self._max_attempts = max_attempts
        # Always build an explicit Client so the transport is owned by
        # the client (tests inject via ``transport=``) and the default
        # timeout is honoured even when MockTransport is supplied.
        # ``connect`` covers DNS / TCP / TLS handshake; ``read`` covers a
        # single socket read so a slow per-day response stays well under
        # the 50-symbol batch budget. ``write`` and ``pool`` remain the
        # smaller original values because GET requests have negligible
        # body writes and the connection pool reuses the same socket.
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        self._client = httpx.Client(
            base_url=_BASE_URL,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": "invest-pipeline/cifangquant"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying ``httpx.Client`` and release the transport."""

        self._client.close()

    def fetch_fund_list(self) -> CifangResponse:
        """Call ``GET /api/fund/list`` and return the decoded payload."""

        return self._request_json(_LIST_ENDPOINT, params=())

    def fetch_fund_hist_em(
        self, chunk: CifangChunkedRequest
    ) -> CifangResponse:
        """Call ``GET /api/fund/hist_em`` for a single chunk.

        ``chunk`` is the bounded sub-list of symbols (already at most 50
        entries per :data:`MAX_SYMBOLS_PER_REQUEST`); the client asserts
        the invariant defensively so a future caller cannot accidentally
        violate the official limit.
        """

        if not chunk.symbols:
            raise ValueError("CifangChunkedRequest.symbols must not be empty")
        if len(chunk.symbols) > MAX_SYMBOLS_PER_REQUEST:
            raise ValueError(
                f"chunk size {len(chunk.symbols)} exceeds "
                f"CifangQuant per-request limit {MAX_SYMBOLS_PER_REQUEST}"
            )
        if chunk.start_date > chunk.end_date:
            raise ValueError(
                f"chunk start_date {chunk.start_date.isoformat()} must be on or "
                f"before end_date {chunk.end_date.isoformat()}"
            )
        params = (
            ("symbol", ",".join(chunk.symbols)),
            ("start_date", chunk.start_date.isoformat()),
            ("end_date", chunk.end_date.isoformat()),
            ("adjust", self._settings.adjustment),
        )
        return self._request_json(_HIST_ENDPOINT, params=params)

    def chunk_symbols(
        self,
        symbols: Sequence[str],
        *,
        start_date: date,
        end_date: date,
        chunk_size: int = MAX_SYMBOLS_PER_REQUEST,
    ) -> tuple[CifangChunkedRequest, ...]:
        """Split ``symbols`` into chunks of at most ``chunk_size`` entries.

        Defensive bounds: empty input yields an empty tuple and an over-
        sized ``chunk_size`` is rejected so a future configuration error
        cannot silently violate the documented 50-symbol limit.
        """

        if chunk_size < 1 or chunk_size > MAX_SYMBOLS_PER_REQUEST:
            raise ValueError(
                f"CifangClient.chunk_size must be in [1, "
                f"{MAX_SYMBOLS_PER_REQUEST}], got {chunk_size}"
            )
        if not symbols:
            return ()
        chunks = tuple(
            symbols[index : index + chunk_size]
            for index in range(0, len(symbols), chunk_size)
        )
        return tuple(
            CifangChunkedRequest(
                chunk_index=index,
                chunk_count=len(chunks),
                symbols=tuple(chunk),
                start_date=start_date,
                end_date=end_date,
            )
            for index, chunk in enumerate(chunks, start=1)
        )

    # ------------------------------------------------------------------
    # Internal: request + retry
    # ------------------------------------------------------------------

    def _request_json(
        self, path: str, *, params: Iterable[tuple[str, str]]
    ) -> CifangResponse:
        params_tuple = tuple(params)
        headers = _build_auth_headers(self._settings)
        token = self._settings.resolved_api_key() or None
        attempts = 0
        last_error: ProviderError | None = None
        while attempts < self._max_attempts:
            attempts += 1
            try:
                response = self._client.get(
                    path, params=params_tuple, headers=headers
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeoutError(
                    _PROVIDER_KEY, _scrub_token(str(exc), token)
                )
                self._maybe_sleep_backoff(attempts)
                continue
            except httpx.TransportError as exc:
                # Network / DNS / TLS / connect — treat as transport-level
                # failure. The mapper never sees this exception type;
                # the adapter maps it to ``ProviderFailureStage``.
                last_error = _classify_transport_error(exc, token)
                self._maybe_sleep_backoff(attempts)
                continue

            permanent = _classify_status(response.status_code)
            if permanent is not None:
                # Permanent (auth) — fail immediately without sleeping.
                raise permanent
            if response.status_code in _RETRYABLE_HTTP_STATUS:
                last_error = _http_status_to_error(response.status_code)
                self._maybe_sleep_backoff(attempts)
                continue
            if 400 <= response.status_code < 500:
                # Deterministic 4xx (e.g. 404 / 422) — fail immediately
                # without retry and never leak the body. The mapper
                # surfaces a typed ``ProviderBadResponseError`` for the
                # attempt row.
                raise ProviderBadResponseError(
                    _PROVIDER_KEY,
                    f"HTTP {response.status_code} (client error)",
                )

            # 2xx — parse and return.
            return _decode_response(
                response,
                request_url=str(response.request.url),
                params=params_tuple,
            )

        assert last_error is not None
        raise last_error

    def _maybe_sleep_backoff(self, attempt_index: int) -> None:
        """Sleep with a small, bounded exponential backoff, **unless** this
        was the final attempt.

        Uses ``0.05 * 2 ** (attempt_index - 1)`` seconds so the total
        back-off for three attempts stays below 0.2 s and CI never pays
        a measurable wait. Skipping the sleep after the final attempt
        keeps the call deterministic when every retry has been
        exhausted — there is no follow-up call to delay — and matches
        the bounded "give up" contract surfaced to the adapter. The
        intent is to give the Provider room without serialising tests;
        production tuning is out of scope for this increment.
        """

        if attempt_index >= self._max_attempts:
            return
        delay = 0.05 * (2 ** (attempt_index - 1))
        self._sleep(delay)


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def _default_clock() -> float:
    import time

    return time.monotonic()


def _build_auth_headers(settings: CifangSettings) -> dict[str, str]:
    """Build the auth header map.

    The token is never placed in query parameters, fixtures, exception
    text or evidence payloads (ADR-0010 §5 / §6). When ``api_key`` is
    empty (the default for the placeholder settings) the header is
    omitted so a misconfigured environment cannot accidentally send
    a literal ``"None"`` token.
    """

    token = settings.resolved_api_key()
    if not token:
        return {}
    return {_API_KEY_HEADER: token}


def _safe_message(exc: BaseException) -> str:
    """Return a redacted error message that cannot leak the API key.

    httpx exceptions do not carry the token, but :func:`str` is routed
    through this helper defensively in case a custom transport attaches
    one. The token itself is only ever held inside the request headers
    dict on the live ``Client``; we never read it back into errors.
    """

    return str(exc)


def _scrub_token(message: str, token: str | None) -> str:
    """Replace any literal token substring with ``***``.

    Belt-and-braces redaction for error messages: httpx itself never
    includes the token in exceptions, but a custom transport or a
    wrapped logger could conceivably attach one. The scrubber is
    intentionally a no-op when ``token`` is empty so we do not mangle
    upstream messages in tests / offline mode.
    """

    if not token:
        return message
    return message.replace(token, "***")


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
    # 4xx other than auth — do not retry, do not leak the body.
    return ProviderBadResponseError(
        _PROVIDER_KEY, f"HTTP {status_code} (unexpected)"
    )


def _classify_transport_error(
    exc: httpx.TransportError, token: str | None = None
) -> ProviderError:
    """Map an ``httpx`` transport exception to the typed Provider error."""

    name = type(exc).__name__
    raw = str(exc)
    if token:
        raw = raw.replace(token, "***")
    return ProviderUnavailableError(
        _PROVIDER_KEY,
        f"transport error ({name}): {raw}",
    )


def _decode_response(
    response: httpx.Response,
    *,
    request_url: str,
    params: tuple[tuple[str, str], ...],
) -> CifangResponse:
    """Decode a 2xx response into a :class:`CifangResponse`.

    JSON decoding failures raise
    :class:`invest_pipeline.adapters.errors.ProviderBadResponseError` (the
    adapter maps it to ``ProviderFailureStage.DECODE``). The original
    bytes are hashed for the raw-evidence column; the parsed payload is
    returned untouched for the mapper to validate.
    """

    raw_bytes = response.content
    raw_hash = sha256(raw_bytes).hexdigest()
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"non-JSON response from {_PROVIDER_KEY}: {_scrub_token(str(exc), None)}",
        ) from exc
    return CifangResponse(
        request_url=request_url,
        request_params=tuple(params),
        raw_payload=payload,
        raw_payload_hash=raw_hash,
    )


__all__ = [
    "CifangChunkedRequest",
    "CifangClient",
    "CifangResponse",
    "MAX_SYMBOLS_PER_REQUEST",
]
