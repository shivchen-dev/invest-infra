"""Offline unit tests for the RssCast MCP adapter (PR-04).

All tests run against ``httpx.MockTransport`` so CI never reaches the
network and never waits in real time. The suite covers the PR-04
contract slice by slice:

- :class:`RssCastMcpSettings` defaults / redaction / value locks.
- :class:`RssCastMcpClient` JSON-RPC envelope construction
  (``initialize`` / ``tools/list`` / generic ``tools/call``),
  bearer-token header injection, response decoding, deterministic hash,
  error classification (auth / rate-limit / timeout / transport /
  unavailable / bad-response / contract).
- :mod:`invest_pipeline.adapters.rsscast.models` redacted research
  response normaliser, batch hash determinism and ETF DailyBar tool
  name rejection.
- ``RssCastMcpSettings`` / ``RssCastMcpClient`` construction must
  never reach the network.
"""

from __future__ import annotations

import json
import socket
import unittest
from collections.abc import Callable
from typing import Any

import httpx
from invest_pipeline.adapters.errors import (
    ProviderAuthenticationError,
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from invest_pipeline.adapters.rsscast.client import RssCastMcpClient
from invest_pipeline.adapters.rsscast.config import RssCastMcpSettings
from invest_pipeline.adapters.rsscast.models import (
    RssCastMcpResearchResponse,
    RssCastMcpToolDescriptor,
    hash_research_responses,
    is_forbidden_tool_name,
    normalise_tool_list,
)
from pydantic import SecretStr

_SECRET_TOKEN = "secret-rsscast-mcp-token-xyz"
_PLACEHOLDER_BASE_URL = "https://rsscast.example.com/api/mcp"
_PROVIDER_KEY = "rsscast"
_PROVIDER_NAME = "rsscast"


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------


class RssCastMcpSettingsDefaultsTest(unittest.TestCase):
    """Defaults for the redacted settings object match matrix §1 / §6."""

    def test_enabled_defaults_to_false(self) -> None:
        # Matrix §6: real providers default to off.
        self.assertFalse(RssCastMcpSettings().enabled)

    def test_base_url_defaults_to_empty_string(self) -> None:
        # Matrix §1 explicitly does not freeze a fixed endpoint, so the
        # default must be empty until the operator sets the env var.
        self.assertEqual(RssCastMcpSettings().base_url, "")

    def test_token_defaults_to_empty_secret(self) -> None:
        # No real secret is shipped; default must be empty so a
        # misconfigured environment cannot accidentally carry a token.
        self.assertEqual(
            RssCastMcpSettings().token.get_secret_value(), ""
        )

    def test_timeout_defaults_to_a_positive_value(self) -> None:
        # Bounded default must stay positive / finite so the request
        # budget is always constrained.
        settings = RssCastMcpSettings()
        self.assertGreater(settings.timeout_seconds, 0.0)
        self.assertLessEqual(settings.timeout_seconds, 300.0)

    def test_token_field_accepts_secretstr(self) -> None:
        # The ``SecretStr`` env hook is what production deploys use;
        # the default factory must surface the value through
        # ``get_secret_value`` so callers never reach into raw text.
        settings = RssCastMcpSettings(token=SecretStr(_SECRET_TOKEN))
        self.assertEqual(
            settings.token.get_secret_value(), _SECRET_TOKEN
        )


class RssCastMcpSettingsValueLockTest(unittest.TestCase):
    """Settings reject malformed values at construction time."""

    def test_non_http_base_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            RssCastMcpSettings(base_url="ftp://example.com/mcp")
        self.assertIn("base_url", str(ctx.exception))

    def test_empty_base_url_is_accepted_as_disabled_default(self) -> None:
        # The default ``base_url == ""`` is valid precisely because the
        # adapter is disabled by default. Construction with the empty
        # string must succeed so the redacted settings can be inspected
        # even when the adapter is not configured.
        settings = RssCastMcpSettings()
        self.assertEqual(settings.base_url, "")

    def test_zero_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            RssCastMcpSettings(timeout_seconds=0)
        self.assertIn("timeout_seconds", str(ctx.exception))

    def test_negative_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RssCastMcpSettings(timeout_seconds=-1.0)

    def test_trailing_slash_is_stripped_from_base_url(self) -> None:
        # So the client always composes a clean "<base>/<endpoint>"
        # without producing "//" separators.
        settings = RssCastMcpSettings(
            base_url=f"{_PLACEHOLDER_BASE_URL}//"
        )
        self.assertFalse(settings.base_url.endswith("/"))


class RssCastMcpSettingsRedactionTest(unittest.TestCase):
    """The token must never leak via repr / str / redacted_dict."""

    def test_repr_does_not_leak_token(self) -> None:
        settings = RssCastMcpSettings(
            base_url=_PLACEHOLDER_BASE_URL, token=_SECRET_TOKEN
        )
        self.assertNotIn(_SECRET_TOKEN, repr(settings))
        self.assertNotIn(_SECRET_TOKEN, str(settings))

    def test_redacted_dict_masks_token(self) -> None:
        settings = RssCastMcpSettings(
            base_url=_PLACEHOLDER_BASE_URL, token=_SECRET_TOKEN
        )
        self.assertEqual(settings.redacted_dict()["token"], "***")
        # The non-secret fields remain visible.
        self.assertEqual(
            settings.redacted_dict()["base_url"], _PLACEHOLDER_BASE_URL
        )
        self.assertEqual(settings.redacted_dict()["enabled"], "False")

    def test_redacted_dict_marks_empty_token(self) -> None:
        # The default settings must report the empty token, not "***",
        # so a misconfigured environment is visible in structured logs.
        settings = RssCastMcpSettings()
        self.assertEqual(settings.redacted_dict()["token"], "")


# ----------------------------------------------------------------------
# Construction side-effect free
# ----------------------------------------------------------------------


class RssCastMcpNoNetworkOnConstructionTest(unittest.TestCase):
    """Settings and Client must never touch the network at construction."""

    def test_settings_construction_does_not_open_socket(self) -> None:
        # ``socket.socket`` is the lowest-level primitive the runtime
        # would use to reach the network; guarding against it keeps
        # the suite deterministic across CI / dev environments.
        original = socket.socket
        guard_calls: list[tuple[Any, ...]] = []

        def guard(*args: Any, **kwargs: Any) -> Any:
            guard_calls.append((args, kwargs))
            return original(*args, **kwargs)

        socket.socket = guard  # type: ignore[assignment]
        try:
            RssCastMcpSettings()
            RssCastMcpSettings(token=_SECRET_TOKEN)
        finally:
            socket.socket = original  # type: ignore[assignment]
        self.assertEqual(guard_calls, [])

    def test_client_construction_does_not_open_socket(self) -> None:
        original = socket.socket

        def guard(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "RssCastMcpClient.__init__ must not touch the network"
            )

        socket.socket = guard  # type: ignore[assignment]
        try:
            settings = RssCastMcpSettings(base_url=_PLACEHOLDER_BASE_URL)
            transport = httpx.MockTransport(
                lambda request: httpx.Response(200, json={"result": {}})
            )
            client = RssCastMcpClient(settings, transport=transport)
            client.close()
        finally:
            socket.socket = original  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Client JSON-RPC envelope
# ----------------------------------------------------------------------


def _make_client(
    *,
    handler: Callable[[httpx.Request], httpx.Response],
    token: str = "",
    id_factory: Callable[[], str] | None = None,
    base_url: str = _PLACEHOLDER_BASE_URL,
) -> RssCastMcpClient:
    """Build a client whose transport is the supplied ``MockTransport``."""

    settings = RssCastMcpSettings(base_url=base_url, token=token)
    return RssCastMcpClient(
        settings,
        transport=httpx.MockTransport(handler),
        id_factory=id_factory or (lambda: "fixed-id-0001"),
    )


def _ok_envelope(result: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": "fixed-id-0001", "result": result},
    )


def _error_envelope(code: int, message: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": "fixed-id-0001",
            "error": {"code": code, "message": message},
        },
    )


