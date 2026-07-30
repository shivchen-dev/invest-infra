from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CifangAdapterConfig:
    """Redacted view of Cifang adapter runtime configuration.

    ARC-confirmed archive captured ``CIFANG_TOKEN`` plus a default base URL of
    ``https://www.cifangquant.com/api``. M0 freezes ``adjustment="none"`` so
    the old archive default of ``qfq`` is explicitly forbidden for v2.
    """

    token: str
    base_url: str
    adjustment: str
    timeout_seconds: float

    def sanitized_dict(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "adjustment": self.adjustment,
            "timeout_seconds": self.timeout_seconds,
        }

    def __repr__(self) -> str:
        return (
            "CifangAdapterConfig(token=<redacted>, base_url="
            f"{self.base_url!r}, adjustment={self.adjustment!r}, "
            f"timeout_seconds={self.timeout_seconds})"
        )
