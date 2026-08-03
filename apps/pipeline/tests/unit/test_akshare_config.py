"""Unit tests for :class:`invest_pipeline.adapters.akshare.config.AkshareSettings`.

The settings object freezes the PR-02 / matrix §6 contract on the
AkShare adapter's runtime configuration:

- ``enabled`` defaults to ``False`` so the adapter is opt-in.
- ``adjust`` is locked to the empty string (``""``); any other value
  is rejected at construction time so the legacy ``hfq`` / ``qfq``
  defaults from archive code cannot reach the production path
  (ADR-0005 §4).
- ``timeout_seconds`` defaults to a small bounded value.
- ``token`` is a :class:`pydantic.SecretStr` so it never appears in
  ``repr`` / ``str`` / log payloads.
"""

from __future__ import annotations

import unittest

from invest_pipeline.adapters.akshare.config import AkshareSettings


class AkshareSettingsDefaultsTest(unittest.TestCase):
    """Defaults for the redacted settings object."""

    def test_enabled_defaults_to_false(self) -> None:
        # Matrix §6: real providers default to off. The default must
        # stay ``False`` so a misconfigured environment cannot
        # accidentally hit the network.
        settings = AkshareSettings()
        self.assertFalse(settings.enabled)

    def test_adjust_defaults_to_empty_string(self) -> None:
        # AkShare's "no adjustment" literal is the empty string. The
        # default must match what ``fund_etf_hist_em`` expects so a
        # caller who never reads the env vars still produces
        # adjustment-free bars.
        settings = AkshareSettings()
        self.assertEqual(settings.adjust, "")

    def test_token_defaults_to_empty_secret(self) -> None:
        # No real secret is shipped; the default token must be empty
        # so the adapter never accidentally carries a real secret.
        settings = AkshareSettings()
        self.assertEqual(settings.token.get_secret_value(), "")

    def test_timeout_seconds_defaults_to_a_positive_value(self) -> None:
        # A default timeout must be set so a caller that never reads
        # the env still gets a bounded request budget. The exact value
        # is part of the documented contract; assert it's positive and
        # finite.
        settings = AkshareSettings()
        self.assertGreater(settings.timeout_seconds, 0)
        self.assertLessEqual(settings.timeout_seconds, 300.0)


class AkshareSettingsAdjustmentLockTest(unittest.TestCase):
    """The ``adjust`` lock mirrors the Cifang ``adjustment="none"`` rule."""

    def test_non_empty_adjust_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AkshareSettings(adjust="qfq")
        message = str(ctx.exception)
        self.assertIn("adjust", message)
        self.assertIn("ADR-0005", message)

    def test_hfq_adjust_is_rejected(self) -> None:
        # ``hfq`` was the other archive default; both must be
        # rejected. The lock is the same one Cifang enforces on
        # ``adjustment``.
        with self.assertRaises(ValueError):
            AkshareSettings(adjust="hfq")

    def test_none_adjust_is_rejected(self) -> None:
        # The AkShare literal for "no adjustment" is the empty
        # string. Passing ``"none"`` (the Cifang literal) must not be
        # silently coerced.
        with self.assertRaises(ValueError):
            AkshareSettings(adjust="none")


class AkshareSettingsTimeoutTest(unittest.TestCase):
    """``timeout_seconds`` must be a positive float."""

    def test_zero_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            AkshareSettings(timeout_seconds=0)
        self.assertIn("timeout_seconds", str(ctx.exception))

    def test_negative_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AkshareSettings(timeout_seconds=-1.0)


class AkshareSettingsRedactionTest(unittest.TestCase):
    """``token`` is redacted from repr / str / redacted_dict."""

    def test_repr_does_not_leak_token(self) -> None:
        settings = AkshareSettings(token="super-secret-akshare-token")
        rendered = repr(settings)
        self.assertNotIn("super-secret-akshare-token", rendered)
        self.assertIn("***", rendered)

    def test_str_does_not_leak_token(self) -> None:
        settings = AkshareSettings(token="another-akshare-token")
        rendered = str(settings)
        self.assertNotIn("another-akshare-token", rendered)
        self.assertIn("***", rendered)

    def test_redacted_dict_masks_token(self) -> None:
        settings = AkshareSettings(token="mask-me-now")
        view = settings.redacted_dict()
        self.assertEqual(view["token"], "***")
        self.assertEqual(view["adjust"], "''")
        self.assertEqual(view["enabled"], "False")
        self.assertIn("timeout_seconds", view)

    def test_redacted_dict_uses_empty_string_for_unset_token(self) -> None:
        view = AkshareSettings().redacted_dict()
        self.assertEqual(view["token"], "")


if __name__ == "__main__":
    unittest.main()
