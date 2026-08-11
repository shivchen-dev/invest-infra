"""Unit tests for the PR-1A provider factory.

The factory is a thin slice of runtime provider selection; the tests
cover every branch documented in
:mod:`invest_pipeline.provider_factory`:

* ``fixture_dev`` -> :class:`FixtureDevInstrumentProvider`.
* ``cifangquant`` (enabled + key) -> :class:`CifangQuantInstrumentProvider`.
* ``cifangquant`` (disabled) -> :class:`RealProviderRequiresExplicitEnablementError`.
* ``cifangquant`` (empty key) -> :class:`ProviderAuthenticationError`.
* Unknown key -> :class:`UnknownProviderError` carrying the offending key.
* Catalog-declared but non-runtime providers (for example ``rsscast``
  / ``quicktiny_mcp`` / ``hithink``) also raise
  :class:`UnknownProviderError` because the factory validates the
  selected key against the catalog-derived :data:`KNOWN_PROVIDER_KEYS`
  *before* any adapter branch runs (GOV-04). ``hithink`` is the
  reserved-provider slice (see
  ``tasks/hithink-reserved-provider-plan.md``); it ships without a
  runtime factory adapter and must therefore fail the upfront
  runtime gate just like the MCP research sources.
* Construction never reaches the network.

Tests always pass an explicit :class:`Settings` (and, for cifang,
an explicit :class:`CifangSettings`) so the suite is hermetic and
does not depend on the host's ``.env`` file or the ``lru_cache``-d
:func:`get_settings`. API-key material is also strictly fictional —
no real or recognizable token is ever embedded in test data.
"""

from __future__ import annotations

import unittest

from invest_pipeline.adapters import (
    FixtureDevInstrumentProvider,
    RealProviderRequiresExplicitEnablementError,
    UnknownProviderError,
)
from invest_pipeline.adapters.cifang import (
    CifangQuantInstrumentProvider,
    CifangSettings,
)
from invest_pipeline.adapters.errors import ProviderAuthenticationError
from invest_pipeline.config import Settings
from invest_pipeline.provider_catalog import runtime_supported_provider_keys
from invest_pipeline.provider_factory import KNOWN_PROVIDER_KEYS, build_provider

# Sentinel token used to verify construction succeeds with a populated
# key. Chosen to be obviously fictional so it cannot accidentally match a
# real secret in a future regression; the tests also assert the literal
# never appears in any error message.
_CIFANG_TEST_TOKEN = "ci-test-token-not-a-real-secret"


class DefaultBehaviorTest(unittest.TestCase):
    """``fixture_dev`` is the only supported default in this increment."""

    def test_default_settings_provider_key_is_fixture_dev(self) -> None:
        # The pydantic default is the deterministic fixture; this guards
        # against a future refactor that accidentally flips the default
        # to ``cifangquant`` (which would silently fail every test that
        # never set the env var).
        settings = Settings()
        self.assertEqual(settings.provider_key, "fixture_dev")

    def test_default_provider_key_environment_alias_is_invest_pipeline(self) -> None:
        # ``validation_alias`` must keep the public env-var name frozen
        # so the docs / .env.example / operators all agree. The alias
        # is an ``AliasChoices`` that also accepts the Python field name
        # so callers can construct :class:`Settings` directly in tests.
        from pydantic import AliasChoices

        field = Settings.model_fields["provider_key"]
        self.assertEqual(
            field.validation_alias,
            AliasChoices("INVEST_PIPELINE_PROVIDER_KEY", "provider_key"),
        )

    def test_known_provider_keys_match_catalog_runtime_support(self) -> None:
        # The factory now derives its public ``KNOWN_PROVIDER_KEYS``
        # tuple from the catalog's
        # :func:`invest_pipeline.provider_catalog.runtime_supported_provider_keys`
        # helper so the catalog is the single declaration authority
        # (GOV-04). This test pins the public tuple's *contents* (the
        # four runtime-backed providers) without depending on the
        # historical declaration order — a future alphabetical
        # re-sort or catalog re-order must not silently drift the
        # factory's supported set. The runtime behaviour for each
        # branch is verified in this file and in
        # ``test_akshare_adapter.py``.
        from invest_pipeline.provider_catalog import (
            AKSHARE,
            CIFANGQUANT,
            FIXTURE_DEV,
            TUSHARE,
            runtime_supported_provider_keys,
        )

        self.assertEqual(
            set(KNOWN_PROVIDER_KEYS),
            {
                FIXTURE_DEV.provider_key,
                CIFANGQUANT.provider_key,
                AKSHARE.provider_key,
                TUSHARE.provider_key,
            },
        )
        # The factory tuple must mirror the catalog helper
        # exactly — both as a set and as an ordered tuple — so any
        # future helper-side reorder surfaces here immediately.
        self.assertEqual(KNOWN_PROVIDER_KEYS, runtime_supported_provider_keys())


