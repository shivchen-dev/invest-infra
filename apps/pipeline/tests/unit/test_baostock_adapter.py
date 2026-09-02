"""BaoStock adapter tests (Slice-1 of PR-08)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from invest_domain.instruments.models import InstrumentId
from invest_pipeline.adapters.baostock.adapter import (
    DATASET_KEY,
    PROVIDER_KEY,
    BaostockEtfDailyBarsAdapter,
)
from invest_pipeline.adapters.baostock.config import BaostockSettings
from invest_pipeline.adapters.errors import (
    ProviderDataContractError,
    ProviderUnavailableError,
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.request_keys import make_daily_bars_request_key

# ----- stub helpers shared with adapter tests ----------------------------


class _StubResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0
        self.error_code = "0"
        self.error_msg = ""

    def next(self):
        return self._idx < len(self._rows)

    def get_row_data(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


def _stub_module(rows_by_code):
    state = SimpleNamespace(queries=[])

    def login():
        return _StubResult([])

    def logout():
        return _StubResult([])

    def query(code, **kwargs):
        state.queries.append((code, kwargs))
        return _StubResult(rows_by_code.get(code, []))

    mod = SimpleNamespace(
        login=login, logout=logout, query_history_k_data_plus=query,
        __version__="0.0-test", queries=state.queries,
    )
    return mod


def _row(code="sh.510300", d="2026-01-05"):
    return (d, code, "1.0", "1.1", "0.95", "1.05", "100", "105.0")


def _adapter(rows_by_code, *, enabled=True, clock=None, settings=None):
    from invest_pipeline.adapters.baostock.client import BaostockClient
    if settings is None:
        settings = BaostockSettings(enabled=enabled)
    real_client = BaostockClient(settings, module=_stub_module(rows_by_code))
    real_client._test_module = real_client._injected_module  # type: ignore[attr-defined]
    return BaostockEtfDailyBarsAdapter(
        settings, client=real_client,
        clock=clock if clock is not None else (lambda: datetime(2026, 1, 31, tzinfo=UTC)),
    )


# ----- tests --------------------------------------------------------------


class TestConstants:
    def test_provider_and_dataset_keys_are_stable(self) -> None:
        assert PROVIDER_KEY == "baostock"
        assert DATASET_KEY == "etf_daily_bars"
        assert BaostockEtfDailyBarsAdapter(BaostockSettings(enabled=True)).provider_key == \
            "baostock"

    def test_fetch_raises_when_disabled(self) -> None:
        # enabled=False → RealProviderRequiresExplicitEnablementError.
        from invest_pipeline.adapters.baostock.client import BaostockClient
        client = BaostockClient(BaostockSettings(enabled=False), module=_stub_module({}))
        adapter = BaostockEtfDailyBarsAdapter(
            BaostockSettings(enabled=False), client=client,
            clock=lambda: datetime(2026, 1, 31, tzinfo=UTC),
        )
        with pytest.raises(RealProviderRequiresExplicitEnablementError):
            adapter.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )


class TestEndToEnd:
    def test_fetch_returns_evidence_tuple_with_canonical_params(self) -> None:
        adapter = _adapter({"sh.510300": [_row()]})
        request, attempt, batch = adapter.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        # Request identity surface.
        assert request.provider_key == "baostock"
        assert request.dataset_key == "etf_daily_bars"
        assert request.params["symbols"] == ["510300"]
        assert request.params["provider_native_symbols"] == ["sh.510300"]
        assert request.request_key == make_daily_bars_request_key(
            date(2026, 1, 1), date(2026, 1, 31), ["510300"],
        )
        # Attempt succeeded; batch has 1 row of Adjust.NONE.
        assert attempt.status.value == "succeeded"
        assert batch is not None and len(batch.records) == 1
        assert batch.records[0].adjustment.value == "none"

    def test_fetch_normalizes_bare_symbols_to_provider_native(self) -> None:
        adapter = _adapter({"sh.510300": [_row()], "sz.159901": [_row(code="sz.159901")]})
        adapter.fetch_daily_bars(
            symbols=["510300", "159901"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        module = adapter._client._test_module
        called_codes = [q[0] for q in module.queries]
        assert called_codes == ["sh.510300", "sz.159901"]

    def test_unsupported_bare_symbol_is_rejected_before_sdk(self) -> None:
        adapter = _adapter({})
        with pytest.raises(ValueError, match="unsupported baostock symbol"):
            adapter.fetch_daily_bars(
                symbols=["XXXXXX"],
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            )
        # No SDK call recorded.
        module = adapter._client._test_module
        assert module.queries == []

    def test_unavailable_or_empty_payload_yields_failed_attempt(self) -> None:
        # Unavailable SDK → ProviderFailureStage.HTTP
        from invest_pipeline.adapters.baostock.client import BaostockClient
        client_u = BaostockClient(BaostockSettings(enabled=True))

        def _unavailable():
            raise ProviderUnavailableError("baostock", "no SDK")
        client_u._resolve_module = _unavailable  # type: ignore[assignment]
        adapter_u = BaostockEtfDailyBarsAdapter(
            BaostockSettings(enabled=True), client=client_u,
            clock=lambda: datetime(2026, 1, 31, tzinfo=UTC),
        )
        request, attempt, batch = adapter_u.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert attempt.status.value == "failed"
        assert batch is None
        assert attempt.error_stage.value == "http"
        assert attempt.error_code == "ProviderUnavailableError"

        # Empty payload → ProviderFailureStage.CONTRACT
        adapter_e = _adapter({})
        request, attempt, batch = adapter_e.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert attempt.status.value == "failed"
        assert batch is None
        assert attempt.error_stage.value == "contract"
        assert attempt.error_code == "ProviderDataContractError"


class TestSymbolResolution:
    """``symbol_for_instrument_id`` round-trips placeholder UUIDs."""

    def test_symbol_for_instrument_id_returns_bare_symbol_for_fetched_bar(
        self,
    ) -> None:
        adapter = _adapter({"sh.510300": [_row()]})
        request, attempt, batch = adapter.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert batch is not None and len(batch.records) == 1
        resolved = adapter.symbol_for_instrument_id(batch.records[0].instrument_id)
        assert resolved == "510300"

    def test_symbol_for_instrument_id_returns_bare_symbol_per_exchange(
        self,
    ) -> None:
        adapter = _adapter(
            {
                "sh.510300": [_row()],
                "sz.159901": [_row(code="sz.159901")],
            },
        )
        _, _, batch = adapter.fetch_daily_bars(
            symbols=["510300", "159901"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert batch is not None and len(batch.records) == 2
        ids = {bar.instrument_id for bar in batch.records}
        resolved = {
            adapter.symbol_for_instrument_id(instrument_id) for instrument_id in ids
        }
        assert resolved == {"510300", "159901"}

    def test_symbol_for_instrument_id_returns_none_for_unknown(self) -> None:
        adapter = _adapter({})
        # An unseeded UUID must resolve to None so the application
        # service surfaces a hard error rather than silently picking
        # the first cached symbol.
        assert adapter.symbol_for_instrument_id(InstrumentId.generate()) is None

    def test_symbol_for_instrument_id_returns_none_before_any_fetch(
        self,
    ) -> None:
        adapter = BaostockEtfDailyBarsAdapter(BaostockSettings(enabled=True))
        assert adapter.symbol_for_instrument_id(InstrumentId.generate()) is None


class TestHistoryWindowGuard:
    """``WINDOW_OUT_OF_RANGE`` is raised before the SDK is invoked."""

    def test_window_within_120_days_is_accepted(self) -> None:
        adapter = _adapter({"sh.510300": [_row()]})
        request, attempt, batch = adapter.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        )
        assert attempt.status.value == "succeeded"
        assert batch is not None

    def test_window_exceeding_120_days_raises_window_out_of_range(self) -> None:
        adapter = _adapter({})
        with pytest.raises(ProviderDataContractError) as exc:
            adapter.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2025, 8, 1), end_date=date(2026, 1, 31),
            )
        assert exc.value.code == "WINDOW_OUT_OF_RANGE"
        # SDK must not have been touched: the guard short-circuits before
        # login / query / logout.
        module = adapter._client._test_module
        assert module.queries == []

    def test_window_at_exact_120_days_is_accepted(self) -> None:
        adapter = _adapter({"sh.510300": [_row()]})
        # Clock at 2026-01-31; start_date at 2025-10-03 → 120-day span.
        request, attempt, batch = adapter.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2025, 10, 3), end_date=date(2026, 1, 31),
        )
        assert attempt.status.value == "succeeded"
        assert batch is not None

    def test_window_uses_injected_clock_date(self) -> None:
        # The guard consumes the injected clock, not wall-clock. A clock
        # fixed to 2026-01-31 makes the same (clock-relative) 120-day
        # window pass.

        def _clock():
            return datetime(2025, 6, 1, tzinfo=UTC)

        adapter = _adapter(
            {"sh.510300": [_row()]}, clock=_clock,
        )
        request, attempt, batch = adapter.fetch_daily_bars(
            symbols=["510300"],
            start_date=date(2025, 4, 1), end_date=date(2025, 6, 1),
        )
        assert attempt.status.value == "succeeded"

    def test_max_history_days_respects_custom_setting(self) -> None:
        settings = BaostockSettings(enabled=True, max_history_days=30)
        adapter = _adapter(
            {},
            settings=settings,
            clock=lambda: datetime(2026, 6, 30, tzinfo=UTC),
        )
        with pytest.raises(ProviderDataContractError) as exc:
            adapter.fetch_daily_bars(
                symbols=["510300"],
                start_date=date(2026, 5, 1), end_date=date(2026, 6, 30),
            )
        assert exc.value.code == "WINDOW_OUT_OF_RANGE"
