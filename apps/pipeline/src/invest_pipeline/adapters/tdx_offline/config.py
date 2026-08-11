"""Configuration for the TDX ``.day`` offline stock provider.

The settings object is intentionally narrow and **fail-closed**:

* ``enabled`` defaults to ``False``. A real offline read of the
  operator-managed ``vipdoc`` tree therefore requires an explicit
  opt-in via the ``INVEST_PIPELINE_TDX_OFFLINE_ENABLED`` environment
  variable. The default keeps the TDX adapter inert in CI / dev /
  tests so a stray fixture directory cannot leak into the daily-bars
  evidence model.
* ``data_root`` is the directory that contains the canonical
  ``vipdoc/{market}/lday/{market}{symbol}.day`` layout the TDX
  reader resolves against. It is **not** a credential, so it is a
  plain :class:`pathlib.Path` (no :class:`pydantic.SecretStr`).
* ``request_timeout`` and ``record_cap`` are explicit operational
  guards: ``request_timeout`` is a no-op today (the reader does
  not block on a network socket) but is kept in the contract so a
  future IO-aware adapter cannot regress the cap, and
  ``record_cap`` bounds the number of bars a single by-date fetch
  may produce — the upstream ``.day`` files can grow to tens of
  thousands of records and a future caller must not let a single
  offline read flood the sidecar.

The configuration object never reaches out to the network or the
filesystem; it is a pure value type that :class:`TdxOfflineStockProvider`
consumes. The provider refuses to construct (or to read) when
``enabled=False`` so the slice can land a catalog entry without
silently wiring the runtime.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from invest_pipeline.adapters.tdx_offline.reader import (
    DATASET_KEY,
    PROVIDER_KEY,
)

_KEY = PROVIDER_KEY
_DEFAULT_DATA_ROOT = Path("/var/lib/tdx/vipdoc")
_DEFAULT_RECORD_CAP = 10_000


class TdxOfflineSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the TDX offline provider.

    The fields mirror the documented Stage 4B Phase 5 contract. The
    settings object never opens the operator-managed ``vipdoc`` tree
    on its own; the provider reaches for :attr:`data_root` only when
    :attr:`enabled` is ``True`` and only inside an explicit fetch call.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_TDX_OFFLINE_",
        extra="ignore",
    )

    enabled: bool = False
    data_root: Path = _DEFAULT_DATA_ROOT
    record_cap: int = _DEFAULT_RECORD_CAP

    def model_post_init(self, __context: object) -> None:
        """Reject any obviously-malformed operator configuration.

        The constraint is enforced here (rather than as a Pydantic
        field validator) so the rejection message is explicit and
        cannot be bypassed by silent coercion. ``record_cap`` is the
        only knob that can shrink to zero and the cap is intentionally
        not negative.
        """

        if not isinstance(self.data_root, Path):
            raise ValueError(
                f"TdxOfflineSettings.data_root must be a pathlib.Path, "
                f"got {type(self.data_root).__name__}"
            )
        if self.record_cap < 0:
            raise ValueError(f"TdxOfflineSettings.record_cap must be >= 0, got {self.record_cap!r}")

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The helper exists so structured loggers and test assertions can
        introspect the configuration without ever materialising any
        operator path that might leak deployment detail. The path is
        rendered as ``"***"`` to keep the helper consistent with the
        Cifang / Tushare redaction policy (ADR-0010 §5 / §6).
        """

        return {
            "enabled": str(self.enabled),
            "data_root": "***",
            "record_cap": str(self.record_cap),
            "provider_key": _KEY,
            "dataset_key": DATASET_KEY,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, data_root='***', "
            f"record_cap={self.record_cap!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["TdxOfflineSettings"]
