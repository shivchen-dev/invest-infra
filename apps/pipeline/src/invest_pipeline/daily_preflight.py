"""Pure checks performed before a personal daily pipeline run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

_KNOWN_PROVIDERS = frozenset({"fixture_dev", "cifangquant"})


@dataclass(frozen=True, slots=True)
class DailyPreflightResult:
    """Decision and stable reason code for one prospective daily run."""

    decision: str
    reason: str


def evaluate_daily_preflight(
    *,
    trade_date: date,
    provider_key: str,
    personal_universe_loader: Callable[[], object],
    published_run_exists: Callable[[date], bool],
    running_run_exists: Callable[[date], bool],
    data_ready_checker: Callable[[date], bool] | None = None,
    today: date | None = None,
) -> DailyPreflightResult:
    """Evaluate safe-to-run checks without touching infrastructure."""

    if trade_date > (today if today is not None else date.today()):
        return DailyPreflightResult("fail", "future_date")
    if trade_date.weekday() >= 5:
        return DailyPreflightResult("skip", "skip_non_business_day")
    if provider_key not in _KNOWN_PROVIDERS:
        return DailyPreflightResult("fail", "provider_not_configured")
    try:
        if not personal_universe_loader():
            return DailyPreflightResult("fail", "personal_universe_unavailable")
    except Exception:
        return DailyPreflightResult("fail", "personal_universe_unavailable")
    if published_run_exists(trade_date):
        return DailyPreflightResult("skip", "skip_already_published")
    if running_run_exists(trade_date):
        return DailyPreflightResult("skip", "skip_already_running")
    if data_ready_checker is not None:
        try:
            if not data_ready_checker(trade_date):
                return DailyPreflightResult("skip", "skip_data_not_ready")
        except Exception:
            return DailyPreflightResult("fail", "data_check_failed")
    return DailyPreflightResult("run", "ready")