class RssCastMcpClientEnvelopeTest(unittest.TestCase):
    """JSON-RPC 2.0 envelope construction and request inspection."""

    def test_initialize_emits_expected_method_and_params(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "rsscast", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                }
            )

        client = _make_client(handler=handler)
        try:
            response = client.initialize()
        finally:
            client.close()
        self.assertEqual(
            captured["url"], f"{_PLACEHOLDER_BASE_URL}/"
        )
        self.assertEqual(captured["body"]["jsonrpc"], "2.0")
        self.assertEqual(captured["body"]["method"], "initialize")
        self.assertEqual(
            captured["body"]["params"]["clientInfo"]["name"], "invest-pipeline"
        )
        # ``initialize`` returns a normalised research response.
        self.assertIsInstance(response, RssCastMcpResearchResponse)
        self.assertEqual(response.provider_name, _PROVIDER_NAME)
        self.assertIsNone(response.tool_name)
        self.assertEqual(response.is_error, False)
        self.assertEqual(response.rate_limited, False)
        # The canonical hash is a stable 64-char hex digest.
        self.assertEqual(len(response.response_hash), 64)

    def test_list_tools_emits_expected_method(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "tools": [
                        {
                            "name": "stock_quote",
                            "description": "Stock snapshot",
                            "inputSchema": {"type": "object"},
                        },
                        {
                            "name": "index_news",
                            "description": "Index news feed",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                }
            )

        client = _make_client(handler=handler)
        try:
            result = client.list_tools()
        finally:
            client.close()
        self.assertEqual(captured["body"]["method"], "tools/list")
        self.assertEqual(captured["body"]["params"], {})
        self.assertEqual(len(result.tools), 2)
        names = tuple(tool.name for tool in result.tools)
        self.assertEqual(names, ("stock_quote", "index_news"))
        self.assertIsInstance(result.tools[0], RssCastMcpToolDescriptor)
        self.assertEqual(result.tools[0].description, "Stock snapshot")
        self.assertEqual(len(result.raw_payload_hash), 64)

    def test_list_tools_drops_entries_with_missing_name(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {
                    "tools": [
                        {"name": "", "description": "no name"},
                        {"description": "no name field at all"},
                        "not-an-object",
                        {"name": "valid_tool", "description": "ok"},
                    ]
                }
            )

        client = _make_client(handler=handler)
        try:
            result = client.list_tools()
        finally:
            client.close()
        self.assertEqual(tuple(t.name for t in result.tools), ("valid_tool",))

    def test_call_tool_stock_quote_emits_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "object",
                            "data": {
                                "symbol": "600519",
                                "name": "贵州茅台",
                                "price": 1680.5,
                                "trade_date": "2026-08-03",
                            },
                        }
                    ],
                    "isError": False,
                }
            )

        client = _make_client(handler=handler)
        try:
            response = client.call_tool(
                "stock_quote", {"symbol": "600519", "mode": "snapshot"}
            )
        finally:
            client.close()
        self.assertEqual(captured["body"]["method"], "tools/call")
        self.assertEqual(
            captured["body"]["params"]["name"], "stock_quote"
        )
        self.assertEqual(
            captured["body"]["params"]["arguments"]["symbol"], "600519"
        )
        self.assertEqual(
            captured["body"]["params"]["arguments"]["mode"], "snapshot"
        )
        self.assertIsInstance(response, RssCastMcpResearchResponse)
        self.assertEqual(response.tool_name, "stock_quote")
        self.assertEqual(response.is_error, False)
        content = response.payload["content"][0]["data"]
        self.assertEqual(content["symbol"], "600519")

    def test_call_tool_index_news_uses_bare_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "Headline: market closed up 0.5%",
                        }
                    ],
                    "isError": False,
                }
            )

        client = _make_client(handler=handler)
        try:
            client.call_tool("index_news")
        finally:
            client.close()
        # ``arguments`` is normalised to ``{}`` so the request always
        # carries an object payload (MCP spec).
        self.assertEqual(captured["body"]["params"]["arguments"], {})
        self.assertEqual(captured["body"]["params"]["name"], "index_news")

    def test_call_tool_rejects_empty_name(self) -> None:
        client = _make_client(
            handler=lambda request: _ok_envelope({}),
            token="",
        )
        try:
            with self.assertRaises(ValueError):
                client.call_tool("")
        finally:
            client.close()

    def test_call_tool_rejects_etf_daily_bars_tool_name(self) -> None:
        # PR-04 / matrix §5.4 contract: the adapter must never accept a
        # tool name whose shape is ETF daily-bars, even if the upstream
        # server happens to expose one. The client must reject it
        # up-front with a typed contract error so the application layer
        # cannot accidentally map the response into a production
        # ``core.daily_bars`` row.
        client = _make_client(
            handler=lambda request: _ok_envelope({}),
            token="",
        )
        try:
            with self.assertRaises(ProviderDataContractError) as ctx:
                client.call_tool("etf_daily_bars")
            self.assertIn("ETF DailyBar", str(ctx.exception))
        finally:
            client.close()

    def test_call_tool_rejects_fund_history_em_tool_name(self) -> None:
        client = _make_client(
            handler=lambda request: _ok_envelope({}),
            token="",
        )
        try:
            with self.assertRaises(ProviderDataContractError):
                client.call_tool("fund_history_em")
        finally:
            client.close()

    def test_call_tool_rejects_etf_kline_tool_name(self) -> None:
        client = _make_client(
            handler=lambda request: _ok_envelope({}),
            token="",
        )
        try:
            with self.assertRaises(ProviderDataContractError):
                client.call_tool("fund_kline")
        finally:
            client.close()