class FixtureDevBranchTest(unittest.TestCase):
    """``fixture_dev`` returns the deterministic fixture provider."""

    def test_explicit_fixture_dev_returns_fixture_dev_provider(self) -> None:
        provider = build_provider(Settings(provider_key="fixture_dev"))
        self.assertIsInstance(provider, FixtureDevInstrumentProvider)

    def test_explicit_fixture_dev_provider_key(self) -> None:
        provider = build_provider(Settings(provider_key="fixture_dev"))
        self.assertEqual(provider.provider_key, "fixture_dev")

    def test_fixture_dev_branch_does_not_require_settings_argument(self) -> None:
        # The factory accepts a positional ``Settings`` and uses keyword
        # arguments for the optional cifang seam; passing a Settings
        # without any kwargs is the canonical call shape.
        provider = build_provider(Settings(provider_key="fixture_dev"))
        self.assertIsNotNone(provider)


class CifangBranchHappyPathTest(unittest.TestCase):
    """``cifangquant`` with the gate satisfied returns the real adapter."""

    def test_cifangquant_enabled_with_api_key_returns_adapter(self) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key=_CIFANG_TEST_TOKEN)
        provider = build_provider(settings, cifang_settings=cifang)
        self.assertIsInstance(provider, CifangQuantInstrumentProvider)

    def test_cifangquant_provider_key_is_cifangquant(self) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key=_CIFANG_TEST_TOKEN)
        provider = build_provider(settings, cifang_settings=cifang)
        self.assertEqual(provider.provider_key, "cifangquant")

    def test_cifangquant_passes_cifang_settings_to_adapter(self) -> None:
        # The adapter must receive the *same* CifangSettings instance
        # the factory validated so the runtime gate (``enabled`` /
        # ``api_key``) stays authoritative.
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key=_CIFANG_TEST_TOKEN)
        provider = build_provider(settings, cifang_settings=cifang)
        self.assertIs(provider._settings, cifang)


class CifangBranchGateTest(unittest.TestCase):
    """``cifangquant`` rejects disabled or empty-key requests without fallback."""

    def test_cifangquant_disabled_raises_real_provider_error(self) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=False, api_key=_CIFANG_TEST_TOKEN)
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            build_provider(settings, cifang_settings=cifang)
        # Operators must still be pointed at ADR-0011 so the O-1 / O-3 /
        # O-4 blockers stay visible.
        self.assertIn("ADR-0011", str(ctx.exception))

    def test_cifangquant_disabled_does_not_fall_back_to_fixture(self) -> None:
        # The factory must not silently return the fixture provider
        # when the cifang gate fails — that would mask the
        # misconfiguration behind ``fixture_dev`` data.
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=False, api_key=_CIFANG_TEST_TOKEN)
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            build_provider(settings, cifang_settings=cifang)

    def test_cifangquant_disabled_with_no_api_key_still_raises_real_provider_error(
        self,
    ) -> None:
        # When both gates fail, the ``enabled`` gate wins because the
        # factory checks it first; the message must still surface
        # ADR-0011 so the operator does not chase a phantom credential
        # issue first.
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=False, api_key="")
        with self.assertRaises(RealProviderRequiresExplicitEnablementError):
            build_provider(settings, cifang_settings=cifang)

    def test_cifangquant_enabled_but_empty_api_key_raises_authentication_error(
        self,
    ) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key="")
        with self.assertRaises(ProviderAuthenticationError):
            build_provider(settings, cifang_settings=cifang)

    def test_cifangquant_empty_api_key_does_not_fall_back_to_fixture(self) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key="")
        with self.assertRaises(ProviderAuthenticationError):
            build_provider(settings, cifang_settings=cifang)

    def test_authentication_error_message_does_not_embed_caller_token(self) -> None:
        # When the gate fails on an empty token, the factory raises
        # ``ProviderAuthenticationError`` with a canonical message.
        # The error text must not echo the caller-supplied (empty)
        # token and must still point operators at ADR-0011 so they
        # know how to resolve the gate.
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key="")
        with self.assertRaises(ProviderAuthenticationError) as ctx:
            build_provider(settings, cifang_settings=cifang)
        message = str(ctx.exception)
        self.assertIn("INVEST_PIPELINE_CIFANG_API_KEY", message)
        self.assertIn("ADR-0011", message)

    def test_real_provider_error_message_never_includes_token(self) -> None:
        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=False, api_key="must-not-leak-token")
        with self.assertRaises(RealProviderRequiresExplicitEnablementError) as ctx:
            build_provider(settings, cifang_settings=cifang)
        self.assertNotIn("must-not-leak-token", str(ctx.exception))


