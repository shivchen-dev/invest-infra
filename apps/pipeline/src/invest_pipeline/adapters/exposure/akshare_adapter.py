"""DC-3B AKShare exposure adapter (vertical slice).

The adapter is the boundary between the AKShare SDK / fixture and the
pure mapping layer in
:mod:`invest_pipeline.adapters.exposure.mapping`. It is intentionally
minimal:

* the adapter defaults to ``enabled=False`` and never reaches the
  network at construction or fetch when disabled;
* the AKShare client is injected through the
  :class:`AkShareExposureClientProtocol` so tests can drop in a fake
  client without monkey-patching or HTTP mocking;
* :meth:`AKShareExposureAdapter.fetch_standardized_payload` returns a
  plain dict payload (``AKShareExposurePayload``) or raises when
  disabled.

The adapter does not store, publish, or push anything anywhere. It is
a one-shot boundary controlled by an explicit ``enabled`` flag.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from invest_pipeline.adapters.errors import (
    RealProviderRequiresExplicitEnablementError,
)
from invest_pipeline.adapters.exposure.config import AKShareExposureConfig

DEFAULT_FIXTURE_NAME: str = "akshare_exposure_payload.json"

AKShareExposurePayload = dict
"""Runtime alias for the standardized payload mapping returned by
:meth:`AKShareExposureAdapter.fetch_standardized_payload`.

The actual value is a plain :class:`dict`; pointing the alias at the
built-in ``dict`` keeps :func:`isinstance` checks working against
unmodified payloads.
"""


def _canonical_fixture_path() -> Path:
    """Return the canonical DC-3B fixture path relative to the adapter source.

    The slice keeps a single source of truth for the JSON payload under
    ``apps/pipeline/tests/unit/fixtures/exposure/``. The adapter does
    not duplicate the file next to its source code; it walks upward
    from its package directory to discover the tests fixture.
    """

    package_dir = Path(__file__).resolve().parent
    for ancestor in (package_dir, *package_dir.parents):
        candidate = ancestor / "tests" / "unit" / "fixtures" / "exposure" / DEFAULT_FIXTURE_NAME
        if candidate.exists():
            return candidate
    return (
        package_dir.parents[3] / "tests" / "unit" / "fixtures" / "exposure" / DEFAULT_FIXTURE_NAME
    )


@runtime_checkable
class AkShareExposureClientProtocol(Protocol):
    """Minimal surface the adapter requires from an AKShare client.

    The concrete client implementation is owned by the existing
    AKShare adapter layer; the slice only requires a single
    ``fetch_exposure_payload`` call returning a dict payload that
    matches the standardized shape.
    """

    def fetch_exposure_payload(self) -> Mapping[str, Any]: ...


class AKShareExposureAdapter:
    """Adapter façade — does not touch the network when disabled."""

    def __init__(
        self,
        client: AkShareExposureClientProtocol | None = None,
        *,
        config: AKShareExposureConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or AKShareExposureConfig()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> AKShareExposureConfig:
        return self._config

    @property
    def client(self) -> AkShareExposureClientProtocol | None:
        return self._client

    @property
    def is_disabled(self) -> bool:
        return not self._config.enabled

    def fetch_standardized_payload(
        self,
        *,
        fixture_path: str | Path | None = None,
    ) -> AKShareExposurePayload:
        """Return the standardized payload or raise when disabled.

        When ``self.enabled`` is ``False`` (the default) the adapter
        refuses to call the injected client and raises
        :class:`RealProviderRequiresExplicitEnablementError` unless
        ``fixture_path`` is supplied.

        When ``fixture_path`` is supplied the adapter loads the
        fixture from disk and returns it verbatim. A relative path
        whose ``basename`` matches the canonical DC-3B fixture file
        resolves to the canonical location; arbitrary relative paths
        that do not exist on disk still raise
        :class:`FileNotFoundError`.
        """

        if not self.enabled:
            if fixture_path is None:
                raise RealProviderRequiresExplicitEnablementError(
                    "AKShare exposure adapter is disabled "
                    "(enabled=False); set enabled=True or pass a fixture_path"
                )
            return self._load_fixture(fixture_path)
        if self._client is None:
            raise RealProviderRequiresExplicitEnablementError(
                "AKShare exposure adapter is enabled but no client is injected"
            )
        return self._client.fetch_exposure_payload()

    def _resolve_fixture_path(self, fixture_path: str | Path) -> Path:
        path = Path(fixture_path)
        if path.exists():
            return path
        if path.name == DEFAULT_FIXTURE_NAME:
            canonical = _canonical_fixture_path()
            if canonical.exists():
                return canonical
        return path

    def _load_fixture(self, fixture_path: str | Path) -> dict[str, Any]:
        path = self._resolve_fixture_path(fixture_path)
        if not path.exists():
            raise FileNotFoundError(f"exposure fixture not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("exposure fixture must be a JSON object")
        return payload


def fetch_akshare_exposure_payload(
    adapter: AKShareExposureAdapter,
    *,
    fixture_path: str | Path | None = None,
) -> AKShareExposurePayload:
    """Convenience wrapper for ``adapter.fetch_standardized_payload``."""

    return adapter.fetch_standardized_payload(fixture_path=fixture_path)


__all__ = [
    "AKShareExposureAdapter",
    "AKShareExposurePayload",
    "AkShareExposureClientProtocol",
    "DEFAULT_FIXTURE_NAME",
    "fetch_akshare_exposure_payload",
]
