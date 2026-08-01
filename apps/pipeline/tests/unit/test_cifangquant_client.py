"""Offline unit tests for the CifangQuant HTTP client (ADR-0011).

All tests run against ``httpx.MockTransport`` so CI never reaches the
network and never waits in real time (a no-op ``sleep`` is injected).
The suite covers:

- Successful 2xx response decoding (path / params / hash).
- Bounded exponential backoff for transient failures (5xx, 429, transport).
- Immediate fail for ``401`` / ``403`` auth rejections (no retry).
- 50-symbol chunking (documented per-request limit).
- Token redaction in error messages and request inspection.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
from invest_pipeline.adapters.cifang.client import (
    MAX_SYMBOLS_PER_REQUEST,
    CifangChunkedRequest,
    CifangClient,
)
from invest_pipeline.adapters.cifang.config import CifangSettings
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_SECRET_TOKEN = "secret-cifang-token-xyz"
_LEGIT_LIST_PAYLOAD = [
    {
        "symbol": "510300",
        "name": "华泰柏瑞沪深300ETF",
        "exchange": "SH",
        "instrument_type": "ETF",
        "list_date": "2012-05-04",
        "status": "active",
    },
    {
        "symbol": "159919",
        "name": "嘉实沪深300ETF",
        "exchange": "SZ",
        "instrument_type": "ETF",
        "list_date": "2012-05-07",
        "status": "active",
    },
]


def _build_settings(
    *,
    enabled: bool = True,
    api_key: str = "",
    adjustment: str = "none",
) -> CifangSettings:
    """Build a settings instance; ``enabled`` is overridden post-hoc.

    ``enabled`` is normally locked to ``False`` by the test; the real
    adapter enforces the disabled gate. For client-level tests we want
    to exercise the transport, so we mutate the flag after construction
    via ``object.__setattr__``.
    """

    settings = CifangSettings(api_key=api_key, adjustment=adjustment)
    object.__setattr__(settings, "enabled", enabled)
    return settings


class _SleepRecorder:
    """A drop-in replacement for ``time.sleep`` that records delays."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _make_client(
    *,
    handler: Callable[[httpx.Request], httpx.Response],
    api_key: str = "",
    sleep: Callable[[float], None] | None = None,
    max_attempts: int = 3,
) -> tuple[CifangClient, _SleepRecorder]:
    """Build a client whose transport is the supplied ``MockTransport``."""

    sleep_recorder = sleep if isinstance(sleep, _SleepRecorder) else _SleepRecorder()
    transport = httpx.MockTransport(handler)
    settings = _build_settings(api_key=api_key)
    client = CifangClient(
        settings,
        transport=transport,
        sleep=sleep_recorder if sleep is None else sleep,
        max_attempts=max_attempts,
    )
    return client, sleep_recorder


# ----------------------------------------------------------------------
# Successful response
# ----------------------------------------------------------------------


