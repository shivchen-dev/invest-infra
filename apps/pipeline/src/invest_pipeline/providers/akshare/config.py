from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AkshareAdapterConfig:
    """Redacted view of AkShare adapter runtime configuration.

    Only environment-bound fields are exposed. ``token`` is never logged,
    repr'd, or echoed. The endpoint value is a placeholder: ARC noted
    historical rate-limit / blocking events against AkShare; per ADR-0003
    selection is unfrozen and the real endpoint must be confirmed by O-1.
    """

    token: str
    base_url: str
    timeout_seconds: float

    def sanitized_dict(self) -> dict[str, object]:
        """Return a structure safe for logging / test snapshots.

        The ``token`` field is intentionally dropped. Callers must never
        log the original config object directly.
        """

        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
        }

    def __repr__(self) -> str:
        return (
            "AkshareAdapterConfig(token=<redacted>, base_url="
            f"{self.base_url!r}, timeout_seconds={self.timeout_seconds})"
        )