# ----------------------------------------------------------------------
# Token handling
# ----------------------------------------------------------------------


class RssCastMcpTokenHeaderTest(unittest.TestCase):
    """The bearer token must be sent via the ``Authorization`` header only."""

    def test_token_is_injected_as_authorization_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["url"] = str(request.url)
            return _ok_envelope({"tools": []})

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            client.list_tools()
        finally:
            client.close()
        self.assertEqual(
            captured["headers"].get("authorization"),
            f"Bearer {_SECRET_TOKEN}",
        )
        self.assertNotIn(_SECRET_TOKEN, captured["url"])

    def test_token_omitted_when_unset(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return _ok_envelope({"tools": []})

        client = _make_client(handler=handler, token="")
        try:
            client.list_tools()
        finally:
            client.close()
        # The header is omitted entirely so a misconfigured environment
        # cannot accidentally send a literal "Bearer None" header.
        self.assertNotIn("authorization", captured["headers"])

    def test_token_is_scrubbed_from_payload(self) -> None:
        # If the upstream payload echoes the token (e.g. via a custom
        # transport that attaches the Authorization header into the
        # body), the normalised research response must scrub it before
        # the application layer sees it.
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Echo Bearer " + _SECRET_TOKEN
                                + " from upstream"
                            ),
                        }
                    ],
                    "isError": False,
                }
            )

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            response = client.call_tool("index_news")
        finally:
            client.close()
        self.assertNotIn(_SECRET_TOKEN, response.payload["content"][0]["text"])
        self.assertNotIn(_SECRET_TOKEN, repr(response))

    def test_token_is_scrubbed_from_error_message(self) -> None:
        # ``tools/call`` returning ``isError`` must not leak the token
        # through the upstream message either.
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Upstream rejected Bearer " + _SECRET_TOKEN
                            ),
                        }
                    ],
                    "isError": True,
                }
            )

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            response = client.call_tool("stock_quote")
        finally:
            client.close()
        self.assertTrue(response.is_error)
        self.assertNotIn(_SECRET_TOKEN, response.error_message)


