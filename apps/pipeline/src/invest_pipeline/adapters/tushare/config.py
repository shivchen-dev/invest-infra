"""Tushare Pro adapter configuration (Phase 1 bounded increment).

Mirrors :class:`invest_pipeline.adapters.cifang.config.CifangSettings`
in shape and redaction rules; the wire details (single endpoint,
``POST`` JSON body, ``api_name`` dispatch) live in :mod:`client`.

Design rules:

- ``enabled`` defaults to ``False``; real network calls require an
  explicit opt-in via the ``INVEST_PIPELINE_TUSHARE_ENABLED`` environment
  variable (mirrors matrix §6 and ADR-0011 §3).
- ``adjust`` is locked to the literal ``"none"`` (ADR-0005 §4); any
  other value is rejected at construction time so the constraint
  cannot be loosened by environment configuration.
- ``token`` is a :class:`pydantic.SecretStr` so it is never exposed
  by the default Pydantic ``__repr__`` / ``__str__`` and cannot leak
  into logs, fixtures or exception messages (ADR-0010 §5 / §6). The
  explicit :meth:`__repr__` / :meth:`__str__` overrides below
  reaffirm the redaction so accidental ``format(settings)`` or log
  formatting cannot surface the token.
- The default ``token`` is empty; the client resolves it lazily from
  the centralized credential store. Operators may populate ``token``
  directly via ``INVEST_PIPELINE_TUSHARE_TOKEN`` as an override.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from invest_pipeline.credentials import CredentialStore

_ADJUST_NONE = "none"


class TushareSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for Tushare Pro.

    The fields mirror the documented Tushare Pro ``POST`` JSON
    contract: ``api_name`` (sent per request by the client),
    ``token`` (kept here only when the operator wants to bypass the
    centralized lookup), and ``adjust`` (locked to ``"none"``).

    The centralized secret is opened at request time only and only
    when ``token`` is empty. The settings object is therefore safe to
    construct in CI without credentials being present.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_TUSHARE_",
        extra="ignore",
    )

    enabled: bool = False
    token: SecretStr = SecretStr("")
    adjust: str = _ADJUST_NONE

    def model_post_init(self, __context: object) -> None:
        """Reject any non-``"none"`` adjust value.

        The constraint is enforced here (rather than as a Pydantic
        field validator) so the rejection message is explicit and
        cannot be bypassed by silent coercion.
        """

        if self.adjust != _ADJUST_NONE:
            raise ValueError(
                f"TushareSettings.adjust must be 'none' (ADR-0005 §4); got {self.adjust!r}"
            )

    def resolved_token(self) -> str:
        """Resolve the explicit token or the centralized secret file."""

        return CredentialStore().resolve("tushare", self.token.get_secret_value())

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The token is replaced with ``"***"`` so structured loggers and
        test assertions can introspect the rest of the configuration
        without ever materialising the secret.
        """

        return {
            "enabled": str(self.enabled),
            "token": "***" if self.token.get_secret_value() else "",
            "adjust": self.adjust,
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, token='***', adjust={self.adjust!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["TushareSettings"]
