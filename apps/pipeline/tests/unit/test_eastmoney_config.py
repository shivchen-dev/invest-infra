"""Unit tests for :class:`invest_pipeline.adapters.eastmoney.config.EastmoneySettings`.

Phase 1 of the V2 three-provider plan
(``tasks/plan-data-source-three-provider.md``) freezes the Eastmoney
adapter configuration contract. The settings object is intentionally
narrow — it captures only the documented safety rules in ADR-0005 §4
and the plan §"Risks and Mitigations" table. The tests assert:

- ``enabled`` defaults to ``False`` so the adapter is opt-in only
  (matrix §6).
- ``adjustment`` is locked to the literal ``"none"``; any other value
  is rejected at construction time so the legacy ``hfq`` / ``qfq``
  defaults from archive code cannot reach the production path
  (ADR-0005 §4).
- ``timeout_seconds`` defaults to a small bounded value and rejects
  non-positive values.
- No real secret is shipped; the public endpoint does not require a
  credential, so the settings intentionally expose **no** credential
  field. ``redacted_dict`` is therefore the raw field view.
- Construction never touches the network; the module is importable
  without the optional ``httpx`` transport.
"""

from __future__ import annotations

import unittest

from invest_pipeline.adapters.eastmoney.config import EastmoneySettings


class EastmoneySettingsDefaultsTest(unittest.TestCase):
    """Defaults for the redacted settings object."""

    def test_enabled_defaults_to_false(self) -> None:
        # Matrix §6: real providers default to off. The default must
        # stay ``False`` so a misconfigured environment cannot
        # accidentally hit the network.
        settings = EastmoneySettings()
        self.assertFalse(settings.enabled)

    def test_adjustment_defaults_to_none(self) -> None:
        # The "no adjustment" literal is ``"none"`` (the same value
        # Cifang uses). The default must match so a caller who never
        # reads the env vars still produces adjustment-free bars.
        settings = EastmoneySettings()
        self.assertEqual(settings.adjustment, "none")

    def test_timeout_seconds_defaults_to_a_positive_value(self) -> None:
        # A default timeout must be set so a caller that never reads
        # the env still gets a bounded request budget. The exact value
        # is part of the documented contract; assert it's positive and
        # finite.
        settings = EastmoneySettings()
        self.assertGreater(settings.timeout_seconds, 0)
        self.assertLessEqual(settings.timeout_seconds, 300.0)


class EastmoneySettingsAdjustmentLockTest(unittest.TestCase):
    """The ``adjustment`` lock mirrors the Cifang ``adjustment="none"`` rule."""

    def test_non_none_adjustment_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            EastmoneySettings(adjustment="qfq")
        message = str(ctx.exception)
        self.assertIn("adjustment", message)
        self.assertIn("ADR-0005", message)

    def test_hfq_adjustment_is_rejected(self) -> None:
        # ``hfq`` was one of the legacy archive defaults; it must be
        # rejected at construction time so the lock cannot be
        # bypassed by environment configuration.
        with self.assertRaises(ValueError):
            EastmoneySettings(adjustment="hfq")

    def test_empty_adjustment_is_rejected(self) -> None:
        # The Eastmoney "no adjustment" literal is the string
        # ``"none"``. The empty string (AkShare's "no adjustment"
        # literal) must not be silently coerced.
        with self.assertRaises(ValueError):
            EastmoneySettings(adjustment="")


class EastmoneySettingsTimeoutTest(unittest.TestCase):
    """``timeout_seconds`` must be a positive float."""

    def test_zero_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            EastmoneySettings(timeout_seconds=0)
        self.assertIn("timeout_seconds", str(ctx.exception))

    def test_negative_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EastmoneySettings(timeout_seconds=-1.0)


class EastmoneySettingsRedactionTest(unittest.TestCase):
    """``redacted_dict`` returns the logging-safe view of the configuration."""

    def test_redacted_dict_exposes_every_field(self) -> None:
        # The public endpoint does not require a credential, so the
        # logging-safe view is the raw field view. Operators reading
        # structured logs can introspect the configuration through
        # this helper without risk of leaking a secret.
        view = EastmoneySettings().redacted_dict()
        self.assertEqual(set(view.keys()), {"enabled", "adjustment", "timeout_seconds"})
        self.assertEqual(view["enabled"], "False")
        self.assertEqual(view["adjustment"], "none")
        self.assertIn("timeout_seconds", view)

    def test_redacted_dict_reflects_overrides(self) -> None:
        # When the caller sets ``enabled=True`` (the operator-facing
        # opt-in path) the redacted view must reflect that, so log
        # consumers can audit the configuration a real run used.
        settings = EastmoneySettings(enabled=True)
        view = settings.redacted_dict()
        self.assertEqual(view["enabled"], "True")


class EastmoneySettingsImportSafetyTest(unittest.TestCase):
    """Construction must be side-effect free."""

    def test_importing_config_does_not_import_httpx(self) -> None:
        # The configuration skeleton is the only Phase 1 module; it
        # must never import ``httpx`` so the package is importable in
        # CI / local dev without the optional HTTP transport. The
        # invariant is asserted via the module's ``__dict__`` rather
        # than a runtime check so a maintainer who accidentally adds
        # an ``import httpx`` at module top-level surfaces here.
        import sys

        import invest_pipeline.adapters.eastmoney.config as config_module

        self.assertFalse(hasattr(config_module, "httpx"))
        self.assertNotIn("httpx", sys.modules.get(config_module.__name__, object()).__dict__)


if __name__ == "__main__":
    unittest.main()
