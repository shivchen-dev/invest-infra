"""Unit tests for the Phase 1 CifangQuant placeholder adapter (ADR-0011).

The tests deliberately cover only what the first bounded increment is
supposed to guarantee: settings defaults, the ``adjustment=none`` lock,
API-key redaction, the ``provider_key`` and the
``ProviderAdapterNotImplementedError`` failure mode. No network call,
no PostgreSQL, no real token.

The package import path (``invest_pipeline.adapters.cifang``) is the
public surface frozen by ADR-0011 §1; the tests intentionally import
through the package entry point rather than reaching into the modules
directly so the public re-exports stay honest.
"""

from __future__ import annotations

import unittest
from datetime import date

from invest_pipeline.adapters import ProviderAdapterNotImplementedError
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)


class CifangSettingsTest(unittest.TestCase):
    """Defaults, ``adjustment`` lock and ``api_key`` redaction."""

    def test_defaults_disable_real_provider_and_lock_adjustment(self) -> None:
        settings = CifangSettings()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.adjustment, "none")
        # The default token must be empty so the placeholder never
        # accidentally carries a real secret into the wild.
        self.assertEqual(settings.api_key.get_secret_value(), "")

    def test_non_none_adjustment_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            CifangSettings(adjustment="qfq")
        message = str(ctx.exception)
        self.assertIn("adjustment", message)
        self.assertIn("none", message)
        self.assertIn("ADR-0005", message)

    def test_other_non_none_adjustment_is_also_rejected(self) -> None:
        # ``hfq`` was the other legacy default; both must be rejected.
        with self.assertRaises(ValueError):
            CifangSettings(adjustment="hfq")

    def test_api_key_is_secret_str(self) -> None:
        # Pydantic auto-coerces str values into SecretStr; confirm the
        # public attribute keeps the SecretStr wrapping.
        settings = CifangSettings(api_key="some-token")
        self.assertEqual(settings.api_key.get_secret_value(), "some-token")

    def test_repr_does_not_leak_token(self) -> None:
        settings = CifangSettings(api_key="super-secret-token")
        rendered = repr(settings)
        self.assertNotIn("super-secret-token", rendered)
        self.assertIn("***", rendered)

    def test_str_does_not_leak_token(self) -> None:
        settings = CifangSettings(api_key="another-token")
        rendered = str(settings)
        self.assertNotIn("another-token", rendered)
        self.assertIn("***", rendered)

    def test_redacted_dict_masks_api_key(self) -> None:
        settings = CifangSettings(api_key="mask-me")
        view = settings.redacted_dict()
        self.assertEqual(view["api_key"], "***")
        self.assertEqual(view["adjustment"], "none")
        self.assertEqual(view["enabled"], "False")

    def test_redacted_dict_uses_empty_string_for_unset_token(self) -> None:
        view = CifangSettings().redacted_dict()
        self.assertEqual(view["api_key"], "")


class CifangQuantAdapterTest(unittest.TestCase):
    """Placeholder shape, provider key and failure contract."""

    def test_provider_key_is_cifangquant(self) -> None:
        provider = CifangQuantInstrumentProvider()
        self.assertEqual(provider.provider_key, "cifangquant")

    def test_fetch_instruments_raises_not_implemented_with_adr_pointer(
        self,
    ) -> None:
        provider = CifangQuantInstrumentProvider()
        with self.assertRaises(ProviderAdapterNotImplementedError) as ctx:
            provider.fetch_instruments(date(2026, 7, 31))
        message = str(ctx.exception)
        # The exception is the canonical ``ProviderError`` subclass; it
        # must carry the ``cifangquant`` provider_key so the application
        # service can attribute the failure correctly.
        self.assertEqual(ctx.exception.provider_key, "cifangquant")
        # The message must point operators at ADR-0011 so they can find
        # the unresolved O-1 / O-3 / O-4 blockers.
        self.assertIn("ADR-0011", message)

    def test_fetch_daily_bars_raises_not_implemented_with_adr_pointer(
        self,
    ) -> None:
        provider = CifangQuantInstrumentProvider()
        with self.assertRaises(ProviderAdapterNotImplementedError) as ctx:
            provider.fetch_daily_bars(
                symbols=["510300", "510500"],
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 30),
            )
        self.assertEqual(ctx.exception.provider_key, "cifangquant")
        self.assertIn("ADR-0011", str(ctx.exception))

    def test_adapter_accepts_settings_but_does_not_call_network(self) -> None:
        # ``settings`` is accepted for symmetry with the future
        # second-increment injection point; the placeholder must not
        # touch the network or perform any I/O.
        settings = CifangSettings()
        provider = CifangQuantInstrumentProvider(settings)
        self.assertEqual(provider.provider_key, "cifangquant")
        # The settings object is held by reference (kept private) but
        # the placeholder does not surface it through public API.
        self.assertFalse(hasattr(provider, "settings"))


if __name__ == "__main__":
    unittest.main()