class UnknownKeyTest(unittest.TestCase):
    """Anything outside the runtime-supported set is rejected."""

    def test_unknown_provider_key_raises_unknown_provider_error(self) -> None:
        settings = Settings(provider_key="not_a_real_provider")
        with self.assertRaises(UnknownProviderError):
            build_provider(settings)

    def test_unknown_provider_error_carries_offending_key(self) -> None:
        # ``UnknownProviderError`` is a ``KeyError`` subclass; the
        # requested key must be the first argument so callers can
        # introspect it without parsing the message string. ``akshare``
        # is intentionally NOT used here any more — PR-02 added it as
        # a gated third factory branch (matrix §6), so a non-registered
        # key is needed to exercise the unknown-key path.
        settings = Settings(provider_key="not_a_real_provider")
        with self.assertRaises(UnknownProviderError) as ctx:
            build_provider(settings)
        self.assertEqual(ctx.exception.args[0], "not_a_real_provider")

    def test_empty_provider_key_is_unknown(self) -> None:
        settings = Settings(provider_key="")
        with self.assertRaises(UnknownProviderError):
            build_provider(settings)

    def test_mixed_case_provider_key_is_unknown(self) -> None:
        # Provider keys are case-sensitive; ``Fixture_Dev`` must not
        # silently match ``fixture_dev``.
        settings = Settings(provider_key="Fixture_Dev")
        with self.assertRaises(UnknownProviderError):
            build_provider(settings)

    def test_unknown_key_does_not_fall_back_to_fixture(self) -> None:
        settings = Settings(provider_key="totally_made_up")
        with self.assertRaises(UnknownProviderError):
            build_provider(settings)


