"""QuickTiny MCP adapter configuration (PR-03, matrix §3 / §5.4 / §6).

The settings object freezes the documented QuickTiny MCP contract surfaced
in :doc:`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §9.1 / §9.2
and the V1 archive (``docs/archive/2026-08-02-stage1/invest-infra-v2-
phase1-data-ingestion-plan.md``). The adapter is research-only
(``ProviderCapability.RESEARCH`` / ``MARKET_SNAPSHOT``) so the settings
must never expose ETF / index daily-bars fields and must keep the
provider opt-in:

- ``enabled`` defaults to ``False`` (matrix §6,
  ``INVEST_PIPELINE_QUICKTINY_MCP_ENABLED``). Real MCP traffic requires
  an explicit opt-in plus a non-empty ``token``.
- ``base_url`` defaults to ``https://stock.quicktiny.cn/api/mcp`` — the
  current official MCP endpoint documented in matrix §9.1; the legacy
  ``/api/mcp-stream`` URL is intentionally **not** exposed as an
  alternative here.
- ``token`` is a :class:`pydantic.SecretStr` so it never leaks into
  ``repr`` / ``str`` / log payloads (ADR-0010 §5 / §6).
- ``timeout_seconds`` is bounded and must be strictly positive so a
  misconfigured deployment cannot hang the pipeline.

The settings object never imports ``httpx``, never reaches the network
and never opens an MCP session. Construction is pure data plumbing so
``import`` and module load stay free of side effects.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_BASE_URL = "https://stock.quicktiny.cn/api/mcp"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_TIMEOUT_FLOOR_SECONDS = 0.0
_TIMEOUT_CEILING_SECONDS = 300.0


class QuickTinyMcpSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the QuickTiny MCP adapter.

    The fields mirror the PR-03 contract:

    - ``enabled`` — explicit opt-in for the real MCP transport. The
      adapter refuses to call :class:`QuickTinyMcpClient` while
      ``enabled`` is ``False`` (the default).
    - ``base_url`` — the official MCP endpoint. Default
      ``https://stock.quicktiny.cn/api/mcp`` per matrix §9.1.
    - ``token`` — MCP bearer token. Stored as :class:`SecretStr` so the
      raw value never appears in ``repr`` / ``str`` / log payloads.
    - ``timeout_seconds`` — bounded request budget. Defaults to 30 s;
      must be in ``(0, 300]``.

    The settings object never imports ``httpx`` so module import remains
    free of network / SDK side effects.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_QUICKTINY_MCP_",
        extra="ignore",
    )

    enabled: bool = False
    base_url: str = _DEFAULT_BASE_URL
    token: SecretStr = SecretStr("")
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def model_post_init(self, __context: object) -> None:
        """Reject malformed base URLs and out-of-range timeouts.

        The base URL is checked here rather than via a Pydantic field
        validator so the rejection message is explicit and the URL
        cannot be silently coerced to a default that masks a
        misconfiguration. The timeout bounds mirror the Cifang client
        contract.
        """

        if not isinstance(self.base_url, str) or not self.base_url:
            raise ValueError(
                "QuickTinyMcpSettings.base_url must be a non-empty string"
            )
        if not (
            self.base_url.startswith("http://")
            or self.base_url.startswith("https://")
        ):
            raise ValueError(
                "QuickTinyMcpSettings.base_url must start with http:// or "
                f"https://; got {self.base_url!r}"
            )
        # Strip trailing slashes so the client always composes a clean
        # "<base>/<endpoint>" URL without producing "//" separators.
        normalised = self.base_url.rstrip("/")
        if normalised != self.base_url:
            object.__setattr__(self, "base_url", normalised)
        if not (
            _TIMEOUT_FLOOR_SECONDS
            < float(self.timeout_seconds)
            <= _TIMEOUT_CEILING_SECONDS
        ):
            raise ValueError(
                "QuickTinyMcpSettings.timeout_seconds must be in "
                f"({_TIMEOUT_FLOOR_SECONDS}, {_TIMEOUT_CEILING_SECONDS}]; "
                f"got {self.timeout_seconds!r}"
            )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The token is masked with ``"***"`` (or empty when unset) so
        structured loggers and test assertions can introspect the rest
        of the configuration without ever materialising the secret.
        """

        return {
            "enabled": str(self.enabled),
            "base_url": self.base_url,
            "token": "***" if self.token.get_secret_value() else "",
            "timeout_seconds": str(self.timeout_seconds),
        }

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, "
            f"base_url={self.base_url!r}, token='***', "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["QuickTinyMcpSettings"]