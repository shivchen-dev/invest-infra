"""RssCast MCP adapter configuration (PR-04, matrix §3 / §5.4 / §6).

The settings object freezes the RssCast MCP contract surfaced in
:doc:`docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md` §1 / §3 / §5.4
and the V1 archive
(``docs/archive/2026-08-02-stage1/invest-infra-v2-phase1-data-ingestion-plan.md``).
The adapter is research / index only — matrix §3 pins the role as
``out_of_scope_for_etf`` and matrix §5.4 plus the plan PR-01 "do not claim
ETF daily bars for RssCast" constraint forbid the adapter from
advertising ``ETF_DAILY_BARS`` — so the settings must never expose ETF /
index daily-bars fields and must keep the provider opt-in:

- ``enabled`` defaults to ``False`` (matrix §6,
  ``INVEST_PIPELINE_RSSCAST_ENABLED``). Real MCP traffic requires an
  explicit opt-in plus a non-empty ``token``.
- ``base_url`` is **not** shipped with a hard-coded default. Matrix §1
  records "归档未冻结固定端点" (the archive did not freeze a fixed
  endpoint) and matrix §5.4 forbids fabricating an internal URL. The
  default is therefore the empty string and operators must set
  ``INVEST_PIPELINE_RSSCAST_BASE_URL`` to the documented endpoint before
  enabling the adapter.
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

from invest_pipeline.credentials import CredentialStore

_DEFAULT_TIMEOUT_SECONDS = 30.0
_TIMEOUT_FLOOR_SECONDS = 0.0
_TIMEOUT_CEILING_SECONDS = 300.0


class RssCastMcpSettings(BaseSettings):
    """Redacted, disabled-by-default configuration for the RssCast MCP adapter.

    The fields mirror the PR-04 contract:

    - ``enabled`` — explicit opt-in for the real MCP transport. The
      adapter refuses to call :class:`RssCastMcpClient` while ``enabled``
      is ``False`` (the default). ``INVEST_PIPELINE_RSSCAST_ENABLED``.
    - ``base_url`` — the official MCP endpoint. The default is the
      empty string because matrix §1 explicitly does not freeze a fixed
      endpoint for RssCast; operators must set
      ``INVEST_PIPELINE_RSSCAST_BASE_URL`` before the adapter can be
      enabled. When set, the value must start with ``http://`` or
      ``https://`` so a misconfigured deployment cannot accidentally
      target an arbitrary scheme.
    - ``token`` — MCP bearer token. Stored as :class:`SecretStr` so the
      raw value never appears in ``repr`` / ``str`` / log payloads.
    - ``timeout_seconds`` — bounded request budget. Defaults to 30 s;
      must be in ``(0, 300]``.

    The settings object never imports ``httpx`` so module import remains
    free of network / SDK side effects.
    """

    model_config = SettingsConfigDict(
        env_prefix="INVEST_PIPELINE_RSSCAST_",
        extra="ignore",
    )

    enabled: bool = False
    base_url: str = ""
    token: SecretStr = SecretStr("")
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    def model_post_init(self, __context: object) -> None:
        """Reject malformed base URLs and out-of-range timeouts.

        The base URL is checked here rather than via a Pydantic field
        validator so the rejection message is explicit and the URL
        cannot be silently coerced to a default that masks a
        misconfiguration. The timeout bounds mirror the QuickTiny
        contract.
        """

        if not isinstance(self.base_url, str):
            raise ValueError(
                f"RssCastMcpSettings.base_url must be a string (got {type(self.base_url).__name__})"
            )
        if self.base_url:
            if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
                raise ValueError(
                    "RssCastMcpSettings.base_url must start with "
                    f"http:// or https://; got {self.base_url!r}"
                )
            normalised = self.base_url.rstrip("/")
            if normalised != self.base_url:
                object.__setattr__(self, "base_url", normalised)
        if not (_TIMEOUT_FLOOR_SECONDS < float(self.timeout_seconds) <= _TIMEOUT_CEILING_SECONDS):
            raise ValueError(
                "RssCastMcpSettings.timeout_seconds must be in "
                f"({_TIMEOUT_FLOOR_SECONDS}, {_TIMEOUT_CEILING_SECONDS}]; "
                f"got {self.timeout_seconds!r}"
            )

    def redacted_dict(self) -> dict[str, str]:
        """Return a logging-safe view of the configuration.

        The token is masked with ``"***"`` (or empty when unset) so
        structured loggers and test assertions can introspect the rest
        of the configuration without ever materialising the secret.
        The base URL is reported as-set; matrix §1 forbids baking a
        default, so an empty string here is the expected default.
        """

        return {
            "enabled": str(self.enabled),
            "base_url": self.base_url,
            "token": "***" if self.token.get_secret_value() else "",
            "timeout_seconds": str(self.timeout_seconds),
        }

    def resolved_token(self) -> str:
        """Resolve the explicit bearer token or the centralized secret file."""

        return CredentialStore().resolve("rsscast", self.token.get_secret_value())

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(enabled={self.enabled!r}, "
            f"base_url={self.base_url!r}, token='***', "
            f"timeout_seconds={self.timeout_seconds!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["RssCastMcpSettings"]
