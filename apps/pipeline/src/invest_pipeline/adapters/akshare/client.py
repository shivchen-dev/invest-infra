"""AkShare SDK wrapper (PR-02, matrix §3 / §10 / NAV / trading calendar).

This module owns the boundary between the optional ``akshare`` SDK and
the V2 domain layer. Like the CifangQuant HTTP client, every side
effect that could touch the network is delayed until the call site
explicitly invokes a fetch method. The adapter module never imports
``akshare`` and the configuration object never imports it; only this
client pays the import cost, and only inside the per-call dispatch
methods so:

- Importing :mod:`invest_pipeline.adapters.akshare` succeeds even when
  the SDK is not installed (matrix §10 verifies the slice ships without
  the dependency by default).
- Constructing :class:`AkshareClient` does not perform any network I/O.
- Construction does not require the SDK either: tests inject a fake
  module and the production code path resolves the real module lazily
  on first use.

When the real SDK is unavailable, the client raises
:class:`~invest_pipeline.adapters.errors.ProviderUnavailableError`
carrying ``provider_key="akshare"`` (the canonical category for
"dependency missing or upstream unreachable" failures). The mapper
never sees raw ``ImportError`` instances — the client translates them
so the adapter only ever deals with the typed
:class:`~invest_pipeline.adapters.errors.ProviderError` family.

The shape of the call surface mirrors matrix §2 / §10 / NAV /
trading calendar additions:

- :meth:`AkshareClient.fetch_fund_etf_fund_info_em` powers the ETF
  master-data path (``ak.fund_etf_fund_info_em()`` per official docs).
- :meth:`AkshareClient.fetch_fund_name_em` powers the public-fund
  profile path (``ak.fund_name_em()`` per official docs). The DC-2
  ETF Profile slice joins this payload on ``基金代码`` against the
  matching ``fund_etf_spot_em`` snapshot to populate the
  ``fund_type`` / ``category`` fields.
- :meth:`AkshareClient.fetch_fund_etf_spot_em` powers the ETF spot
  snapshot path (``ak.fund_etf_spot_em()`` per official docs). The
  DC-2 ETF Profile slice reads ``最新份额`` to populate the
  ``shares`` field; the response's ``总市值`` is **never** mapped to
  ``aum`` (AUM is a Provider-disclosed figure, not a market-cap
  calculation).
- :meth:`AkshareClient.fetch_fund_etf_hist_em` powers the daily-bars
  path (``ak.fund_etf_hist_em(symbol=..., period='daily',
  start_date=..., end_date=..., adjust=...)`` per official docs).
- :meth:`AkshareClient.fetch_fund_etf_fund_daily_em` powers the
  per-symbol NAV path (``ak.fund_etf_fund_daily_em()`` per official
  docs). The mapper does **not** promote NAV rows to OHLCV (plan §5
  Task 2 "明确 NAV 不映射为 OHLCV，不填充成交额").
- :meth:`AkshareClient.fetch_tool_trade_date_hist_sina` powers the
  read-only trading-calendar surface
  (``ak.tool_trade_date_hist_sina()`` per official docs); the helper
  preserves the upstream string dates so the mapper can normalise
  them against the ADR-0004 timezone rule.

Every method normalises the SDK's pandas ``DataFrame`` return value
to a list of plain ``dict[str, Any]`` at the boundary so the rest of
the adapter stack does not need ``pandas`` and so the sidecar JSON
payload hashing remains canonical.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from types import ModuleType
from typing import Any

from invest_pipeline.adapters.akshare.config import AkshareSettings
from invest_pipeline.adapters.errors import (
    ProviderBadResponseError,
    ProviderUnavailableError,
)

_PROVIDER_KEY = "akshare"


@dataclass(frozen=True, slots=True)
class AkshareResponse:
    """A single successful AkShare call.

    ``raw_payload`` is the list-of-dicts normalising the SDK's pandas
    ``DataFrame`` so the mapper and the hashing layer stay
    ``pandas``-free. ``raw_payload_hash`` is the hex SHA-256 of the
    canonical JSON encoding of ``raw_payload``; the adapter stamps it
    on :attr:`invest_domain.market_data.models.ProviderBatch.
    raw_payload_hash` so the raw evidence row stays request-scoped.
    """

    operation: str
    raw_payload: list[dict[str, Any]]
    raw_payload_hash: str


class AkshareClient:
    """Lazy-importing wrapper around the optional ``akshare`` SDK.

    Parameters
    ----------
    settings:
        Redacted configuration object. ``enabled`` is **not** consulted
        by the client (the adapter refuses to call the client while
        ``enabled=False``). The client is purely a transport.
    module:
        Optional pre-resolved ``akshare`` module. When supplied the
        client skips the ``importlib.util.find_spec`` /
        ``importlib.import_module`` round-trip and uses the injected
        reference verbatim — this is the seam unit tests use to inject
        a fake module via ``monkeypatch.setitem`` or a constructor
        kwarg.
    module_resolver:
        Optional callable that returns the ``akshare`` module on
        demand. The default resolves the module via
        :func:`_default_module_resolver`; tests inject a callable that
        returns a stub module so CI never has the real dependency
        installed.
    """

    def __init__(
        self,
        settings: AkshareSettings,
        *,
        module: ModuleType | None = None,
        module_resolver: Callable[[], ModuleType] | None = None,
    ) -> None:
        if not isinstance(settings, AkshareSettings):
            raise TypeError(
                "AkshareClient requires an AkshareSettings instance "
                f"(got {type(settings).__name__})"
            )
        if module is not None and module_resolver is not None:
            raise ValueError(
                "AkshareClient accepts either 'module' or "
                "'module_resolver', not both"
            )
        self._settings = settings
        self._injected_module = module
        self._module_resolver: Callable[[], ModuleType] = (
            module_resolver if module_resolver is not None else _default_module_resolver
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_fund_etf_fund_info_em(self) -> AkshareResponse:
        """Return the canonical ETF master-data payload.

        Calls ``ak.fund_etf_fund_info_em()`` and normalises the
        ``DataFrame`` into a list of plain ``dict`` records. The
        upstream function returns DataFrames with Chinese column names
        (``基金代码`` / ``基金简称`` / ...); the mapper translates
        each row into a domain :class:`Instrument` and applies the
        SSE / SZSE allow-list.
        """

        module = self._resolve_module()
        operation = "fund_etf_fund_info_em"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)()
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() raised {type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_fund_name_em(self) -> AkshareResponse:
        """Return the canonical public-fund profile payload.

        Calls ``ak.fund_name_em()`` (per official docs) and normalises
        the ``DataFrame`` into a list of plain ``dict`` records. The
        upstream function returns DataFrames with Chinese column names
        (``基金代码`` / ``基金简称`` / ``基金类型`` / ...). The
        ETF Profile mapper reads ``基金类型`` to populate
        ``EtfProfile.fund_type`` / ``category`` and uses ``基金代码``
        as the join key against the matching ``fund_etf_spot_em``
        snapshot.
        """

        module = self._resolve_module()
        operation = "fund_name_em"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)()
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() raised {type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_fund_etf_spot_em(self) -> AkshareResponse:
        """Return the canonical ETF spot snapshot payload.

        Calls ``ak.fund_etf_spot_em()`` (per official docs) and
        normalises the ``DataFrame`` into a list of plain ``dict``
        records. The upstream function returns DataFrames with Chinese
        column names (``代码`` / ``名称`` / ``最新份额`` / ...). The
        ETF Profile mapper reads ``最新份额`` to populate
        ``EtfProfile.shares`` and uses ``代码`` as the join key against
        the matching ``fund_name_em`` payload.
        """

        module = self._resolve_module()
        operation = "fund_etf_spot_em"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)()
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() raised {type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_fund_etf_hist_em(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> AkshareResponse:
        """Return the canonical ETF daily-bars payload for ``symbol``.

        Calls ``ak.fund_etf_hist_em(symbol=..., period='daily',
        start_date=..., end_date=..., adjust=...)``. The
        ``start_date`` / ``end_date`` are formatted with AkShare's
        ``YYYYMMDD`` convention; the ``adjust`` argument comes from
        :attr:`AkshareSettings.adjust` so the lock is enforced
        regardless of which caller asked for the data.

        Parameters
        ----------
        symbol:
            Six-digit ETF code understood by AkShare (e.g.
            ``"510300"``). The mapper translates the code into the
            upstream ``SSE`` / ``SZSE`` exchange via the documented
            prefix rule.
        start_date / end_date:
            Inclusive date interval. AkShare accepts strings in the
            ``YYYYMMDD`` / ``YYYY-MM-DD`` forms; we use the compact
            eight-digit form to match the official examples.
        """

        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        module = self._resolve_module()
        operation = "fund_etf_hist_em"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)(
                symbol=symbol,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust=self._settings.adjust,
            )
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}(symbol={symbol!r}) raised "
                f"{type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_fund_etf_hist_sina(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> AkshareResponse:
        """Return the requested-range ETF daily-bars payload from Sina.

        Sina exposes the full history for a market-prefixed symbol, so the
        client applies the inclusive date boundary after normalising the
        SDK response.
        """

        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if end_date < start_date:
            raise ValueError(
                f"end_date {end_date.isoformat()} must be on or after "
                f"start_date {start_date.isoformat()}"
            )
        module = self._resolve_module()
        operation = "fund_etf_hist_sina"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        sina_symbol = _sina_symbol(symbol)
        try:
            dataframe = getattr(module, operation)(symbol=sina_symbol)
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}(symbol={sina_symbol!r}) raised "
                f"{type(exc).__name__}: {_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _filter_date_range(
            _dataframe_to_records(dataframe, operation),
            operation=operation,
            start_date=start_date,
            end_date=end_date,
        )
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_fund_etf_fund_daily_em(self, *, symbol: str) -> AkshareResponse:
        """Return the canonical per-symbol ETF NAV payload.

        Calls ``ak.fund_etf_fund_daily_em()`` which returns the daily
        NAV / unit-net-value series for a single ETF symbol. The
        payload is intentionally **separate** from the daily-bars
        feed: per plan §5 Task 2 ("明确 NAV 不映射为 OHLCV，不填充成
        交额") NAV rows must never be coerced into ``DailyBar`` rows.
        The mapper therefore produces its own dataclass instead of
        reusing :class:`DailyBar`.

        Parameters
        ----------
        symbol:
            Six-digit ETF code understood by AkShare (e.g.
            ``"510300"``). The mapper translates the code into the
            upstream ``SSE`` / ``SZSE`` exchange via the documented
            prefix rule.
        """

        if not symbol or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        module = self._resolve_module()
        operation = "fund_etf_fund_daily_em"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)(symbol=symbol)
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}(symbol={symbol!r}) raised "
                f"{type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    def fetch_tool_trade_date_hist_sina(self) -> AkshareResponse:
        """Return the canonical read-only trading-calendar payload.

        Calls ``ak.tool_trade_date_hist_sina()`` (per official docs)
        which returns the historical SSE / SZSE trading-day schedule.
        The endpoint is a **read-only** research / coverage surface
        that backs the AkShare side of the PR-05 coverage probe; it
        carries no per-symbol rows so the mapper produces date-only
        records and the adapter stamps a single date-range batch on
        :class:`ProviderBatch`.
        """

        module = self._resolve_module()
        operation = "tool_trade_date_hist_sina"
        if not hasattr(module, operation):
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare module exposes no '{operation}' function; "
                "the installed SDK version may have removed or renamed "
                f"it (akshare.__version__={getattr(module, '__version__', 'unknown')!r})",
            )
        try:
            dataframe = getattr(module, operation)()
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() raised {type(exc).__name__}: "
                f"{_scrub_message(str(exc), self._settings)}",
            ) from exc
        records = _dataframe_to_records(dataframe, operation)
        return AkshareResponse(
            operation=operation,
            raw_payload=records,
            raw_payload_hash=_canonical_payload_hash(records),
        )

    # ------------------------------------------------------------------
    # Internal: module resolution
    # ------------------------------------------------------------------

    def _resolve_module(self) -> ModuleType:
        if self._injected_module is not None:
            return self._injected_module
        try:
            return self._module_resolver()
        except _AkshareModuleUnavailable as exc:
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare SDK is not installed or importable "
                f"(install with 'pip install akshare' to enable the "
                f"akshare provider; root cause: {exc})",
            ) from exc
        except ImportError as exc:
            # The default resolver raised ``ModuleNotFoundError``
            # (an ``ImportError`` subclass) when ``akshare`` is not
            # installed on the host; surface the same typed error so
            # unit tests injecting a stub ``module_resolver`` do not
            # need to wrap the failure manually.
            raise ProviderUnavailableError(
                _PROVIDER_KEY,
                f"akshare SDK is not installed or importable "
                f"(install with 'pip install akshare' to enable the "
                f"akshare provider; root cause: {exc})",
            ) from exc


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


class _AkshareModuleUnavailable(ImportError):
    """Internal: wrapped ``ImportError`` so the client can map to typed errors."""


def _default_module_resolver() -> ModuleType:
    """Resolve the ``akshare`` SDK module lazily.

    Implemented via :func:`importlib.import_module` rather than a
    module-level ``import akshare`` so the package stays importable
    when the optional dependency is absent. The resolver raises the
    internal :class:`_AkshareModuleUnavailable` on failure so the
    client can attach context without leaking ``ImportError`` through
    the adapter boundary.
    """

    import importlib
    import importlib.util

    try:
        spec = importlib.util.find_spec("akshare")
    except Exception as exc:
        raise _AkshareModuleUnavailable(str(exc)) from exc
    if spec is None:
        raise _AkshareModuleUnavailable("akshare is not installed (no module spec found)")
    try:
        return importlib.import_module("akshare")
    except Exception as exc:
        raise _AkshareModuleUnavailable(str(exc)) from exc


def _dataframe_to_records(dataframe: Any, operation: str) -> list[dict[str, Any]]:
    """Coerce a pandas ``DataFrame`` (or duck-typed drop-in) to ``dict`` rows.

    The real AkShare SDK returns ``pandas.DataFrame`` objects. The
    coercion uses the ``DataFrame.to_dict(orient='records')`` method
    when available; otherwise it accepts a list / tuple of dict-like
    rows. The mapper never imports ``pandas`` so a stub dataframe
    exposing ``to_dict(orient=...)`` (or a plain ``__iter__`` of
    dicts) is sufficient for tests.
    """

    if dataframe is None:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"akshare.{operation}() returned None instead of a data table",
        )
    if hasattr(dataframe, "to_dict"):
        try:
            records = dataframe.to_dict(orient="records")
        except Exception as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() payload is not a serialisable "
                f"data table: {exc}",
            ) from exc
    elif isinstance(dataframe, list):
        records = dataframe
    elif isinstance(dataframe, tuple):
        records = list(dataframe)
    else:
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"akshare.{operation}() returned unexpected payload of "
            f"type {type(dataframe).__name__}; expected a pandas DataFrame",
        )
    if not isinstance(records, list):
        raise ProviderBadResponseError(
            _PROVIDER_KEY,
            f"akshare.{operation}() payload is not a list of records "
            f"(got {type(records).__name__})",
        )
    normalised: list[dict[str, Any]] = []
    for index, entry in enumerate(records):
        if entry is None:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() row {index} is None",
            )
        if not isinstance(entry, dict):
            try:
                entry = dict(entry)
            except Exception as exc:
                raise ProviderBadResponseError(
                    _PROVIDER_KEY,
                    f"akshare.{operation}() row {index} is not a "
                    f"dict-like mapping: {exc}",
                ) from exc
        normalised.append(dict(entry))
    return normalised


def _sina_symbol(symbol: str) -> str:
    """Apply the V1 ETF market-prefix convention used by Sina."""

    code = symbol.strip()
    if code[0] in {"5", "6"}:
        return f"sh{code}"
    if code[0] in {"1", "2"}:
        return f"sz{code}"
    raise ProviderBadResponseError(
        _PROVIDER_KEY,
        f"cannot map ETF symbol {symbol!r} to Sina's sh/sz market prefix",
    )


def _filter_date_range(
    records: list[dict[str, Any]],
    *,
    operation: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        raw_date = next(
            (
                record.get(key)
                for key in ("日期", "trade_date", "date")
                if record.get(key) is not None
            ),
            None,
        )
        if raw_date is None:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() row {index} has no date field",
            )
        try:
            if isinstance(raw_date, datetime):
                row_date = raw_date.date()
            elif isinstance(raw_date, date):
                row_date = raw_date
            else:
                text = str(raw_date).strip()
                if "-" in text:
                    row_date = datetime.strptime(text[:10], "%Y-%m-%d").date()
                else:
                    row_date = datetime.strptime(text[:8], "%Y%m%d").date()
        except (TypeError, ValueError) as exc:
            raise ProviderBadResponseError(
                _PROVIDER_KEY,
                f"akshare.{operation}() row {index} has invalid date {raw_date!r}",
            ) from exc
        if start_date <= row_date <= end_date:
            filtered.append(record)
    return filtered


def _canonical_payload_hash(records: list[dict[str, Any]]) -> str:
    """Return a stable SHA-256 of the normalised AkShare payload.

    Uses sorted keys + compact separators so the digest is independent
    of dict ordering; the value populates
    :attr:`invest_domain.market_data.models.ProviderBatch.
    raw_payload_hash` so the raw evidence row stays request-scoped.
    """

    import json
    from hashlib import sha256

    text = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(text.encode("utf-8")).hexdigest()


def _scrub_message(message: str, settings: AkshareSettings) -> str:
    """Remove any configured token substrings from a free-text error.

    AkShare exceptions are not known to embed the SDK token, but a
    wrapped logger or a custom AkShare release could conceivably do so.
    The scrubber is a no-op when the token is empty so we never mangle
    test / offline-mode error messages.
    """

    token = settings.resolved_token()
    if not token:
        return message
    return message.replace(token, "***")


__all__ = ["AkshareClient", "AkshareResponse"]
