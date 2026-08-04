"""Tonghuashun (同花顺) adapter configuration (three-provider plan, Phase 1).

The settings object mirrors the Eastmoney
:class:`~invest_pipeline.adapters.eastmoney.config.EastmoneySettings`
shape because Tonghuashun shares the documented "no adjustment"
contract on its public historical-quotes endpoint and the source is a
public, non-official endpoint with no documented API key.

Design rules:

- ``enabled`` defaults to ``False``; the adapter is opt-in only (matrix
  §6, ``INVEST_PIPELINE_TONGHUASHUN_ENABLED`` env var).
- ``adjustment`` is locked to the literal ``"none"`` so the legacy
  ``hfq`` / ``qfq`` adjustments from archive code cannot reach the
  production path (ADR-0005 §4 / three-provider plan §"Risks and
  Mitigations" "将 adjustment 作为显式请求参数和证据元数据，禁止
  静默转换").
- ``timeout_seconds`` defaults to a small bounded value; the upstream
  endpoints have no documented SLA so we keep the request budget
  small and let the runtime raise rather than burn minutes on a single
  request.
- No real secret is shipped; the public endpoint does not require an
  API key, so the settings intentionally expose **no** credential field.
- The settings object never imports ``httpx`` and never reaches the
  network; construction is pure data plumbing so ``import`` and module
  load stay free of side effects.

Phase 1 of the three-provider plan deliberately ships the configuration
skeleton only. The HTTP client, the field mapper and the evidence-tuple
adapter land in Phase 2.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

_ADJUSTMENT_NONE = "none"


class TonghuashunSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the Tonghuashun adapter.

    The fields mirror the three-provider plan Phase 1 contract: an
    explicit enablement boolean, a locked adjustment token and a bounded
    request timeout. The adapter (which Phase 2 adds) refuses to call
    the upstream while ``enabled`` is ``False`` (the default) so a
    misconfigured environment cannot accidentally hit the network.

    The public Tonghuashun endpoint does not require credentials, so
    the settings expose **no** credential field. The ``adjustment``
    lock is enforced here (rather than as a Pydantic field validator)
    so the rejection message is explicit and the value cannot be
    silently coerced.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_TONGHUASHUN_",
        extra="ignore",
    )

    enabled: bool = False
    adjustment: str = _ADJUSTMENT_NONE
    timeout_seconds: float = 30.0

    def model_post_init(self, __context: object) -> None:
        """Reject any non-``"none"`` adjustment value or non-positive timeout.

        The constraint mirrors the Cifang
        :class:`~invest_pipeline.adapters.cifang.config.CifangSettings`
        ``adjustment="none"`` rule. Tonghuashun uses ``"none"`` as the
        "no adjustment" literal on its public historical-quotes
        endpoint; the legacy ``hfq`` / ``qfq`` defaults from the
        archive must never reach the production path (ADR-0005 §4).
        """

        if self.adjustment != _ADJUSTMENT_NONE:
            raise ValueError(
                "TonghuashunSettings.adjustment must be 'none' "
                "(ADR-0005 §4 / three-provider plan §Risks); "
                f"got {self.adjustment!r}"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"TonghuashunSettings.timeout_seconds must be > 0; got {self.timeout_seconds!r}"
            )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The settings carry no credential, so the view is the raw
        dictionary with every field stringified. Callers can still
        introspect the configuration through this view without risk
        of leaking a secret.
        """

        return {
            "enabled": str(self.enabled),
            "adjustment": self.adjustment,
            "timeout_seconds": str(self.timeout_seconds),
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, "
            f"adjustment={self.adjustment!r}, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["TonghuashunSettings"]