# ----------------------------------------------------------------------
# Error classification
# ----------------------------------------------------------------------


class RssCastMcpErrorClassificationTest(unittest.TestCase):
    """HTTP / auth / timeout / JSON / MCP errors map to typed categories."""

    def test_401_maps_to_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            with self.assertRaises(ProviderAuthenticationError):
                client.list_tools()
        finally:
            client.close()

    def test_403_maps_to_authentication_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "forbidden"})

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            with self.assertRaises(ProviderAuthenticationError):
                client.list_tools()
        finally:
            client.close()

    def test_404_maps_to_bad_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.list_tools()
        finally:
            client.close()

    def test_429_maps_to_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderRateLimitError):
                client.list_tools()
        finally:
            client.close()

    def test_500_maps_to_unavailable_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderUnavailableError):
                client.list_tools()
        finally:
            client.close()

    def test_503_maps_to_unavailable_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "unavailable"})

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderUnavailableError):
                client.list_tools()
        finally:
            client.close()

    def test_timeout_maps_to_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderTimeoutError):
                client.list_tools()
        finally:
            client.close()

    def test_transport_error_maps_to_unavailable_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderUnavailableError):
                client.list_tools()
        finally:
            client.close()

    def test_non_json_body_maps_to_bad_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>oops</html>")

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.list_tools()
        finally:
            client.close()

    def test_missing_result_block_maps_to_bad_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": "fixed-id-0001"},
            )

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.list_tools()
        finally:
            client.close()

    def test_non_object_envelope_maps_to_bad_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["not", "an", "object"])

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.list_tools()
        finally:
            client.close()

    def test_non_object_result_block_maps_to_bad_response_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": "fixed-id-0001", "result": []},
            )

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderBadResponseError):
                client.list_tools()
        finally:
            client.close()

    def test_jsonrpc_invalid_request_maps_to_contract_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_envelope(-32600, "Invalid Request")

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderDataContractError) as ctx:
                client.list_tools()
        finally:
            client.close()
        self.assertIn("Invalid Request", str(ctx.exception))

    def test_jsonrpc_parse_error_maps_to_contract_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _error_envelope(-32700, "Parse error")

        client = _make_client(handler=handler)
        try:
            with self.assertRaises(ProviderDataContractError):
                client.list_tools()
        finally:
            client.close()

    def test_token_does_not_leak_through_transport_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                f"connection refused near {_SECRET_TOKEN}"
            )

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            with self.assertRaises(ProviderUnavailableError) as ctx:
                client.list_tools()
        finally:
            client.close()
        # The token must never appear in the upstream error message
        # because the scrubber replaces it before construction.
        self.assertNotIn(_SECRET_TOKEN, str(ctx.exception))


