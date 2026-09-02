"""BaoStock SDK wrapper (Slice-1 of PR-08).

Lazy-importing wrapper around the optional ``baostock`` SDK.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from types import ModuleType
from typing import Any

from invest_pipeline.adapters.baostock.config import BaostockSettings
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderDataContractError,
    ProviderUnavailableError,
)

_PROVIDER_KEY = "baostock"
_FIELDS = "date,code,open,high,low,close,volume,amount"


@dataclass(frozen=True, slots=True)
class BaostockResponse:
    operation: str
    raw_payload: list[dict[str, Any]]
    raw_payload_hash: str


class BaostockClient:
    """Lazy-importing wrapper around the optional ``baostock`` SDK."""

    def __init__(
        self,
        settings: BaostockSettings,
        *,
        module: ModuleType | None = None,
    ) -> None:
        if not isinstance(settings, BaostockSettings):
            raise TypeError(
                f"BaostockClient requires BaostockSettings (got {type(settings).__name__})"
            )
        self._settings = settings
        self._injected_module = module

    def fetch_etf_daily_bars(
        self,
        *,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
    ) -> BaostockResponse:
        if not symbols:
            raise ValueError("symbols must be a non-empty sequence")
        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        module = self._resolve_module()
        self._invoke_login(module.login)
        per_symbol_rows: list[tuple[str, list[dict[str, Any]]]] = []
        try:
            for symbol in symbols:
                per_symbol_rows.append(
                    (
                        symbol,
                        self._invoke_query(
                            module.query_history_k_data_plus,
                            symbol=symbol, start_date=start_date, end_date=end_date,
                        ),
                    )
                )
        finally:
            self._invoke_logout(module.logout)
        merged = [row for _, rows in per_symbol_rows for row in rows]
        if not merged:
            raise ProviderDataContractError(
                "EMPTY_REQUIRED_PAYLOAD",
                "baostock.query_history_k_data_plus returned an empty row "
                "set; Slice-1 contract requires at least one row",
                provider_key=_PROVIDER_KEY,
            )
        if len(symbols) > 1:
            empty_symbols = [
                symbol for symbol, rows in per_symbol_rows if not rows
            ]
            if empty_symbols:
                raise ProviderDataContractError(
                    "EMPTY_SYMBOL_PAYLOAD",
                    (
                        "baostock.query_history_k_data_plus returned 0 rows "
                        f"for native symbol(s) {empty_symbols!r} in a "
                        f"multi-symbol request; Slice-1 contract rejects "
                        f"silent partial success"
                    ),
                    provider_key=_PROVIDER_KEY,
                )
        return BaostockResponse(
            operation="query_history_k_data_plus",
            raw_payload=merged,
            raw_payload_hash=_canonical_payload_hash(merged),
        )

    def _invoke_login(self, login: Any) -> None:
        try:
            result = login()
        except OSError as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, f"baostock.login() raised OSError: {exc}",
            ) from exc
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY, f"baostock.login() raised {type(exc).__name__}: {exc}",
            ) from exc
        self._check_result_like(result, op="login")
        if str(getattr(result, "error_code", "")) != "0":
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"baostock.login() error_code={getattr(result, 'error_code', '?')!r} "
                f"error_msg={getattr(result, 'error_msg', '?')!r}",
            )

    def _invoke_logout(self, logout: Any) -> None:
        # Best-effort cleanup — must never mask a successful query payload.
        try:
            result = logout()
        except Exception:
            return
        if not (hasattr(result, "error_code") and hasattr(result, "error_msg")):
            return
        if str(getattr(result, "error_code", "")) != "0":
            return

    def _invoke_query(
        self, query: Any, *, symbol: str, start_date: date, end_date: date,
    ) -> list[dict[str, Any]]:
        try:
            result = query(
                code=symbol, fields=_FIELDS,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                adjustflag=self._settings.adjustflag, frequency="d",
            )
        except OSError as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"baostock.query_history_k_data_plus(code={symbol!r}) "
                f"raised OSError: {exc}",
            ) from exc
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"baostock.query_history_k_data_plus(code={symbol!r}) "
                f"raised {type(exc).__name__}: {exc}",
            ) from exc
        self._check_result_like(result, op="query_history_k_data_plus")
        error_code = str(getattr(result, "error_code", ""))
        if error_code != "0":
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"baostock.query_history_k_data_plus error_code={error_code!r} "
                f"error_msg={getattr(result, 'error_msg', '?')!r}",
            )
        return _rows_to_records(result, symbol)

    @staticmethod
    def _check_result_like(result: Any, *, op: str) -> None:
        if not (hasattr(result, "error_code") and hasattr(result, "error_msg")):
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"baostock.{op}() did not return a Result-like object "
                f"(got {type(result).__name__})",
            )

    def _resolve_module(self) -> ModuleType:
        if self._injected_module is not None:
            return self._injected_module
        try:
            spec = importlib.util.find_spec("baostock")
        except Exception as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, f"baostock SDK not importable ({exc})",
            ) from exc
        if spec is None:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, "baostock SDK not installed",
            )
        try:
            return importlib.import_module("baostock")
        except ImportError as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, f"baostock SDK not importable ({exc})",
            ) from exc


def _rows_to_records(result: Any, symbol: str) -> list[dict[str, Any]]:
    field_names = _FIELDS.split(",")
    records: list[dict[str, Any]] = []
    row_index = 0
    while True:
        try:
            has_next = result.next()
        except OSError as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, f"baostock next() raised OSError: {exc}",
            ) from exc
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY, f"baostock next() raised {type(exc).__name__}: {exc}",
            ) from exc
        if not has_next:
            break
        try:
            row = result.get_row_data()
        except OSError as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY, f"baostock get_row_data() raised OSError: {exc}",
            ) from exc
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY, f"baostock get_row_data() raised {type(exc).__name__}: {exc}",
            ) from exc
        if not isinstance(row, (list, tuple)):
            raise ProviderDataContractError(
                "MALFORMED_HISTORY_ROW",
                f"row {row_index} (symbol={symbol!r}) not a list/tuple",
                provider_key=_PROVIDER_KEY,
            )
        if len(row) != len(field_names):
            raise ProviderDataContractError(
                "MALFORMED_HISTORY_ROW",
                f"row {row_index} (symbol={symbol!r}) has {len(row)} columns, "
                f"expected {len(field_names)} ({_FIELDS!r})",
                provider_key=_PROVIDER_KEY,
            )
        records.append(dict(zip(field_names, list(row), strict=True)))
        row_index += 1
    final_err = str(getattr(result, "error_code", ""))
    if final_err and final_err != "0":
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"baostock query (symbol={symbol!r}) terminated error_code="
            f"{final_err!r} error_msg={getattr(result, 'error_msg', '?')!r}",
        )
    return records


def _canonical_payload_hash(records: list[dict[str, Any]]) -> str:
    text = json.dumps(
        records,
        ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    )
    return sha256(text.encode("utf-8")).hexdigest()


__all__ = ["BaostockClient", "BaostockResponse"]
