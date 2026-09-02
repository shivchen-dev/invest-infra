"""Tests for the opt-in ETF daily-bars transient fallback seam."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest
from invest_pipeline.etf_daily_bars import (
    RawEtlResult,
    write_etf_daily_bars_raw_with_fallback,
)

_START_DATE = date(2026, 8, 1)
_END_DATE = date(2026, 8, 31)


def _result(
    *,
    request_status: str,
    attempt_status: str = "succeeded",
    record_count: int = 1,
    error_code: str | None = None,
    provider_key: str | None = None,
) -> RawEtlResult:
    return RawEtlResult(
        request_id=uuid4(),
        attempt_id=uuid4(),
        batch_id=uuid4() if request_status == "succeeded" else None,
        request_status=request_status,
        attempt_status=attempt_status,
        record_count=record_count,
        error_code=error_code,
        provider_key=provider_key,
    )


@pytest.mark.parametrize(
    "error_code",
    ["ProviderTimeoutError", "ProviderUnavailableError"],
)
def test_transient_primary_failure_persists_then_returns_fallback(
    error_code: str,
) -> None:
    primary_provider = MagicMock(name="akshare_provider")
    fallback_provider = MagicMock(name="baostock_provider")
    session_factory = MagicMock(name="session_factory")
    unit_of_work_factory = MagicMock(name="unit_of_work_factory")
    symbols = ["510300", "159915"]
    primary = _result(
        request_status="failed",
        attempt_status="failed",
        record_count=0,
        error_code=error_code,
        provider_key="akshare",
    )
    fallback = _result(
        request_status="succeeded",
        record_count=2,
        provider_key="baostock",
    )

    with patch(
        "invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw",
        side_effect=[primary, fallback],
    ) as writer:
        result = write_etf_daily_bars_raw_with_fallback(
            primary_provider,
            session_factory,
            symbols=symbols,
            start_date=_START_DATE,
            end_date=_END_DATE,
            fallback_provider=fallback_provider,
            fallback_enabled=True,
            unit_of_work_factory=unit_of_work_factory,
        )

    assert result is fallback
    assert result.provider_key == "baostock"
    assert writer.call_args_list == [
        call(
            primary_provider,
            session_factory,
            symbols=symbols,
            start_date=_START_DATE,
            end_date=_END_DATE,
            unit_of_work_factory=unit_of_work_factory,
        ),
        call(
            fallback_provider,
            session_factory,
            symbols=symbols,
            start_date=_START_DATE,
            end_date=_END_DATE,
            unit_of_work_factory=unit_of_work_factory,
        ),
    ]
    assert writer.call_args_list[0].kwargs["symbols"] is symbols
    assert writer.call_args_list[1].kwargs["symbols"] is symbols


@pytest.mark.parametrize(
    ("request_status", "attempt_status", "record_count", "error_code"),
    [
        ("succeeded", "succeeded", 2, None),
        ("partial", "succeeded", 0, None),
        ("succeeded", "succeeded", 0, None),
        ("failed", "failed", 0, "ProviderAuthenticationError"),
        ("failed", "failed", 0, "ProviderRateLimitError"),
        ("failed", "failed", 0, "ProviderBadResponseError"),
        ("failed", "failed", 0, "ProviderDataContractError"),
        ("failed", "failed", 0, "MapperValidationError"),
        ("failed", "failed", 0, "unknown_error"),
        ("failed", "failed", 0, "some_future_error"),
        ("failed", "failed", 0, None),
    ],
)
def test_non_transient_or_non_failed_primary_does_not_fallback(
    request_status: str,
    attempt_status: str,
    record_count: int,
    error_code: str | None,
) -> None:
    primary = _result(
        request_status=request_status,
        attempt_status=attempt_status,
        record_count=record_count,
        error_code=error_code,
        provider_key="akshare",
    )
    fallback_provider = MagicMock(name="baostock_provider")

    with patch(
        "invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw",
        return_value=primary,
    ) as writer:
        result = write_etf_daily_bars_raw_with_fallback(
            MagicMock(name="akshare_provider"),
            MagicMock(name="session_factory"),
            symbols=("510300",),
            start_date=_START_DATE,
            end_date=_END_DATE,
            fallback_provider=fallback_provider,
            fallback_enabled=True,
        )

    assert result is primary
    assert result.provider_key == "akshare"
    assert writer.call_count == 1
    fallback_provider.fetch_daily_bars.assert_not_called()


@pytest.mark.parametrize(
    ("fallback_enabled", "has_fallback"),
    [(False, True), (True, False)],
)
def test_fallback_is_default_off_and_requires_provider(
    fallback_enabled: bool,
    has_fallback: bool,
) -> None:
    primary = _result(
        request_status="failed",
        attempt_status="failed",
        record_count=0,
        error_code="ProviderTimeoutError",
    )
    fallback_provider = MagicMock(name="baostock_provider") if has_fallback else None

    with patch(
        "invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw",
        return_value=primary,
    ) as writer:
        result = write_etf_daily_bars_raw_with_fallback(
            MagicMock(name="akshare_provider"),
            MagicMock(name="session_factory"),
            symbols=("510300",),
            start_date=_START_DATE,
            end_date=_END_DATE,
            fallback_provider=fallback_provider,
            fallback_enabled=fallback_enabled,
        )

    assert result is primary
    assert writer.call_count == 1


def test_failed_fallback_is_returned_without_third_attempt() -> None:
    primary = _result(
        request_status="failed",
        attempt_status="failed",
        record_count=0,
        error_code="ProviderUnavailableError",
    )
    fallback = _result(
        request_status="failed",
        attempt_status="failed",
        record_count=0,
        error_code="ProviderUnavailableError",
    )

    with patch(
        "invest_pipeline.etf_daily_bars.write_etf_daily_bars_raw",
        side_effect=[primary, fallback],
    ) as writer:
        result = write_etf_daily_bars_raw_with_fallback(
            MagicMock(name="akshare_provider"),
            MagicMock(name="session_factory"),
            symbols=("510300",),
            start_date=_START_DATE,
            end_date=_END_DATE,
            fallback_provider=MagicMock(name="baostock_provider"),
            fallback_enabled=True,
        )

    assert result is fallback
    assert writer.call_count == 2