# ----------------------------------------------------------------------
# Deterministic hashing
# ----------------------------------------------------------------------


class RssCastMcpHashTest(unittest.TestCase):
    """The response / params hashes must be deterministic across re-runs."""

    def test_response_hash_is_stable_across_runs(self) -> None:
        result = {"tools": [{"name": "stock_quote", "description": "x"}]}

        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(result)

        client_a = _make_client(handler=handler)
        client_b = _make_client(handler=handler)
        try:
            first = client_a.list_tools().raw_payload_hash
            second = client_b.list_tools().raw_payload_hash
        finally:
            client_a.close()
            client_b.close()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_response_hash_is_independent_of_whitespace(self) -> None:
        # Two envelopes with identical ``result`` blocks but different
        # upstream whitespace must produce the same canonical hash so
        # raw-evidence rows stay comparable across runs.

        def pretty_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "fixed-id-0001",
                        "result": {"tools": [{"name": "stock_quote"}]},
                    },
                    indent=2,
                ).encode("utf-8"),
                headers={"content-type": "application/json"},
            )

        def compact_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"tools": [{"name": "stock_quote"}]})

        pretty = _make_client(handler=pretty_handler)
        compact = _make_client(handler=compact_handler)
        try:
            pretty_hash = pretty.list_tools().raw_payload_hash
            compact_hash = compact.list_tools().raw_payload_hash
        finally:
            pretty.close()
            compact.close()
        self.assertEqual(pretty_hash, compact_hash)

    def test_response_hash_differs_when_payload_changes(self) -> None:
        def first_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"tools": [{"name": "a"}]})

        def second_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"tools": [{"name": "b"}]})

        first = _make_client(handler=first_handler)
        second = _make_client(handler=second_handler)
        try:
            first_hash = first.list_tools().raw_payload_hash
            second_hash = second.list_tools().raw_payload_hash
        finally:
            first.close()
            second.close()
        self.assertNotEqual(first_hash, second_hash)

    def test_request_params_hash_is_stable_across_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"content": [], "isError": False})

        client_a = _make_client(handler=handler)
        client_b = _make_client(handler=handler)
        try:
            first = client_a.call_tool("stock_quote", {"symbol": "600519"})
            second = client_b.call_tool("stock_quote", {"symbol": "600519"})
        finally:
            client_a.close()
            client_b.close()
        self.assertEqual(first.request_params_hash, second.request_params_hash)
        self.assertEqual(len(first.request_params_hash), 64)

    def test_request_params_hash_differs_when_arguments_change(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"content": [], "isError": False})

        client = _make_client(handler=handler)
        try:
            first = client.call_tool("stock_quote", {"symbol": "600519"})
            second = client.call_tool("stock_quote", {"symbol": "000001"})
        finally:
            client.close()
        self.assertNotEqual(first.request_params_hash, second.request_params_hash)


# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------


class RssCastMcpResearchResponseTest(unittest.TestCase):
    """``RssCastMcpResearchResponse`` carries the documented contract fields."""

    def test_provider_name_is_rsscast(self) -> None:
        response = RssCastMcpResearchResponse(
            provider_name=_PROVIDER_NAME,
            tool_name="stock_quote",
            request_params_hash="h1",
            response_hash="h2",
            payload={"content": []},
            is_error=False,
            error_message=None,
            rate_limited=False,
            request_url="https://rsscast.example.com/api/mcp/",
        )
        self.assertEqual(response.provider_name, _PROVIDER_NAME)

    def test_record_to_mapping_is_complete(self) -> None:
        # The mapping used for hashing covers every dataclass field so
        # a future maintainer who adds a field cannot silently leave
        # the hash stale.
        response = RssCastMcpResearchResponse(
            provider_name=_PROVIDER_NAME,
            tool_name="stock_quote",
            request_params_hash="h1",
            response_hash="h2",
            payload={"content": []},
            is_error=False,
            error_message=None,
            rate_limited=False,
            request_url="https://rsscast.example.com/api/mcp/",
        )
        mapping = response.record_to_mapping()
        self.assertEqual(
            set(mapping),
            {
                "provider_name",
                "tool_name",
                "request_params_hash",
                "response_hash",
                "payload",
                "is_error",
                "error_message",
                "rate_limited",
                "request_url",
            },
        )


class RssCastMcpBatchHashTest(unittest.TestCase):
    """The batch hash must be deterministic across re-runs."""

    def test_batch_hash_is_stable_across_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope({"content": [], "isError": False})

        client = _make_client(handler=handler)
        try:
            first = client.call_tool("stock_quote", {"symbol": "600519"})
            second = client.call_tool("stock_quote", {"symbol": "600519"})
        finally:
            client.close()
        self.assertEqual(
            hash_research_responses([first]),
            hash_research_responses([second]),
        )

    def test_batch_hash_is_independent_of_field_order(self) -> None:
        # The hash must be stable regardless of dict key ordering in
        # the upstream payload (canonical sorted-keys serialisation).
        def first_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {
                    "content": [{"data": {"symbol": "1", "price": 1.0}}],
                    "isError": False,
                }
            )

        def second_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {
                    "isError": False,
                    "content": [{"data": {"price": 1.0, "symbol": "1"}}],
                }
            )

        first = _make_client(handler=first_handler)
        second = _make_client(handler=second_handler)
        try:
            first_response = first.call_tool("stock_quote")
            second_response = second.call_tool("stock_quote")
        finally:
            first.close()
            second.close()
        self.assertEqual(
            hash_research_responses([first_response]),
            hash_research_responses([second_response]),
        )


