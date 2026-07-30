from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from invest_pipeline.providers.capabilities import (
    ADJUSTMENT_NONE,
    PROVIDER_KEY_AKSHARE,
    PROVIDER_KEY_CIFANG,
    PROVIDER_KEY_FIXTURE_DEV,
    PROVIDER_KEY_QUICKTINY_MCP,
    PROVIDER_KEY_RSSCAST,
    is_adjustment_allowed,
)
from invest_pipeline.providers.errors import RealProviderRequiresExplicitEnablementError


@dataclass(frozen=True, slots=True)
class AkshareProviderSettings:
    enabled: bool = False
    token: str = ""
    base_url: str = "https://example.invalid/akshare"
    timeout_seconds: float = 10.0

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "AkshareProviderSettings":
        return cls(
            enabled=_coerce_bool(mapping.get("enabled", False)),
            token=str(mapping.get("token", "") or ""),
            base_url=str(mapping.get("base_url", "https://example.invalid/akshare")),
            timeout_seconds=float(mapping.get("timeout_seconds", 10.0)),
        )


@dataclass(frozen=True, slots=True)
class CifangProviderSettings:
    enabled: bool = False
    token: str = ""
    base_url: str = "https://www.cifangquant.com/api"
    adjustment: str = ADJUSTMENT_NONE
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not is_adjustment_allowed(self.adjustment):
            raise ValueError(
                f"CifangProviderSettings.adjustment must be one of {{'none'}} "
                f"per ADR-0005; got {self.adjustment!r}"
            )

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "CifangProviderSettings":
        return cls(
            enabled=_coerce_bool(mapping.get("enabled", False)),
            token=str(mapping.get("token", "") or ""),
            base_url=str(mapping.get("base_url", "https://www.cifangquant.com/api")),
            adjustment=str(mapping.get("adjustment", ADJUSTMENT_NONE)),
            timeout_seconds=float(mapping.get("timeout_seconds", 10.0)),
        )


@dataclass(frozen=True, slots=True)
class RsscastProviderSettings:
    enabled: bool = False
    token: str = ""
    timeout_seconds: float = 10.0

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "RsscastProviderSettings":
        return cls(
            enabled=_coerce_bool(mapping.get("enabled", False)),
            token=str(mapping.get("token", "") or ""),
            timeout_seconds=float(mapping.get("timeout_seconds", 10.0)),
        )


@dataclass(frozen=True, slots=True)
class QuicktinyMcpProviderSettings:
    enabled: bool = False
    token: str = ""
    timeout_seconds: float = 10.0

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "QuicktinyMcpProviderSettings":
        return cls(
            enabled=_coerce_bool(mapping.get("enabled", False)),
            token=str(mapping.get("token", "") or ""),
            timeout_seconds=float(mapping.get("timeout_seconds", 10.0)),
        )


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Top-level Provider settings driven by environment variables.

    Default selection is fixture_dev. Real Providers stay disabled so no
    CI/test/dev process ever silently hits a third-party API.
    """

    provider_key: str = PROVIDER_KEY_FIXTURE_DEV
    akshare: AkshareProviderSettings = field(default_factory=AkshareProviderSettings)
    cifang: CifangProviderSettings = field(default_factory=CifangProviderSettings)
    rsscast: RsscastProviderSettings = field(default_factory=RsscastProviderSettings)
    quicktiny_mcp: QuicktinyMcpProviderSettings = field(default_factory=QuicktinyMcpProviderSettings)

    def is_enabled(self, provider_key: str) -> bool:
        if provider_key == PROVIDER_KEY_FIXTURE_DEV:
            return True
        return self._real_settings(provider_key).enabled

    def real_settings(self, provider_key: str) -> object:
        return self._real_settings(provider_key)

    def _real_settings(self, provider_key: str) -> object:
        mapping = {
            PROVIDER_KEY_AKSHARE: self.akshare,
            PROVIDER_KEY_CIFANG: self.cifang,
            PROVIDER_KEY_RSSCAST: self.rsscast,
            PROVIDER_KEY_QUICKTINY_MCP: self.quicktiny_mcp,
        }
        if provider_key not in mapping:
            raise RealProviderRequiresExplicitEnablementError(
                f"Unknown real Provider key {provider_key!r}; cannot resolve settings."
            )
        return mapping[provider_key]

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "ProviderSettings":
        provider_key = str(mapping.get("provider_key", PROVIDER_KEY_FIXTURE_DEV))
        return cls(
            provider_key=provider_key,
            akshare=AkshareProviderSettings.from_mapping(mapping.get("akshare", {})),
            cifang=CifangProviderSettings.from_mapping(mapping.get("cifang", {})),
            rsscast=RsscastProviderSettings.from_mapping(mapping.get("rsscast", {})),
            quicktiny_mcp=QuicktinyMcpProviderSettings.from_mapping(
                mapping.get("quicktiny_mcp", {})
            ),
        )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def default_provider_settings() -> ProviderSettings:
    """Build settings from the host environment without third-party SDKs.

    Reads from process environment only (``INVEST_PIPELINE_*``); never reaches
    out to any third-party data source. Production secrets stay in the
    deployment Secret store and are injected via ``INVEST_PIPELINE_*_TOKEN``
    vars at runtime; this loader never holds them in the repo.
    """

    import os

    def _str(name: str, default: str) -> str:
        value = os.environ.get(name)
        if value is None or value == "":
            return default
        return value

    def _bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(
                f"Environment variable {name}={raw!r} is not a float"
            ) from exc

    return ProviderSettings.from_mapping(
        {
            "provider_key": _str("INVEST_PIPELINE_PROVIDER_KEY", PROVIDER_KEY_FIXTURE_DEV),
            "akshare": {
                "enabled": _bool("INVEST_PIPELINE_AKSHARE_ENABLED", False),
                "token": _str("INVEST_PIPELINE_AKSHARE_TOKEN", ""),
                "base_url": _str(
                    "INVEST_PIPELINE_AKSHARE_BASE_URL", "https://example.invalid/akshare"
                ),
                "timeout_seconds": _float("INVEST_PIPELINE_AKSHARE_TIMEOUT_SECONDS", 10.0),
            },
            "cifang": {
                "enabled": _bool("INVEST_PIPELINE_CIFANG_ENABLED", False),
                "token": _str("INVEST_PIPELINE_CIFANG_TOKEN", ""),
                "base_url": _str(
                    "INVEST_PIPELINE_CIFANG_BASE_URL", "https://www.cifangquant.com/api"
                ),
                "adjustment": _str("INVEST_PIPELINE_CIFANG_ADJUSTMENT", ADJUSTMENT_NONE),
                "timeout_seconds": _float("INVEST_PIPELINE_CIFANG_TIMEOUT_SECONDS", 10.0),
            },
            "rsscast": {
                "enabled": _bool("INVEST_PIPELINE_RSSCAST_ENABLED", False),
                "token": _str("INVEST_PIPELINE_RSSCAST_TOKEN", ""),
                "timeout_seconds": _float("INVEST_PIPELINE_RSSCAST_TIMEOUT_SECONDS", 10.0),
            },
            "quicktiny_mcp": {
                "enabled": _bool("INVEST_PIPELINE_QUICKTINY_MCP_ENABLED", False),
                "token": _str("INVEST_PIPELINE_QUICKTINY_MCP_TOKEN", ""),
                "timeout_seconds": _float(
                    "INVEST_PIPELINE_QUICKTINY_MCP_TIMEOUT_SECONDS", 10.0
                ),
            },
        }
    )
