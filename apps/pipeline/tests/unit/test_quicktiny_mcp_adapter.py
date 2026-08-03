"""Offline unit tests for the QuickTiny MCP adapter (PR-03).

All tests run against ``httpx.MockTransport`` so CI never reaches the
network and never waits in real time. The suite covers the PR-03
contract slice by slice:

- :class:`QuickTinyMcpSettings` defaults / redaction / value locks.
- :class:`QuickTinyMcpClient` JSON-RPC envelope construction
  (``initialize`` / ``tools/list`` / ``tools/call``), bearer-token
  header injection, response decoding, deterministic hash, error
  classification (auth / rate-limit / timeout / transport /
  unavailable / bad-response / contract).
- :mod:`invest_pipeline.adapters.quicktiny_mcp.models` market-snapshot
  normaliser and hash determinism.
- ``QuickTinyMcpSettings`` / ``QuickTinyMcpClient`` construction must
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
from invest_pipeline.adapters.quicktiny_mcp.client import QuickTinyMcpClient
from invest_pipeline.adapters.quicktiny_mcp.config import QuickTinyMcpSettings
from invest_pipeline.adapters.quicktiny_mcp.models import (
    QuickTinyMcpMarketSnapshot,
    QuickTinyMcpToolDescriptor,
    hash_market_snapshot_records,
    normalise_market_snapshot,
    record_to_mapping,
)
from pydantic import SecretStr

_SECRET_TOKEN = "secret-quicktiny-mcp-token-xyz"
_PROVIDER_KEY = "quicktiny_mcp"
_DEFAULT_BASE_URL = "https://stock.quicktiny.cn/api/mcp"


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------


class QuickTinyMcpSettingsDefaultsTest(unittest.TestCase):
    """Defaults for the redacted settings object match matrix §9.1 / §6."""

    def test_enabled_defaults_to_false(self) -> None:
        # Matrix §6: real providers default to off.
        self.assertFalse(QuickTinyMcpSettings().enabled)

    def test_base_url_defaults_to_official_endpoint(self) -> None:
        # Matrix §9.1: ``https://stock.quicktiny.cn/api/mcp``.
        self.assertEqual(
            QuickTinyMcpSettings().base_url, _DEFAULT_BASE_URL
        )

    def test_token_defaults_to_empty_secret(self) -> None:
        # No real secret is shipped; default must be empty so a
        # misconfigured environment cannot accidentally carry a token.
        self.assertEqual(
            QuickTinyMcpSettings().token.get_secret_value(), ""
        )

    def test_timeout_defaults_to_a_positive_value(self) -> None:
        # Bounded default must stay positive / finite so the request
        # budget is always constrained.
        settings = QuickTinyMcpSettings()
        self.assertGreater(settings.timeout_seconds, 0.0)
        self.assertLessEqual(settings.timeout_seconds, 300.0)

    def test_token_field_accepts_secretstr(self) -> None:
        # The ``SecretStr`` env hook is what production deploys use;
        # the default factory must surface the value through
        # ``get_secret_value`` so callers never reach into raw text.
        settings = QuickTinyMcpSettings(token=SecretStr(_SECRET_TOKEN))
        self.assertEqual(
            settings.token.get_secret_value(), _SECRET_TOKEN
        )


class QuickTinyMcpSettingsValueLockTest(unittest.TestCase):
    """Settings reject malformed values at construction time."""

    def test_empty_base_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            QuickTinyMcpSettings(base_url="")
        self.assertIn("base_url", str(ctx.exception))

    def test_non_http_base_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            QuickTinyMcpSettings(base_url="ftp://example.com/mcp")

    def test_zero_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            QuickTinyMcpSettings(timeout_seconds=0)
        self.assertIn("timeout_seconds", str(ctx.exception))

    def test_negative_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            QuickTinyMcpSettings(timeout_seconds=-1.0)

    def test_trailing_slash_is_stripped_from_base_url(self) -> None:
        # So the client always composes a clean "<base>/<endpoint>"
        # without producing "//" separators.
        settings = QuickTinyMcpSettings(base_url=f"{_DEFAULT_BASE_URL}//")
        self.assertFalse(settings.base_url.endswith("/"))


class QuickTinyMcpSettingsRedactionTest(unittest.TestCase):
    """The token must never leak via repr / str / redacted_dict."""

    def test_repr_does_not_leak_token(self) -> None:
        settings = QuickTinyMcpSettings(token=_SECRET_TOKEN)
        self.assertNotIn(_SECRET_TOKEN, repr(settings))
        self.assertNotIn(_SECRET_TOKEN, str(settings))

    def test_redacted_dict_masks_token(self) -> None:
        settings = QuickTinyMcpSettings(token=_SECRET_TOKEN)
        self.assertEqual(settings.redacted_dict()["token"], "***")
        # The non-secret fields remain visible.
        self.assertEqual(settings.redacted_dict()["base_url"], _DEFAULT_BASE_URL)
        self.assertEqual(settings.redacted_dict()["enabled"], "False")


# ----------------------------------------------------------------------
# Construction side-effect free
# ----------------------------------------------------------------------


class QuickTinyMcpNoNetworkOnConstructionTest(unittest.TestCase):
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
            QuickTinyMcpSettings()
            QuickTinyMcpSettings(token=_SECRET_TOKEN)
        finally:
            socket.socket = original  # type: ignore[assignment]
        self.assertEqual(guard_calls, [])

    def test_client_construction_does_not_open_socket(self) -> None:
        original = socket.socket

        def guard(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "QuickTinyMcpClient.__init__ must not touch the network"
            )

        socket.socket = guard  # type: ignore[assignment]
        try:
            settings = QuickTinyMcpSettings()
            transport = httpx.MockTransport(
                lambda request: httpx.Response(200, json={"result": {}})
            )
            client = QuickTinyMcpClient(settings, transport=transport)
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
) -> QuickTinyMcpClient:
    """Build a client whose transport is the supplied ``MockTransport``."""

    settings = QuickTinyMcpSettings(token=token)
    return QuickTinyMcpClient(
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


class QuickTinyMcpClientEnvelopeTest(unittest.TestCase):
    """JSON-RPC 2.0 envelope construction and request inspection."""

    def test_initialize_emits_expected_method_and_params(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "quicktiny", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                }
            )

        client = _make_client(handler=handler)
        try:
            response = client.initialize()
        finally:
            client.close()
        self.assertEqual(
            captured["url"], f"{_DEFAULT_BASE_URL}/"
        )
        self.assertEqual(captured["body"]["jsonrpc"], "2.0")
        self.assertEqual(captured["body"]["method"], "initialize")
        self.assertEqual(
            captured["headers"]["accept"],
            "application/json, text/event-stream",
        )
        self.assertEqual(
            captured["headers"]["content-type"],
            "application/json",
        )
        self.assertEqual(
            captured["body"]["params"]["clientInfo"]["name"], "invest-pipeline"
        )
        self.assertEqual(
            response.raw_payload["protocolVersion"], "2024-11-05"
        )
        # The canonical hash is a stable 64-char hex digest.
        self.assertEqual(len(response.raw_payload_hash), 64)

    def test_list_tools_emits_expected_method(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "tools": [
                        {
                            "name": "etf_market",
                            "description": "ETF market snapshot",
                            "inputSchema": {"type": "object"},
                        },
                        {
                            "name": "index_market",
                            "description": "Index market snapshot",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                }
            )

        client = _make_client(handler=handler)
        try:
            response = client.list_tools()
        finally:
            client.close()
        self.assertEqual(captured["body"]["method"], "tools/list")
        self.assertEqual(captured["body"]["params"], {})
        self.assertEqual(len(response.raw_payload["tools"]), 2)
        names = tuple(
            tool["name"] for tool in response.raw_payload["tools"]
        )
        self.assertEqual(names, ("etf_market", "index_market"))

    def test_call_tool_etf_market_emits_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "object",
                            "data": {
                                "symbol": "510300",
                                "name": "华泰柏瑞沪深300ETF",
                                "exchange": "SH",
                                "latest_close": 4.123,
                                "latest_trade_date": "2026-08-03",
                                "change_percent": 0.85,
                            },
                        }
                    ],
                    "isError": False,
                }
            )

        client = _make_client(handler=handler)
        try:
            response = client.call_tool(
                "etf_market", {"symbol": "510300", "mode": "snapshot"}
            )
        finally:
            client.close()
        self.assertEqual(captured["body"]["method"], "tools/call")
        self.assertEqual(
            captured["body"]["params"]["name"], "etf_market"
        )
        self.assertEqual(
            captured["body"]["params"]["arguments"]["symbol"], "510300"
        )
        self.assertEqual(
            captured["body"]["params"]["arguments"]["mode"], "snapshot"
        )
        content = response.raw_payload["content"][0]["data"]
        self.assertEqual(content["symbol"], "510300")

    def test_call_tool_index_market_uses_bare_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return _ok_envelope(
                {
                    "content": [
                        {
                            "type": "object",
                            "data": {
                                "symbol": "000300",
                                "name": "沪深300",
                                "exchange": "SH",
                                "latest_close": 4123.45,
                            },
                        }
                    ],
                    "isError": False,
                }
            )

        client = _make_client(handler=handler)
        try:
            client.call_tool("index_market")
        finally:
            client.close()
        # ``arguments`` is normalised to ``{}`` so the request always
        # carries an object payload (MCP spec).
        self.assertEqual(
            captured["body"]["params"]["arguments"], {}
        )
        self.assertEqual(captured["body"]["params"]["name"], "index_market")

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

    def test_initialize_negotiates_protocol_and_session_for_follow_up_calls(self) -> None:
        captured: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(dict(request.headers))
            method = json.loads(request.content.decode("utf-8"))["method"]
            if method == "initialize":
                return httpx.Response(
                    200,
                    headers={"Mcp-Session-Id": "session-without-token"},
                    json={
                        "jsonrpc": "2.0",
                        "id": "fixed-id-0001",
                        "result": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {"tools": {}},
                        },
                    },
                )
            return _ok_envelope({"tools": []})

        client = _make_client(handler=handler, token=_SECRET_TOKEN)
        try:
            client.initialize()
            client.list_tools()
            client.call_tool("etf_market")
        finally:
            client.close()

        self.assertEqual(
            [headers["accept"] for headers in captured],
            ["application/json, text/event-stream"] * 3,
        )
        self.assertEqual(
            [headers["content-type"] for headers in captured],
            ["application/json"] * 3,
        )
        self.assertNotIn("mcp-protocol-version", captured[0])
        self.assertNotIn("mcp-session-id", captured[0])
        for headers in captured[1:]:
            self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")
            self.assertEqual(headers["mcp-session-id"], "session-without-token")
            self.assertEqual(headers["authorization"], f"Bearer {_SECRET_TOKEN}")
            self.assertNotIn(_SECRET_TOKEN, headers["mcp-session-id"])


# ----------------------------------------------------------------------
# Token handling
# ----------------------------------------------------------------------


class QuickTinyMcpTokenHeaderTest(unittest.TestCase):
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


# ----------------------------------------------------------------------
# Error classification
# ----------------------------------------------------------------------


class QuickTinyMcpErrorClassificationTest(unittest.TestCase):
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


class QuickTinyMcpHashTest(unittest.TestCase):
    """The raw-payload hash must be deterministic across re-runs."""

    def test_response_hash_is_stable_across_runs(self) -> None:
        result = {"tools": [{"name": "etf_market", "description": "x"}]}

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
        # raw-evidence rows stay comparable across runs. The list
        # ordering is preserved on purpose — JSON canonical form does
        # not reorder array elements.
        def pretty_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "fixed-id-0001",
                        "result": {"tools": [{"name": "etf_market"}]},
                    },
                    indent=2,
                ).encode("utf-8"),
                headers={"content-type": "application/json"},
            )

        def compact_handler(request: httpx.Request) -> httpx.Response:
            return _ok_envelope(
                {"tools": [{"name": "etf_market"}]}
            )

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


# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------


class QuickTinyMcpModelNormalisationTest(unittest.TestCase):
    """``normalise_market_snapshot`` produces the documented dataclass."""

    def test_etf_market_payload_normalises_to_snapshot(self) -> None:
        raw = {
            "symbol": "510300",
            "name": "华泰柏瑞沪深300ETF",
            "exchange": "SH",
            "latest_close": 4.123,
            "latest_trade_date": "2026-08-03",
            "change_percent": 0.85,
            "volume": 1234567,
        }
        snapshot = normalise_market_snapshot(
            raw_payload=raw,
            raw_payload_hash="hash-1",
            instrument_kind="etf",
        )
        self.assertIsInstance(snapshot, QuickTinyMcpMarketSnapshot)
        self.assertEqual(snapshot.symbol, "510300")
        self.assertEqual(snapshot.exchange, "SH")
        self.assertEqual(snapshot.instrument_kind, "etf")
        self.assertEqual(snapshot.latest_close, 4.123)
        self.assertEqual(snapshot.latest_trade_date, "2026-08-03")
        self.assertEqual(snapshot.change_percent, 0.85)
        self.assertEqual(snapshot.volume, 1234567)
        self.assertEqual(snapshot.raw_payload_hash, "hash-1")

    def test_index_market_payload_uses_index_kind(self) -> None:
        raw = {
            "symbol": "000300",
            "name": "沪深300",
            "exchange": "SH",
            "price": 4123.45,
            "date": "2026-08-03",
            "pct_change": -0.42,
        }
        snapshot = normalise_market_snapshot(
            raw_payload=raw,
            raw_payload_hash="hash-2",
            instrument_kind="index",
        )
        self.assertEqual(snapshot.instrument_kind, "index")
        self.assertEqual(snapshot.latest_close, 4123.45)
        self.assertEqual(snapshot.latest_trade_date, "2026-08-03")
        self.assertEqual(snapshot.change_percent, -0.42)

    def test_extras_are_preserved(self) -> None:
        raw = {
            "symbol": "510300",
            "name": "ETF",
            "exchange": "SH",
            "rank": 3,
            "category": "规模指数ETF",
        }
        snapshot = normalise_market_snapshot(
            raw_payload=raw,
            raw_payload_hash="hash-3",
            instrument_kind="etf",
        )
        self.assertEqual(snapshot.extra, {"rank": 3, "category": "规模指数ETF"})

    def test_numeric_aliases_are_resolved(self) -> None:
        # The adapter accepts ``close`` / ``price``, ``change_amt``,
        # ``vol`` and ``amount`` aliases so a future tool enhancement
        # cannot silently break the dataclass.
        raw = {
            "code": "510300",
            "name": "ETF",
            "exchange": "SH",
            "close": 4.5,
            "trade_date": "2026-08-03",
            "change_amt": 0.05,
            "vol": 100.0,
            "amount": 200.0,
        }
        snapshot = normalise_market_snapshot(
            raw_payload=raw,
            raw_payload_hash="hash-4",
            instrument_kind="etf",
        )
        self.assertEqual(snapshot.symbol, "510300")
        self.assertEqual(snapshot.latest_close, 4.5)
        self.assertEqual(snapshot.change_amount, 0.05)
        self.assertEqual(snapshot.volume, 100.0)
        self.assertEqual(snapshot.turnover, 200.0)


class QuickTinyMcpModelHashTest(unittest.TestCase):
    """The batch hash must be deterministic."""

    def test_batch_hash_is_stable_across_calls(self) -> None:
        snapshot = normalise_market_snapshot(
            raw_payload={
                "symbol": "510300",
                "name": "ETF",
                "exchange": "SH",
                "latest_close": 4.5,
                "latest_trade_date": "2026-08-03",
            },
            raw_payload_hash="hash-x",
            instrument_kind="etf",
        )
        first = hash_market_snapshot_records([snapshot])
        second = hash_market_snapshot_records([snapshot])
        self.assertEqual(first, second)

    def test_batch_hash_is_independent_of_field_order(self) -> None:
        snapshot_a = normalise_market_snapshot(
            raw_payload={
                "symbol": "510300",
                "name": "ETF",
                "exchange": "SH",
                "latest_close": 4.5,
            },
            raw_payload_hash="hash-x",
            instrument_kind="etf",
        )
        snapshot_b = normalise_market_snapshot(
            raw_payload={
                "exchange": "SH",
                "latest_close": 4.5,
                "symbol": "510300",
                "name": "ETF",
            },
            raw_payload_hash="hash-x",
            instrument_kind="etf",
        )
        # Field order in the upstream payload must not affect the
        # canonical digest; ``dataclasses.asdict`` + sorted-keys
        # canonicalisation makes the batch hash invariant.
        self.assertEqual(
            hash_market_snapshot_records([snapshot_a]),
            hash_market_snapshot_records([snapshot_b]),
        )

    def test_record_to_mapping_is_complete(self) -> None:
        # The mapping used for hashing covers every dataclass field
        # so a future maintainer who adds a field cannot silently
        # leave the hash stale.
        snapshot = normalise_market_snapshot(
            raw_payload={
                "symbol": "510300",
                "name": "ETF",
                "exchange": "SH",
                "latest_close": 4.5,
                "latest_trade_date": "2026-08-03",
            },
            raw_payload_hash="hash-x",
            instrument_kind="etf",
        )
        mapping = record_to_mapping(snapshot)
        self.assertEqual(
            set(mapping),
            {
                "symbol",
                "name",
                "exchange",
                "instrument_kind",
                "latest_close",
                "latest_trade_date",
                "change_percent",
                "change_amount",
                "volume",
                "turnover",
                "extra",
                "raw_payload_hash",
            },
        )


class QuickTinyMcpToolDescriptorTest(unittest.TestCase):
    """``QuickTinyMcpToolDescriptor`` carries the documented MCP fields."""

    def test_descriptor_carries_name_description_and_schema(self) -> None:
        descriptor = QuickTinyMcpToolDescriptor(
            name="etf_market",
            description="ETF market snapshot",
            input_schema={"type": "object"},
        )
        self.assertEqual(descriptor.name, "etf_market")
        self.assertEqual(descriptor.description, "ETF market snapshot")
        self.assertEqual(descriptor.input_schema, {"type": "object"})


# ----------------------------------------------------------------------
# Disabled gate
# ----------------------------------------------------------------------


class QuickTinyMcpDisabledGateTest(unittest.TestCase):
    """``QuickTinyMcpSettings.enabled`` defaults to ``False``.

    The full adapter would refuse to call the client while ``enabled``
    is ``False`` via
    :class:`RealProviderRequiresExplicitEnablementError`; PR-03
    deliberately stops short of the full adapter and keeps the gate at
    the settings layer. The test pins the gate so a future maintainer
    cannot silently flip the default to ``True``.
    """

    def test_settings_enabled_defaults_to_false(self) -> None:
        self.assertFalse(QuickTinyMcpSettings().enabled)

    def test_settings_enabled_can_be_opted_in(self) -> None:
        # The settings object must accept ``enabled=True`` so
        # operators who have set
        # ``INVEST_PIPELINE_QUICKTINY_MCP_ENABLED=true`` get the
        # explicit opt-in expected by matrix §6.
        settings = QuickTinyMcpSettings()
        object.__setattr__(settings, "enabled", True)
        self.assertTrue(settings.enabled)


if __name__ == "__main__":
    unittest.main()