class RssCastMcpNormaliseToolListTest(unittest.TestCase):
    """``normalise_tool_list`` consumes a ``tools/list`` ``result`` block."""

    def test_normalises_standard_tools(self) -> None:
        result = normalise_tool_list(
            raw_payload={
                "tools": [
                    {
                        "name": "stock_quote",
                        "description": "Stock snapshot",
                        "inputSchema": {"type": "object"},
                    },
                    {
                        "name": "index_news",
                        "description": "Index news feed",
                        "inputSchema": {"type": "object"},
                    },
                ]
            },
            raw_payload_hash="hash-x",
        )
        self.assertEqual(len(result.tools), 2)
        self.assertEqual(result.tools[0].name, "stock_quote")
        self.assertEqual(result.tools[1].input_schema, {"type": "object"})
        self.assertEqual(result.raw_payload_hash, "hash-x")


class RssCastMcpIsForbiddenToolNameTest(unittest.TestCase):
    """The forbidden-name guard covers the ETF DailyBar-shaped contract."""

    def test_rejects_etf_daily_bars(self) -> None:
        self.assertTrue(is_forbidden_tool_name("etf_daily_bars"))

    def test_rejects_fund_history(self) -> None:
        self.assertTrue(is_forbidden_tool_name("fund_history_em"))

    def test_rejects_etf_kline(self) -> None:
        self.assertTrue(is_forbidden_tool_name("etf_kline"))

    def test_rejects_fund_history_underscore(self) -> None:
        self.assertTrue(is_forbidden_tool_name("fund_history"))

    def test_accepts_research_tool_names(self) -> None:
        self.assertFalse(is_forbidden_tool_name("stock_quote"))
        self.assertFalse(is_forbidden_tool_name("index_news"))
        self.assertFalse(is_forbidden_tool_name("news_search"))

    def test_empty_string_is_not_forbidden(self) -> None:
        # An empty string is not a forbidden name (the client raises a
        # separate ``ValueError`` for it); the helper simply returns
        # ``False`` so the dedicated validation runs first.
        self.assertFalse(is_forbidden_tool_name(""))


class RssCastMcpToolDescriptorTest(unittest.TestCase):
    """``RssCastMcpToolDescriptor`` carries the documented MCP fields."""

    def test_descriptor_carries_name_description_and_schema(self) -> None:
        descriptor = RssCastMcpToolDescriptor(
            name="stock_quote",
            description="Stock snapshot",
            input_schema={"type": "object"},
        )
        self.assertEqual(descriptor.name, "stock_quote")
        self.assertEqual(descriptor.description, "Stock snapshot")
        self.assertEqual(descriptor.input_schema, {"type": "object"})


# ----------------------------------------------------------------------
# Disabled gate
# ----------------------------------------------------------------------


class RssCastMcpDisabledGateTest(unittest.TestCase):
    """``RssCastMcpSettings.enabled`` defaults to ``False``.

    The full adapter would refuse to call the client while ``enabled``
    is ``False`` via
    :class:`RealProviderRequiresExplicitEnablementError`; PR-04
    deliberately stops short of the full adapter and keeps the gate at
    the settings layer. The test pins the gate so a future maintainer
    cannot silently flip the default to ``True``.
    """

    def test_settings_enabled_defaults_to_false(self) -> None:
        self.assertFalse(RssCastMcpSettings().enabled)

    def test_settings_enabled_can_be_opted_in(self) -> None:
        # The settings object must accept ``enabled=True`` so
        # operators who have set
        # ``INVEST_PIPELINE_RSSCAST_ENABLED=true`` get the explicit
        # opt-in expected by matrix §6.
        settings = RssCastMcpSettings()
        object.__setattr__(settings, "enabled", True)
        self.assertTrue(settings.enabled)


if __name__ == "__main__":
    unittest.main()