class CifangClientSuccessTest(unittest.TestCase):
    """Happy-path decoding of a single ``/api/fund/list`` exchange."""

    def test_list_request_uses_expected_url_and_headers(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler, api_key=_SECRET_TOKEN)
        try:
            response = client.fetch_fund_list()
        finally:
            client.close()

        self.assertEqual(captured["path"], "/api/fund/list")
        # The token must be sent as the ``x-api-key`` header (ADR-0011 §3),
        # NOT as a query parameter (ADR-0011 §3 / ADR-0010 §5 / §6).
        self.assertEqual(captured["headers"].get("x-api-key"), _SECRET_TOKEN)
        # The token must not appear in the URL itself either.
        self.assertNotIn(_SECRET_TOKEN, str(captured["path"]))
        # The client returns the parsed JSON body for the mapper to consume.
        self.assertEqual(response.raw_payload, _LEGIT_LIST_PAYLOAD)
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_hist_em_request_forwards_symbols_and_dates(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["params"] = dict(request.url.params)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200, json={"adjust": "none", "data": []}
            )

        client, _ = _make_client(handler=handler, api_key=_SECRET_TOKEN)
        try:
            chunk = CifangChunkedRequest(
                chunk_index=1,
                chunk_count=1,
                symbols=("510300", "159919"),
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
            client.fetch_fund_hist_em(chunk)
        finally:
            client.close()

        self.assertEqual(captured["path"], "/api/fund/hist_em")
        params = captured["params"]
        self.assertEqual(params["symbol"], "510300,159919")
        self.assertEqual(params["start_date"], "2026-07-23")
        self.assertEqual(params["end_date"], "2026-07-30")
        self.assertEqual(params["adjust"], "none")
        # The token is in the header only.
        self.assertEqual(captured["headers"].get("x-api-key"), _SECRET_TOKEN)
        # Not in any URL parameter.
        for key, value in params.items():
            self.assertNotEqual(value, _SECRET_TOKEN, f"token in param {key}")

    def test_response_payload_hash_is_stable_across_runs(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler)
        try:
            a = client.fetch_fund_list()
            b = client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(a.raw_payload_hash, b.raw_payload_hash)


# ----------------------------------------------------------------------
# Authentication failures
# ----------------------------------------------------------------------


class CifangClientAuthFailureTest(unittest.TestCase):
    """401 / 403 must fail immediately with no retry."""

    def test_401_returns_authentication_error_without_retry(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(401, json={"error": "unauthorized"})

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            with self.assertRaises(ProviderAuthenticationError) as ctx:
                client.fetch_fund_list()
        finally:
            client.close()
        # Single attempt, no backoff: auth failures must not retry.
        self.assertEqual(attempts, 1)
        self.assertEqual(sleep.calls, [])
        # The message must not leak the token; the type is the canonical
        # failure surface.
        self.assertEqual(ctx.exception.provider_key, "cifangquant")

    def test_403_returns_authentication_error_without_retry(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(403, json={"error": "forbidden"})

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            with self.assertRaises(ProviderAuthenticationError):
                client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(attempts, 1)
        self.assertEqual(sleep.calls, [])


# ----------------------------------------------------------------------
# Retryable failures
# ----------------------------------------------------------------------


class CifangClientRetryTest(unittest.TestCase):
    """Transient 5xx / 429 / transport failures retry then give up."""

    def test_5xx_then_success_retries_with_backoff(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return httpx.Response(503, json={"error": "service unavailable"})
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            response = client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(attempts, 3)
        # Two backoffs (one after the first 503, one after the second).
        self.assertEqual(len(sleep.calls), 2)
        self.assertEqual(sleep.calls[0], 0.05)
        self.assertEqual(sleep.calls[1], 0.10)
        self.assertEqual(response.raw_payload, _LEGIT_LIST_PAYLOAD)

    def test_429_returns_rate_limit_after_max_attempts(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, json={"error": "rate limited"})

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            with self.assertRaises(ProviderRateLimitError):
                client.fetch_fund_list()
        finally:
            client.close()
        # 429 is retried up to max_attempts (3) then surfaces as the
        # typed error so the application service can back off / alert.
        # Two backoffs only — the final attempt must not sleep because
        # there is no follow-up call to delay.
        self.assertEqual(attempts, 3)
        self.assertEqual(len(sleep.calls), 2)
        self.assertEqual(sleep.calls, [0.05, 0.10])

    def test_5xx_then_give_up_after_max_attempts(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(500, json={"error": "boom"})

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            with self.assertRaises(ProviderUnavailableError):
                client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(attempts, 3)
        # Two backoffs only — the final attempt must not sleep because
        # there is no follow-up call to delay.
        self.assertEqual(len(sleep.calls), 2)
        self.assertEqual(sleep.calls, [0.05, 0.10])

    def test_transport_error_then_success(self) -> None:
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("simulated DNS failure")
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            response = client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(attempts, 2)
        self.assertEqual(len(sleep.calls), 1)
        self.assertEqual(response.raw_payload, _LEGIT_LIST_PAYLOAD)

    def test_timeout_then_success(self) -> None:
        """First attempt reads timed out; the second attempt succeeds.

        This guards the backoff timing for the retryable transport path
        and confirms a single transport-level exception does not abort
        the whole call.
        """
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ReadTimeout("simulated read timeout")
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            client.fetch_fund_hist_em(
                CifangChunkedRequest(
                    chunk_index=1,
                    chunk_count=1,
                    symbols=("510300",),
                    start_date=date(2026, 7, 23),
                    end_date=date(2026, 7, 30),
                )
            )
        finally:
            client.close()
        self.assertEqual(attempts, 2)
        self.assertEqual(len(sleep.calls), 1)

    def test_persistent_timeout_raises_timeout_after_max_attempts(
        self,
    ) -> None:
        """When every attempt times out the client surfaces a typed
        :class:`ProviderTimeoutError` after ``max_attempts`` tries
        **without** sleeping after the final attempt."""
        attempts = 0
        sleep = _SleepRecorder()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("simulated read timeout")

        client, _ = _make_client(handler=handler, sleep=sleep)
        try:
            with self.assertRaises(ProviderTimeoutError):
                client.fetch_fund_list()
        finally:
            client.close()
        self.assertEqual(attempts, 3)
        # Two backoffs only — the final attempt must not sleep because
        # there is no follow-up call to delay.
        self.assertEqual(len(sleep.calls), 2)
        self.assertEqual(sleep.calls, [0.05, 0.10])

    def test_final_attempt_never_sleeps_across_retryable_categories(
        self,
    ) -> None:
        """The "no sleep after the final attempt" rule must apply to
        every retryable failure category: timeout, transport, 429, 5xx.

        Each scenario exhausts ``max_attempts``; the sleep recorder must
        only have observed backoffs between attempts (i.e. one fewer
        sleep than attempts).
        """

        def make_timeout_handler(
            request: httpx.Request,
        ) -> httpx.Response:
            raise httpx.ReadTimeout("simulated read timeout")

        def make_transport_handler(
            request: httpx.Request,
        ) -> httpx.Response:
            raise httpx.ConnectError("simulated DNS failure")

        def make_429_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        def make_5xx_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        scenarios = (
            ("timeout", make_timeout_handler),
            ("transport", make_transport_handler),
            ("429", make_429_handler),
            ("5xx", make_5xx_handler),
        )

        for label, handler in scenarios:
            with self.subTest(category=label):
                sleep = _SleepRecorder()
                client, _ = _make_client(handler=handler, sleep=sleep)
                try:
                    with self.assertRaises(ProviderError):
                        client.fetch_fund_list()
                finally:
                    client.close()
                # 3 attempts ⇒ exactly 2 sleeps (between attempts only).
                self.assertEqual(len(sleep.calls), 2)
                self.assertEqual(sleep.calls, [0.05, 0.10])

    def test_default_timeout_matches_documented_budget(self) -> None:
        """The default ``httpx.Timeout`` is ``connect=10s / read=30s``
        with ``write=10s / pool=5s`` retained as reasonable values.

        This guards the production transport budget against accidental
        regression — CI uses ``MockTransport`` so the live timeout is
        never exercised here, but the configuration is the contract.
        """

        settings = _build_settings()
        client = CifangClient(settings, transport=httpx.MockTransport(_ok_handler))
        try:
            timeout = client._client.timeout
            self.assertEqual(timeout.connect, 10.0)
            self.assertEqual(timeout.read, 30.0)
            self.assertEqual(timeout.write, 10.0)
            self.assertEqual(timeout.pool, 5.0)
        finally:
            client.close()

    def test_4xx_other_than_auth_does_not_retry(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(404, json={"error": "not found"})

        client, _ = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.fetch_fund_list()
        finally:
            client.close()
        # 4xx (non-auth) is a deterministic contract failure and must
        # not be retried.
        self.assertEqual(attempts, 1)

    def test_non_json_response_raises_bad_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>oops</html>")

        client, _ = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.fetch_fund_list()
        finally:
            client.close()


# ----------------------------------------------------------------------
# Chunking
# ----------------------------------------------------------------------


class CifangClientChunkingTest(unittest.TestCase):
    """The 50-symbol per-request limit is enforced at the client."""

    def test_chunk_size_matches_documented_limit(self) -> None:
        self.assertEqual(MAX_SYMBOLS_PER_REQUEST, 50)

    def test_chunk_symbols_splits_at_max_symbols(self) -> None:
        settings = _build_settings()
        client = CifangClient(
            settings, transport=httpx.MockTransport(_ok_handler)
        )
        try:
            symbols = [f"5{index:05d}" for index in range(120)]
            chunks = client.chunk_symbols(
                symbols,
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
            self.assertEqual(len(chunks), 3)
            self.assertEqual(len(chunks[0].symbols), 50)
            self.assertEqual(len(chunks[1].symbols), 50)
            self.assertEqual(len(chunks[2].symbols), 20)
            # Indices are 1-based and deterministic.
            self.assertEqual(chunks[0].chunk_index, 1)
            self.assertEqual(chunks[1].chunk_index, 2)
            self.assertEqual(chunks[2].chunk_index, 3)
            self.assertEqual(chunks[2].chunk_count, 3)
            # The union covers the original set with no duplicates.
            flattened = [
                symbol for chunk in chunks for symbol in chunk.symbols
            ]
            self.assertEqual(flattened, symbols)
        finally:
            client.close()

    def test_chunk_symbols_rejects_oversized_chunk_size(self) -> None:
        client = CifangClient(
            _build_settings(), transport=httpx.MockTransport(_ok_handler)
        )
        try:
            with self.assertRaises(ValueError):
                client.chunk_symbols(
                    ["510300"],
                    start_date=date(2026, 7, 23),
                    end_date=date(2026, 7, 30),
                    chunk_size=MAX_SYMBOLS_PER_REQUEST + 1,
                )
        finally:
            client.close()

    def test_chunk_symbols_handles_empty_input(self) -> None:
        client = CifangClient(
            _build_settings(), transport=httpx.MockTransport(_ok_handler)
        )
        try:
            chunks = client.chunk_symbols(
                [],
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
            self.assertEqual(chunks, ())
        finally:
            client.close()


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)


# ----------------------------------------------------------------------
# Secret non-leakage
# ----------------------------------------------------------------------


class CifangClientSecretNonLeakTest(unittest.TestCase):
    """The token must not appear in evidence, query params, or errors."""

    def test_token_does_not_appear_in_request_url(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json=_LEGIT_LIST_PAYLOAD)

        client, _ = _make_client(handler=handler, api_key=_SECRET_TOKEN)
        try:
            client.fetch_fund_list()
        finally:
            client.close()
        self.assertNotIn(_SECRET_TOKEN, captured["url"])

    def test_token_does_not_leak_through_provider_error_message(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"connection refused near {_SECRET_TOKEN}")

        client, _ = _make_client(handler=handler, api_key=_SECRET_TOKEN)
        try:
            with self.assertRaises(ProviderUnavailableError) as ctx:
                client.fetch_fund_list()
        finally:
            client.close()
        # The Provider error type does not retain the upstream message
        # in a form that would leak the token; the canonical type name
        # is the only evidence persisted on the attempt row.
        self.assertNotIn(_SECRET_TOKEN, str(ctx.exception))

    def test_settings_redacted_dict_hides_token(self) -> None:
        settings = _build_settings(api_key=_SECRET_TOKEN)
        self.assertEqual(settings.redacted_dict()["api_key"], "***")


if __name__ == "__main__":
    unittest.main()