"""BaoStock client tests (Slice-1 of PR-08)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from invest_pipeline.adapters.baostock.client import BaostockClient
from invest_pipeline.adapters.baostock.config import BaostockSettings
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderUnavailableError,
)

# ----- stub SDK ----------------------------------------------------------


class _StubResult:
    def __init__(self, rows=None, error_code="0", error_msg=""):
        self._rows = list(rows or [])
        self._idx = 0
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self) -> bool:
        return self._idx < len(self._rows)

    def get_row_data(self) -> tuple:
        row = self._rows[self._idx]
        self._idx += 1
        return row


def _stub_module(rows_per_query=None, error_code="0"):
    state = SimpleNamespace(calls=[], login_count=0, logout_count=0)
    rows_per_query = rows_per_query or {}

    def login():
        state.calls.append(("login", ()))
        state.login_count += 1
        return _StubResult()

    def logout():
        state.calls.append(("logout", ()))
        state.logout_count += 1
        return _StubResult()

    def query_history_k_data_plus(code, **kwargs):
        state.calls.append(("query", code, kwargs))
        return _StubResult(rows_per_query.get(code, []))

    return SimpleNamespace(
        login=login, logout=logout,
        query_history_k_data_plus=query_history_k_data_plus,
        __version__="0.0-test", calls=state.calls,
        login_count=lambda: state.login_count,
        logout_count=lambda: state.logout_count,
    )


def _client_with(rows_per_query=None) -> BaostockClient:
    module = _stub_module(rows_per_query)
    client = BaostockClient(BaostockSettings(), module=module)
    client._test_module = module  # type: ignore[attr-defined]
    return client


def _row(d="2026-01-05", code="sh.510300", op="1.0", hi="1.1", lo="0.95",
         close="1.05", vol="100", amt="105.0"):
    return (d, code, op, hi, lo, close, vol, amt)


# ----- tests --------------------------------------------------------------


class TestLifecycle:
    def test_login_query_logout_lifecycle_single_symbol(self) -> None:
        client = _client_with({"sh.510300": [_row()]})
        response = client.fetch_etf_daily_bars(
            symbols=["sh.510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        module = client._test_module
        assert [c[0] for c in module.calls] == ["login", "query", "logout"]
        assert response.raw_payload[0]["date"] == "2026-01-05"
        assert response.raw_payload[0]["code"] == "sh.510300"

    def test_login_query_logout_lifecycle_multi_symbol(self) -> None:
        client = _client_with(
            {"sh.510300": [_row()], "sz.159901": [_row(code="sz.159901")]}
        )
        client.fetch_etf_daily_bars(
            symbols=["sh.510300", "sz.159901"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        module = client._test_module
        names = [c[0] for c in module.calls]
        assert names == ["login", "query", "query", "logout"]
        assert module.login_count() == 1
        assert module.logout_count() == 1

    def test_logout_failure_does_not_mask_query_result(self) -> None:
        module = _stub_module({"sh.510300": [_row()]})

        def bad_logout():
            raise RuntimeError("logout crashed")
        module.logout = bad_logout

        client = BaostockClient(BaostockSettings(), module=module)
        client._test_module = module  # type: ignore[attr-defined]
        response = client.fetch_etf_daily_bars(
            symbols=["sh.510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert len(response.raw_payload) == 1


class TestInputValidation:
    def test_empty_symbols_raises_value_error(self) -> None:
        client = _client_with({})
        with pytest.raises(ValueError, match="non-empty"):
            client.fetch_etf_daily_bars(
                symbols=[],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

    def test_end_before_start_raises_value_error(self) -> None:
        client = _client_with({})
        with pytest.raises(ValueError, match="on or after"):
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 31), end_date=date(2026, 1, 1),
            )


class TestErrors:
    def test_missing_sdk_raises_provider_unavailable(self) -> None:
        client = BaostockClient(BaostockSettings())
        def _missing():
            raise ProviderUnavailableError("baostock", "baostock SDK not installed")
        client._resolve_module = _missing  # type: ignore[assignment]
        with pytest.raises(ProviderUnavailableError):
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

    def test_query_oserror_raises_unavailable(self) -> None:
        module = _stub_module()
        def boom(*a, **kw):
            raise OSError("connection refused")
        module.query_history_k_data_plus = boom
        client = BaostockClient(BaostockSettings(), module=module)
        with pytest.raises(ProviderUnavailableError):
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

    def test_empty_required_payload_raises_contract_error(self) -> None:
        client = _client_with({})
        with pytest.raises(ProviderDataContractError) as exc:
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )
        assert exc.value.code == "EMPTY_REQUIRED_PAYLOAD"

    def test_malformed_row_length_raises_contract_error(self) -> None:
        client = _client_with({"sh.510300": [("short",)]})
        with pytest.raises(ProviderDataContractError) as exc:
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )
        assert exc.value.code == "MALFORMED_HISTORY_ROW"


class TestCursorProtocol:
    def test_cursor_next_oserror_raises_unavailable(self) -> None:
        class BadResult:
            error_code = "0"
            error_msg = ""

            def next(self):
                raise OSError("socket reset")

        module = _stub_module()
        module.query_history_k_data_plus = lambda **kw: BadResult()
        client = BaostockClient(BaostockSettings(), module=module)
        with pytest.raises(ProviderUnavailableError):
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

    def test_cursor_next_other_exception_raises_bad_response(self) -> None:
        class BadResult:
            error_code = "0"
            error_msg = ""

            def next(self):
                raise RuntimeError("protocol glitch")

        module = _stub_module()
        module.query_history_k_data_plus = lambda **kw: BadResult()
        client = BaostockClient(BaostockSettings(), module=module)
        with pytest.raises(ProviderBadResponseError):
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )

    def test_cursor_post_pagination_nonzero_error_raises_bad_response(self) -> None:
        class FlakyResult:
            error_code = "0"
            error_msg = ""

            def next(self):
                self.error_code = "10001001"
                self.error_msg = "trade calendar unavailable"
                return False

            def get_row_data(self):
                return ()

        module = _stub_module()
        module.query_history_k_data_plus = lambda **kw: FlakyResult()
        client = BaostockClient(BaostockSettings(), module=module)
        with pytest.raises(ProviderBadResponseError) as exc:
            client.fetch_etf_daily_bars(
                symbols=["sh.510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )
        assert "10001001" in str(exc.value)
