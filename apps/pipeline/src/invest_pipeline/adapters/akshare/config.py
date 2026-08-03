"""AkShare adapter configuration (PR-02, matrix §3 / §5.4 / §6).

The settings object mirrors the CifangQuant
:class:`~invest_pipeline.adapters.cifang.config.CifangSettings` shape but
opens the gate purely on the boolean ``enabled`` flag because AkShare's
public endpoints do not require an outbound API key for the documented
ETF functions (``fund_etf_fund_info_em`` / ``fund_etf_hist_em``). The
``adjust`` field is locked to the empty string (``""``) which is the
AkShare convention for "no adjustment" — AkShare uses empty ``adjust``
for unadjusted historical quotes and the v2 pipeline must reject any
other value at construction time so the legacy ``hfq`` / ``qfq`` defaults
from archive code can never sneak in (ADR-0005 §4).

Design rules:

- ``enabled`` defaults to ``False``; the adapter is opt-in only (matrix
  §6, ``INVEST_PIPELINE_AKSHARE_ENABLED`` env var).
- ``adjust`` is locked to ``""`` and any other value is rejected at
  construction time, mirroring the Cifang ``adjustment="none"`` lock.
- ``timeout_seconds`` defaults to a small bounded value; AkShare has no
  official rate-limit disclosure so we keep the budget small and let
  the runtime raise rather than burn minutes on a single request.
- No real secret is shipped; the optional ``token`` is a
  :class:`pydantic.SecretStr` so it stays out of ``repr`` / ``str`` /
  exception messages (ADR-0010 §5 / §6).
- The settings object never imports the ``akshare`` SDK at construction
  time; the optional dependency is checked lazily by the client so
  ``pip install invest-pipeline`` never fails purely because AkShare is
  absent.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADJUST_NONE = ""


class AkshareSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the AkShare adapter.

    The fields mirror the PR-02 contract: an explicit enablement boolean,
    a locked adjustment token and an optional redacted SDK token. The
    adapter refuses to call the underlying SDK while ``enabled`` is
    ``False`` (the default) so a missing deployment configuration cannot
    silently hit the network.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_AKSHARE_",
        extra="ignore",
    )

    enabled: bool = False
    token: SecretStr = SecretStr("")
    adjust: str = _ADJUST_NONE
    timeout_seconds: float = 30.0

    def model_post_init(self, __context: object) -> None:
        """Reject any non-empty ``adjust`` value at construction time.

        AkShare's official ``fund_etf_hist_em`` (and the variant aliases
        used by ``fund_etf_fund_info_em`` callers) treats the empty
        string as "no adjustment". The legacy archive defaults
        (``hfq`` / ``qfq``) must never reach the production path
        (ADR-0005 §4 / matrix §5.3); the lock is enforced here rather
        than as a Pydantic field validator so the rejection message
        is explicit.
        """

        if self.adjust != _ADJUST_NONE:
            raise ValueError(
                "AkshareSettings.adjust must be '' (the AkShare 'no "
                "adjustment' literal); ADR-0005 §4 forbids hfq / qfq "
                "reaching the production pipeline. "
                f"got {self.adjust!r}"
            )
        if self.timeout_seconds <= 0:
            raise ValueError(
                "AkshareSettings.timeout_seconds must be > 0; "
                f"got {self.timeout_seconds!r}"
            )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The optional SDK token is masked with ``"***"`` (or empty when
        the field is unset) so structured loggers and test assertions
        can introspect the rest of the configuration without ever
        materialising a secret.
        """

        return {
            "enabled": str(self.enabled),
            "token": "***" if self.token.get_secret_value() else "",
            "adjust": repr(self.adjust),
            "timeout_seconds": str(self.timeout_seconds),
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, "
            f"token='***', adjust={self.adjust!r}, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["AkshareSettings"]
