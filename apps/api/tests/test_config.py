"""Tests for :mod:`invest_api.config`.

Pins the CORS default-value contract so the documented public Web port
(``3001``) plus the local Vite dev port (``5173``) are always accepted
when the API process has no explicit ``API_CORS_ORIGINS`` override —
which is the case for the user-level systemd unit. The overrides path
is also locked down so a misconfigured env var can silently regress back
to a narrower allow-list.

Tests construct :class:`Settings` directly and never call
:func:`get_settings` (or clear its ``lru_cache``) so the singleton held
by :mod:`invest_api.main` stays untouched across the suite.
"""

from __future__ import annotations

from invest_api.config import Settings
from pydantic_settings import SettingsConfigDict


def _new_settings(env_file: str | None = None) -> Settings:
    """Build an isolated :class:`Settings` instance.

    A dedicated subclass disables env-file lookup so the test does not
    depend on the presence (or absence) of an ``apps/api/.env`` next to
    the working directory — only the explicit ``os.environ`` mutations
    done by the test itself are honoured.
    """

    class _IsolatedSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=env_file,
            extra="ignore",
        )

    return _IsolatedSettings()


class TestDefaultCorsOrigins:
    """No ``API_CORS_ORIGINS`` set → both the public (3001) and local
    Vite (5173) origins are accepted on the localhost and 127.0.0.1
    hostnames."""

    def test_default_origins_include_public_web_port(self, monkeypatch) -> None:
        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

        settings = _new_settings()

        assert "http://localhost:3001" in settings.cors_origins
        assert "http://127.0.0.1:3001" in settings.cors_origins

    def test_default_origins_include_local_vite_port(self, monkeypatch) -> None:
        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

        settings = _new_settings()

        assert "http://localhost:5173" in settings.cors_origins
        assert "http://127.0.0.1:5173" in settings.cors_origins

    def test_default_origins_are_four_distinct_entries(self, monkeypatch) -> None:
        monkeypatch.delenv("API_CORS_ORIGINS", raising=False)

        settings = _new_settings()

        assert settings.cors_origins == [
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]


class TestExplicitCorsOriginsOverride:
    """An explicit ``API_CORS_ORIGINS`` env var is authoritative and
    replaces the default allow-list."""

    def test_explicit_override_replaces_default(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "API_CORS_ORIGINS",
            "https://app.example.test,https://app.example.test:443",
        )

        settings = _new_settings()

        assert settings.cors_origins == [
            "https://app.example.test",
            "https://app.example.test:443",
        ]

    def test_explicit_override_strips_whitespace(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "API_CORS_ORIGINS",
            " http://a.test ,http://b.test ",
        )

        settings = _new_settings()

        assert settings.cors_origins == ["http://a.test", "http://b.test"]


__all__ = [
    "TestDefaultCorsOrigins",
    "TestExplicitCorsOriginsOverride",
]
