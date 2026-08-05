"""Centralized, lazy provider credential lookup.

Explicit provider environment variables remain the highest-priority
override. When they are empty, credentials are read from one operator-owned
directory outside the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_SECRETS_DIR = Path("/home/claw/invest-secrets")
SECRETS_DIR_ENV = "INVEST_PIPELINE_SECRETS_DIR"

_CREDENTIAL_FILES = {
    "cifangquant": "cifangquant.api_key",
    "akshare": "akshare.token",
    "rsscast": "rsscast.token",
    "tushare": "tushare.token",
}


class CredentialStore:
    """Resolve provider credentials without exposing their values in errors."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root or Path(os.environ.get(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR))

    def path_for(self, provider_key: str) -> Path:
        try:
            filename = _CREDENTIAL_FILES[provider_key]
        except KeyError as exc:
            raise ValueError(f"unsupported credential provider {provider_key!r}") from exc
        return self.root / filename

    def resolve(self, provider_key: str, explicit_value: str = "") -> str:
        """Return an explicit value or the trimmed contents of its secret file."""

        if explicit_value:
            return explicit_value
        path = self.path_for(provider_key)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise RuntimeError(
                f"unable to read centralized credential for {provider_key} "
                f"from {path!s}: {type(exc).__name__}"
            ) from exc
        return value


__all__ = [
    "DEFAULT_SECRETS_DIR",
    "SECRETS_DIR_ENV",
    "CredentialStore",
]
