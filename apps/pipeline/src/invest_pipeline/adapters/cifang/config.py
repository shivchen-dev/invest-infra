"""CifangQuant adapter configuration (ADR-0011, Phase 1 first increment).

The settings object is intentionally narrow: it captures only the
documented official facts in ADR-0011 §2 and the redaction rules in
ADR-0010 §5 / §6. It does **not** import the HTTP client or the mapper
that Phase 1 second-increment will add once O-1 / O-3 / O-4 are closed.

Design rules:

- ``enabled`` defaults to ``False``; real network calls require an
  explicit opt-in via the ``INVEST_PIPELINE_CIFANG_ENABLED`` environment
  variable (ADR-0003 §8, ADR-0011 §3).
- ``adjustment`` is locked to the literal ``"none"`` (ADR-0005 §4);
  any other value is rejected at construction time so the constraint
  cannot be loosened by environment configuration.
- ``api_key`` is a :class:`pydantic.SecretStr` so it is never exposed by
  the default Pydantic ``__repr__`` / ``__str__`` and cannot leak into
  logs, fixtures or exception messages (ADR-0010 §5 / §6). The explicit
  :meth:`__repr__` / :meth:`__str__` overrides below reaffirm the
  redaction so accidental ``format(settings)`` or log formatting cannot
  surface the token.
- No real secret is shipped; the default ``api_key`` is empty and is
  only populated via the ``INVEST_PIPELINE_CIFANG_API_KEY`` environment
  variable. The settings object never reaches out to the network.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADJUSTMENT_NONE = "none"


class CifangSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for CifangQuant.

    The fields mirror the documented Phase 1 contract in ADR-0011 §2.
    Phase 1 second-increment may extend the model with ``base_url``,
    timeout and bounded retry settings, but must keep ``enabled`` off
    by default and must keep ``adjustment`` locked to ``none``.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_CIFANG_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = False
    api_key: SecretStr = SecretStr("")
    adjustment: str = _ADJUSTMENT_NONE

    def model_post_init(self, __context: object) -> None:
        """Reject any non-``"none"`` adjustment value.

        The constraint is enforced here (rather than as a Pydantic
        field validator) so the rejection message is explicit and
        cannot be bypassed by silent coercion. ``adjustment`` is
        intentionally typed as ``str`` to keep the surface flat and to
        match the ``adjust`` query parameter the official API exposes.
        """

        if self.adjustment != _ADJUSTMENT_NONE:
            raise ValueError(
                "CifangSettings.adjustment must be 'none' "
                "(ADR-0005 §4 / ADR-0011 §3); "
                f"got {self.adjustment!r}"
            )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The token is replaced with ``"***"`` so structured loggers and
        test assertions can introspect the rest of the configuration
        without ever materializing the secret.
        """

        return {
            "enabled": str(self.enabled),
            "api_key": "***" if self.api_key.get_secret_value() else "",
            "adjustment": self.adjustment,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, "
            f"api_key='***', adjustment={self.adjustment!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["CifangSettings"]