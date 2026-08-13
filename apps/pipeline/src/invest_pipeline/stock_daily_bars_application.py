"""Application orchestration for stock daily bars ingestion."""

from __future__ import annotations

import re
from typing import Any, Protocol

from .provider_health import ProviderHealthSnapshot, ProviderHealthStatus
from .stock_daily_bars_engine import StockDailyBarsCommand, StockDailyBarsOutcome


class ProviderResolver(Protocol):
    def __call__(self, command: StockDailyBarsCommand) -> Any: ...


class RawIngestor(Protocol):
    def __call__(self, provider: Any, command: StockDailyBarsCommand) -> Any: ...


class CorePublisher(Protocol):
    def __call__(self, raw: Any, command: StockDailyBarsCommand) -> Any: ...


class HealthPreflight(Protocol):
    def __call__(
        self, command: StockDailyBarsCommand
    ) -> ProviderHealthSnapshot | None: ...


_UNHEALTHY_PREFLIGHT_SUMMARY = "provider health preflight not healthy"


class StockDailyBarsEngine:
    def __init__(
        self,
        resolver: ProviderResolver,
        raw_ingestor: RawIngestor,
        core_publisher: CorePublisher,
        *,
        health_preflight: HealthPreflight | None = None,
    ) -> None:
        self._resolver = resolver
        self._raw_ingestor = raw_ingestor
        self._core_publisher = core_publisher
        self._health_preflight = health_preflight

    def execute(self, command: StockDailyBarsCommand) -> StockDailyBarsOutcome:
        raw: Any = None
        provider: Any = None
        try:
            if self._health_preflight is not None:
                snapshot = self._health_preflight(command)
                if snapshot is not None and (
                    snapshot.status is not ProviderHealthStatus.HEALTHY
                ):
                    return self._outcome(
                        raw,
                        provider,
                        "FAILED",
                        error_summary=_UNHEALTHY_PREFLIGHT_SUMMARY,
                    )

            provider = self._resolver(command)
            raw = self._raw_ingestor(provider, command)

            if getattr(raw, "request_status", None) == "failed":
                return self._outcome(
                    raw,
                    provider,
                    "FAILED",
                    error_summary="raw ingestion failed",
                )
            if getattr(raw, "request_status", None) == "partial":
                return self._outcome(raw, provider, "PARTIAL")

            published = self._core_publisher(raw, command)
            return self._outcome(
                raw,
                provider,
                "SUCCEEDED",
                inserted=getattr(published, "inserted", 0),
                skipped=getattr(published, "skipped", 0),
            )
        except Exception as exc:
            return self._outcome(
                raw,
                provider,
                "FAILED",
                error_summary=self._safe_error_summary(exc),
            )

    @staticmethod
    def _outcome(
        raw: Any,
        provider: Any,
        status: str,
        *,
        error_summary: str | None = None,
        inserted: Any = None,
        skipped: Any = None,
    ) -> StockDailyBarsOutcome:
        raw_provider_key = getattr(raw, "provider_key", None)
        return StockDailyBarsOutcome(
            status=status,
            provider_key=(
                raw_provider_key
                if raw_provider_key is not None
                else getattr(provider, "provider_key", None)
            ),
            request_id=getattr(raw, "request_id", None),
            attempt_id=getattr(raw, "attempt_id", None),
            batch_id=getattr(raw, "batch_id", None),
            record_count=getattr(raw, "record_count", 0) or 0,
            inserted=inserted if inserted is not None else 0,
            skipped=skipped if skipped is not None else 0,
            fallback_used=getattr(raw, "fallback_used", False) or False,
            error_summary=error_summary,
        )

    @staticmethod
    def _safe_error_summary(exc: Exception) -> str:
        message = str(exc).replace("\n", " ").strip()
        message = re.sub(
            r"(?i)(api_key|access_token|token\s*=|password|secret)",
            "[REDACTED]",
            message,
        )
        message = re.sub(r"\s+", " ", message)[:160]
        return f"{type(exc).__name__}: {message or 'operation failed'}"