class CatalogDeclaredNonRuntimeProviderRejectionTest(unittest.TestCase):
    """GOV-04: catalog-declared but non-runtime providers are rejected.

    The provider catalog (PR-01) declares six providers so the routing
    layer and coverage reports can reason about every V2 data source.
    Two of those declarations (``rsscast`` and ``quicktiny_mcp``) are
    MCP research sources with no runtime factory adapter: they must
    not enter the runtime selection surface. The reserved-provider
    slice additionally adds ``hithink`` as a catalog-only,
    disabled-by-default entry that also has no runtime factory
    adapter. The factory validates the selected key against
    :data:`invest_pipeline.provider_catalog.runtime_supported_provider_keys`
    before any adapter branch runs, so picking one of them raises the
    same :class:`UnknownProviderError` a completely unknown key does.
    """

    def test_rsscast_provider_key_raises_unknown_provider_error(self) -> None:
        settings = Settings(provider_key="rsscast")
        with self.assertRaises(UnknownProviderError) as ctx:
            build_provider(settings)
        self.assertEqual(ctx.exception.args[0], "rsscast")

    def test_quicktiny_mcp_provider_key_raises_unknown_provider_error(self) -> None:
        settings = Settings(provider_key="quicktiny_mcp")
        with self.assertRaises(UnknownProviderError) as ctx:
            build_provider(settings)
        self.assertEqual(ctx.exception.args[0], "quicktiny_mcp")

    def test_hithink_provider_key_raises_unknown_provider_error(self) -> None:
        # Reserved-provider slice: ``hithink`` is visible in the
        # catalog but has no runtime factory adapter, so the factory
        # must reject it through the same
        # :class:`UnknownProviderError` path the MCP research sources
        # use. The exception carries the offending key as its first
        # argument so callers can self-diagnose without parsing the
        # message string.
        settings = Settings(provider_key="hithink")
        with self.assertRaises(UnknownProviderError) as ctx:
            build_provider(settings)
        self.assertEqual(ctx.exception.args[0], "hithink")

    def test_every_catalog_declared_non_runtime_key_is_rejected(self) -> None:
        # Drive the factory with every key that exists in the catalog
        # but is **not** part of the runtime-supported set. None of
        # them should reach an adapter branch — they all fail the
        # upfront runtime gate.
        from invest_pipeline.provider_catalog import (
            HITHINK,
            QUICKTINY_MCP,
            RSSCAST,
            TDX_OFFLINE,
            iter_provider_declarations,
            runtime_supported_provider_keys,
        )

        runtime_keys = set(runtime_supported_provider_keys())
        non_runtime_keys = [
            declaration.provider_key
            for declaration in iter_provider_declarations()
            if declaration.provider_key not in runtime_keys
        ]
        # The catalog currently has four non-runtime declarations
        # (``rsscast`` / ``quicktiny_mcp`` / ``hithink`` / ``tdx_offline``);
        # the assertion protects against a future regression that adds a
        # fifth without a test covering it.
        self.assertEqual(
            sorted(non_runtime_keys),
            sorted(
                [
                    HITHINK.provider_key,
                    QUICKTINY_MCP.provider_key,
                    RSSCAST.provider_key,
                    TDX_OFFLINE.provider_key,
                ]
            ),
        )
        for key in non_runtime_keys:
            with self.subTest(provider_key=key):
                settings = Settings(provider_key=key)
                with self.assertRaises(UnknownProviderError) as ctx:
                    build_provider(settings)
                self.assertEqual(ctx.exception.args[0], key)

    def test_known_provider_keys_alias_is_the_catalog_helper(self) -> None:
        # GOV-04 guardrail: the factory's public ``KNOWN_PROVIDER_KEYS``
        # must be the *same object* the catalog helper returns, not a
        # copy. A future regression that re-introduces a hand-written
        # literal here would lose the identity and surface in this
        # assertion.
        self.assertIs(KNOWN_PROVIDER_KEYS, runtime_supported_provider_keys())


class ConstructionSideEffectsTest(unittest.TestCase):
    """``build_provider`` must not perform any network I/O."""

    def test_fixture_dev_construction_does_not_open_network_sockets(self) -> None:
        # The fixture provider loads a local JSON file and never
        # imports an HTTP / network module; the import surface should
        # stay stdlib-only. Belt-and-braces: enumerate the ``__dict__``
        # keys so a future regression that lazily imports an HTTP
        # client surfaces immediately.
        provider = build_provider(Settings(provider_key="fixture_dev"))
        public_attrs = {name for name in vars(provider) if not name.startswith("_")}
        self.assertEqual(
            public_attrs,
            set(),
            "FixtureDevInstrumentProvider must not expose public attributes "
            "carrying network resources.",
        )

    def test_cifang_construction_does_not_call_client(self) -> None:
        # ``httpx.Client(...)`` construction itself is inert (it does
        # not open a socket); the factory must not invoke any of its
        # fetch methods. Patch ``fetch_fund_list`` and
        # ``fetch_fund_hist_em`` to raise so any accidental call surfaces
        # here rather than in CI.
        from unittest.mock import patch

        settings = Settings(provider_key="cifangquant")
        cifang = CifangSettings(enabled=True, api_key=_CIFANG_TEST_TOKEN)
        with (
            patch(
                "invest_pipeline.adapters.cifang.client.CifangClient.fetch_fund_list",
                side_effect=AssertionError("network call during build_provider"),
            ),
            patch(
                "invest_pipeline.adapters.cifang.client.CifangClient.fetch_fund_hist_em",
                side_effect=AssertionError("network call during build_provider"),
            ),
        ):
            provider = build_provider(settings, cifang_settings=cifang)
        self.assertIsInstance(provider, CifangQuantInstrumentProvider)


if __name__ == "__main__":
    unittest.main()
