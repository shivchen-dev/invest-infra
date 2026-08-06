"""Static configuration for the AKShare exposure adapter.

The configuration is intentionally tiny: ``enabled`` defaults to
``False`` so accidental construction never reaches the network. The
adapter is a no-op while disabled and only consults an injected
client when ``enabled=True``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AKShareExposureConfig:
    """Adapter configuration.

    ``enabled`` is the kill-switch for live network access. The
    adapter refuses to call any client when ``enabled`` is ``False``.
    ``provider_key`` and ``dataset_key`` are non-empty strings that
    stamp the standardized payload; ``fixture_path`` and
    ``observed_at`` are optional convenience fields validated at
    construction so callers never accidentally hand an empty
    fixture path or a naive datetime to the adapter.
    """

    enabled: bool = False
    provider_key: str = "akshare"
    dataset_key: str = "exposure_bundle"
    fixture_path: str | Path | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError(f"enabled must be a bool, got {type(self.enabled).__name__}")
        if not isinstance(self.provider_key, str):
            raise TypeError(f"provider_key must be a str, got {type(self.provider_key).__name__}")
        if not self.provider_key.strip():
            raise ValueError("provider_key must not be empty")
        if not isinstance(self.dataset_key, str):
            raise TypeError(f"dataset_key must be a str, got {type(self.dataset_key).__name__}")
        if not self.dataset_key.strip():
            raise ValueError("dataset_key must not be empty")
        if self.fixture_path is not None:
            if isinstance(self.fixture_path, Path):
                fixture_text = str(self.fixture_path)
            elif isinstance(self.fixture_path, str):
                fixture_text = self.fixture_path
            else:
                raise TypeError(
                    "fixture_path must be a str, Path, or None, "
                    f"got {type(self.fixture_path).__name__}"
                )
            if not fixture_text.strip():
                raise ValueError("fixture_path must not be empty")
        if self.observed_at is not None:
            if not isinstance(self.observed_at, datetime):
                raise TypeError(
                    f"observed_at must be a datetime or None, got {type(self.observed_at).__name__}"
                )
            if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
                raise ValueError("observed_at must be timezone-aware")


__all__ = ["AKShareExposureConfig"]
