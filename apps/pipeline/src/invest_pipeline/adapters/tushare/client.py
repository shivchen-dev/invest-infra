"""Tushare Pro HTTP client (Phase 1 bounded increment).

Owns all transport concerns for the Tushare Pro adapter:

- Single endpoint (``POST https://api.tushare.pro``) with a JSON body
  of ``{api_name, token, params, fields}``.
- Token lookup at request time only: when ``settings.token`` is empty,
  the client resolves the credential from the centralized secret store.
  the first non-empty / non-comment line. The settings object itself
  never touches the file.
- Bounded timeouts and exponential-backoff retry on transient
  failures (mirrors :mod:`invest_pipeline.adapters.cifang.client`).
- Error classification into the typed categories declared in
  :mod:`invest_pipeline.adapters.errors`. Tushare's own
  ``code != 0`` responses are surfaced as
  :class:`ProviderBadResponseError` with the upstream ``code`` carried
  in the message so operators can route alerts.
- Two ``api_name`` values are supported:
  - ``fund_basic`` -> master data
  - ``fund_daily`` -> daily bars

All side effects (transport, sleep, wall-clock) are
injected so CI never reaches the network and tests can replay time
deterministically. The client never
touches the domain layer; it returns the parsed JSON payload (or
raises a typed error) and lets :mod:`mapper` translate field aliases
into domain objects.

The mapper is intentionally **not** imported here so this module stays
httpx-only; the adapter wires them together.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from typing import Any

import httpx

from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from invest_pipeline.adapters.tushare.config import TushareSettings

_PROVIDER_KEY = "tushare"
_BASE_URL = "https://api.tushare.pro"
_FUND_BASIC_API = "fund_basic"
_FUND_DAILY_API = "fund_daily"
_STOCK_BASIC_API = "stock_basic"
_STOCK_DAILY_API = "daily"
_FUND_DAILY_FIELDS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)
_STOCK_DAILY_FIELDS = (
    "ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"
)
_MAX_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_FAILURE_HTTP_STATUS = frozenset({401, 403})


@dataclass(frozen=True, slots=True)
class TushareResponse:
    """A single successful HTTP exchange.

    ``raw_payload`` is the parsed JSON body the mapper will consume;
    ``raw_payload_hash`` is the hex SHA-256 of the original bytes and
    is intended to populate
    :attr:`invest_domain.market_data.models.ProviderBatch.raw_payload_hash`
    so the raw evidence row stays request-scoped.
    """

    request_url: str
    request_body: dict[str, Any]
    raw_payload: Any
    raw_payload_hash: str


class TushareClient:
    """Thin, injectable HTTP wrapper around the Tushare Pro API.

    Parameters
    ----------
    settings:
        The (redacted) configuration object. ``enabled`` is **not**
        consulted by the client; the adapter refuses to call the
        client while ``enabled=False``. The client is purely a
        transport.
    transport:
        Optional ``httpx.BaseTransport`` (typically a ``MockTransport``
        in tests). When omitted, an ``httpx.Client`` is constructed
        with a 10-second connect / 30-second read timeout.
    sleep:
        Callable used to back off between retry attempts. The default
        is :func:`time.sleep`; tests inject a no-op fake so the suite
        runs instantly.
    max_attempts:
        Upper bound on retry attempts (including the first try). The
        constant defaults to 3 to match the CifangQuant client.
    """

    def __init__(
        self,
        settings: TushareSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        if not isinstance(settings, TushareSettings):
            raise TypeError(
                f"TushareClient requires a TushareSettings instance (got {type(settings).__name__})"
            )
        if max_attempts < 1:
            raise ValueError(f"TushareClient.max_attempts must be >= 1, got {max_attempts}")
        self._settings = settings
        self._sleep: Callable[[float], None] = sleep if sleep is not None else _default_sleep
        self._max_attempts = max_attempts
        # ``connect`` covers DNS / TCP / TLS handshake; ``read`` covers
        # a single socket read so a slow per-day response stays well
        # under the daily-bars budget. ``write`` and ``pool`` remain
        # small because POST JSON bodies are tiny and the connection
        # pool reuses the same socket.
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
        self._client = httpx.Client(
            base_url=_BASE_URL,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": "invest-pipeline/tushare"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying ``httpx.Client`` and release the transport."""

        self._client.close()

    def fetch_fund_basic(self) -> TushareResponse:
        """POST ``api_name=fund_basic`` and return the decoded payload.

        The Tushare ``fund_basic`` endpoint accepts a ``params`` body
        filter; we send an empty ``params`` object so the upstream
        returns its full ETF universe. Fields are left unset so the
        upstream returns its default column set.
        """

        body = {
            "api_name": _FUND_BASIC_API,
            "token": self._resolve_token(),
            "params": {},
            "fields": "",
        }
        return self._post_json(body)

    def fetch_fund_daily(
        self, *, ts_code: str, start_date: date, end_date: date
    ) -> TushareResponse:
        """POST ``api_name=fund_daily`` and return the decoded payload.

        ``ts_code`` is the Tushare-native identifier including the
        ``.SH`` / ``.SZ`` suffix (e.g. ``"510300.SH"``). ``start_date``
        and ``end_date`` are inclusive ISO-8601 dates.
        """

        if not isinstance(ts_code, str) or not ts_code.strip():
            raise ValueError("ts_code must be a non-empty string")
        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        body = {
            "api_name": _FUND_DAILY_API,
            "token": self._resolve_token(),
            "params": {
                "ts_code": ts_code.strip(),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
            "fields": ",".join(_FUND_DAILY_FIELDS),
        }
        return self._post_json(body)

    def fetch_stock_basic(self) -> TushareResponse:
        """Fetch the A-share stock master table from ``stock_basic``."""

        return self._post_json({
            "api_name": _STOCK_BASIC_API,
            "token": self._resolve_token(),
            "params": {"list_status": "L"},
            "fields": "ts_code,symbol,name,area,industry,market,list_date,delist_date,list_status",
        })

    def fetch_stock_daily(
        self, *, ts_code: str, start_date: date, end_date: date
    ) -> TushareResponse:
        """Fetch unadjusted stock daily bars using Tushare's YYYYMMDD dates."""

        if not isinstance(ts_code, str) or not ts_code.strip():
            raise ValueError("ts_code must be a non-empty string")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        return self._post_json({
            "api_name": _STOCK_DAILY_API,
            "token": self._resolve_token(),
            "params": {
                "ts_code": ts_code.strip(),
                "start_date": start_date.strftime("%Y%m%d"),
                "end_date": end_date.strftime("%Y%m%d"),
            },
            "fields": ",".join(_STOCK_DAILY_FIELDS),
        })

    # ------------------------------------------------------------------
    # Internal: token resolution + request + retry
    # ------------------------------------------------------------------

    def _resolve_token(self) -> str:
        """Return the effective token for the current request.

        ``TushareSettings.token`` (the ``INVEST_PIPELINE_TUSHARE_TOKEN``
        env var) wins when non-empty; otherwise the client reads the
        centralized credential lazily. An empty
        result raises :class:`ProviderAuthenticationError` so the
        adapter surfaces a typed failure category rather than silently
        sending an empty ``token`` field to Tushare.

        The token is **never** cached on the client so operators can
        rotate the centralized credential between calls without restarting the
        process.
        """

        token = self._settings.resolved_token()
        if not token:
            raise ProviderAuthenticationError(
                _PROVIDER_KEY,
                "Tushare credential is missing from the explicit setting or "
                "centralized secret store",
            )
        return token

    def _post_json(self, body: dict[str, Any]) -> TushareResponse:
        attempts = 0
        last_error: ProviderError | None = None
        while attempts < self._max_attempts:
            attempts += 1
            try:
                response = self._client.post("/", json=body)
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeoutError(_PROVIDER_KEY, _scrub_body(str(exc), body))
                self._maybe_sleep_backoff(attempts)
                continue
            except httpx.TransportError as exc:
                last_error = _classify_transport_error(exc, body)
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
                body=body,
            )

        assert last_error is not None
        raise last_error

    def _maybe_sleep_backoff(self, attempt_index: int) -> None:
        """Sleep with a small, bounded exponential backoff, **unless**
        this was the final attempt.

        Mirrors :meth:`invest_pipeline.adapters.cifang.client.
        CifangClient._maybe_sleep_backoff`: ``0.05 * 2 ** (attempt_index
        - 1)`` seconds so the total back-off for three attempts stays
        below 0.2 s and CI never pays a measurable wait. Skipping the
        sleep after the final attempt keeps the call deterministic
        when every retry has been exhausted.
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


def _scrub_body(message: str, body: dict[str, Any]) -> str:
    """Replace any literal token substring in ``message`` with ``***``.

    Belt-and-braces redaction for error messages: httpx itself never
    includes the token in exceptions, but a custom transport or a
    wrapped logger could conceivably attach one. The scrubber is
    intentionally a no-op when ``token`` is empty so we do not mangle
    upstream messages in tests / offline mode.
    """

    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
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
        return ProviderRateLimitError(_PROVIDER_KEY, f"HTTP {status_code} (rate limited)")
    if 500 <= status_code < 600:
        return ProviderUnavailableError(_PROVIDER_KEY, f"HTTP {status_code} (server unavailable)")
    # 4xx other than auth — do not retry, do not leak the body.
    return ProviderBadResponseError(_PROVIDER_KEY, f"HTTP {status_code} (unexpected)")


def _classify_transport_error(exc: httpx.TransportError, body: dict[str, Any]) -> ProviderError:
    """Map an ``httpx`` transport exception to the typed Provider error."""

    name = type(exc).__name__
    raw = _scrub_body(str(exc), body)
    return ProviderUnavailableError(
        _PROVIDER_KEY,
        f"transport error ({name}): {raw}",
    )


def _decode_response(
    response: httpx.Response,
    *,
    request_url: str,
    body: dict[str, Any],
) -> TushareResponse:
    """Decode a 2xx response into a :class:`TushareResponse`.

    JSON decoding failures raise
    :class:`invest_pipeline.adapters.errors.ProviderBadResponseError`
    (the adapter maps it to ``ProviderFailureStage.DECODE``). The
    original bytes are hashed for the raw-evidence column; the parsed
    payload is returned untouched for the mapper to validate.
    """

    raw_bytes = response.content
    raw_hash = sha256(raw_bytes).hexdigest()
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"non-JSON response from {_PROVIDER_KEY}: {str(exc)}",
        ) from exc
    # Tushare's own envelope: ``{"code": int, "msg": str, "data": ...}``.
    # A non-zero ``code`` is a typed contract failure, distinct from
    # an HTTP-layer 4xx / 5xx.
    if isinstance(payload, dict) and "code" in payload and payload.get("code") != 0:
        upstream_code = payload.get("code")
        upstream_msg = payload.get("msg", "")
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"Tushare returned code={upstream_code!r} msg={upstream_msg!r}",
        )
    return TushareResponse(
        request_url=request_url,
        request_body=dict(body),
        raw_payload=payload,
        raw_payload_hash=raw_hash,
    )


__all__ = [
    "TushareClient",
    "TushareResponse",
]
