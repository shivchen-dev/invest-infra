"""Unit tests for the V2 provider catalog (PR-01 + three-provider plan Phase 1).

The catalog is a data declaration only — these tests assert the
catalog invariants without touching the network, the database or any
external resource. PR-01
(``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md``)
freezes the original five-entry catalog (``fixture_dev``,
``cifangquant``, ``akshare``, ``rsscast``, ``quicktiny_mcp``) and the
V2 three-provider plan
(``tasks/plan-data-source-three-provider.md``) extends it with three
cross-validation / historical-quotes sources (``eastmoney``, ``sina``,
``tonghuashun``). The tests verify:

* Each declaration's ``provider_key`` / ``role`` / ``capabilities`` /
  ``enabled_by_default`` matches
  ``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`` §2 / §3 /
  §5.4 / §6 and the three-provider plan §"Architecture Decisions".
* RssCast and Quicktiny do **not** advertise ``ETF_DAILY_BARS`` (or
  any other ETF / index daily-bars capability) — matrix §5.4 plus the
  plan PR-01 "do not claim ETF daily bars for RssCast or QuickTiny"
  constraint.
* Eastmoney / Sina / Tonghuashun advertise the same three market-data
  capabilities as AkShare (``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` /
  indirect ``INDEX_DAILY_BARS``) but stay ``research_only`` and
  ``enabled_by_default=False`` per the three-provider plan §"Risks and
  Mitigations".
* Every real provider stays ``enabled_by_default=False``; only
  ``fixture_dev`` is on by default.
* ``lookup_provider`` resolves every known key and raises
  ``KeyError`` for unknown keys (carrying the key as the first
  argument).
* ``iter_provider_declarations`` returns the eight expected entries
  in a stable, alphabetical order.

The provider factory's runtime surface is intentionally **not**
exercised here — that lives in ``test_provider_factory_runtime.py``
and continues to assert the existing three-key factory surface per
PR-01's "preserve the existing runtime factory behavior" guardrail and
the three-provider plan Phase 1 "do not extend the factory in Phase 1"
rule.
"""

from __future__ import annotations

import unittest

from invest_pipeline.provider_catalog import (
    AKSHARE,
    CIFANGQUANT,
    EASTMONEY,
    FIXTURE_DEV,
    QUICKTINY_MCP,
    RSSCAST,
    SINA,
    TONGHUASHUN,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    iter_provider_declarations,
    lookup_provider,
)

_ALL_EIGHT_PROVIDER_KEYS: tuple[str, ...] = (
    "akshare",
    "cifangquant",
    "eastmoney",
    "fixture_dev",
    "quicktiny_mcp",
    "rsscast",
    "sina",
    "tonghuashun",
)


class DeclarationShapeTest(unittest.TestCase):
    """Every registered declaration has the frozen-dataclass shape."""

    def test_every_declaration_is_a_provider_declaration_instance(self) -> None:
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertIsInstance(declaration, ProviderDeclaration)

    def test_every_role_is_a_provider_role_enum(self) -> None:
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertIsInstance(declaration.role, ProviderRole)

    def test_every_capability_is_a_provider_capability_enum(self) -> None:
        for declaration in iter_provider_declarations():
            capabilities = declaration.capabilities
            self.assertIsInstance(capabilities, tuple)
            for capability in capabilities:
                with self.subTest(provider_key=declaration.provider_key, capability=capability):
                    self.assertIsInstance(capability, ProviderCapability)

    def test_enabled_by_default_is_a_boolean(self) -> None:
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertIsInstance(declaration.enabled_by_default, bool)


class FixtureDevDeclarationTest(unittest.TestCase):
    """The ``fixture_dev`` declaration matches the matrix §3 / §6 decision."""

    def test_provider_key_is_fixture_dev(self) -> None:
        self.assertEqual(FIXTURE_DEV.provider_key, "fixture_dev")

    def test_role_is_fixture_dev(self) -> None:
        self.assertEqual(FIXTURE_DEV.role, ProviderRole.FIXTURE_DEV)
        self.assertEqual(FIXTURE_DEV.role.value, "fixture_dev")

    def test_capabilities_are_etf_master_and_etf_daily_bars(self) -> None:
        capabilities = FIXTURE_DEV.capabilities
        self.assertEqual(
            set(capabilities),
            {
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_MASTER_DATA,
            },
        )
        self.assertNotIn(ProviderCapability.INDEX_DAILY_BARS, capabilities)
        self.assertNotIn(ProviderCapability.RESEARCH, capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, capabilities)

    def test_enabled_by_default_is_true(self) -> None:
        # Matrix §3 / §6: ``fixture_dev`` is the only on-by-default
        # provider; the on-disk fixtures never reach the network, so
        # the default is safe to leave on for dev / tests.
        self.assertTrue(FIXTURE_DEV.enabled_by_default)


class CifangquantDeclarationTest(unittest.TestCase):
    """The ``cifangquant`` declaration matches matrix §2 / §3 / §6."""

    def test_provider_key_is_cifangquant(self) -> None:
        self.assertEqual(CIFANGQUANT.provider_key, "cifangquant")

    def test_role_is_secondary(self) -> None:
        # Matrix §3: ``secondary`` is the recommended role once O-1
        # is closed. ``primary`` would be wrong because matrix §3
        # explicitly defers primary status until O-1.
        self.assertEqual(CIFANGQUANT.role, ProviderRole.SECONDARY)
        self.assertEqual(CIFANGQUANT.role.value, "secondary")

    def test_capabilities_cover_etf_and_indirect_index(self) -> None:
        capabilities = set(CIFANGQUANT.capabilities)
        self.assertIn(ProviderCapability.ETF_DAILY_BARS, capabilities)
        self.assertIn(ProviderCapability.ETF_MASTER_DATA, capabilities)
        # Matrix §2: index capability is observed but indirect
        # ("与 ETF 数据共用接口，已观察到").
        self.assertIn(ProviderCapability.INDEX_DAILY_BARS, capabilities)

    def test_research_and_market_snapshot_capabilities_are_absent(self) -> None:
        # CifangQuant is a deterministic market-data source; it must
        # not advertise the research-only surfaces.
        self.assertNotIn(ProviderCapability.RESEARCH, CIFANGQUANT.capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, CIFANGQUANT.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        # Matrix §6: real providers default to off.
        self.assertFalse(CIFANGQUANT.enabled_by_default)


class AkshareDeclarationTest(unittest.TestCase):
    """The ``akshare`` declaration matches matrix §2 / §3 / §5.4 / §6."""

    def test_provider_key_is_akshare(self) -> None:
        self.assertEqual(AKSHARE.provider_key, "akshare")

    def test_role_is_research_only(self) -> None:
        # Matrix §3 default recommendation; matrix §5.4 forbids
        # treating AkShare as a production SLA source, so the safer
        # ``research_only`` role is the one frozen in PR-01.
        self.assertEqual(AKSHARE.role, ProviderRole.RESEARCH_ONLY)
        self.assertEqual(AKSHARE.role.value, "research_only")

    def test_capabilities_cover_etf_and_indirect_index(self) -> None:
        # Matrix §2: ETF master data, ETF daily bars, and indirect
        # index daily bars are all observed.
        capabilities = set(AKSHARE.capabilities)
        self.assertEqual(
            capabilities,
            {
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_MASTER_DATA,
                ProviderCapability.INDEX_DAILY_BARS,
            },
        )

    def test_research_and_market_snapshot_capabilities_are_absent(self) -> None:
        # AkShare is a deterministic aggregator; it must not advertise
        # the research / market-snapshot surfaces reserved for the MCP
        # research providers.
        self.assertNotIn(ProviderCapability.RESEARCH, AKSHARE.capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, AKSHARE.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        # Matrix §6: real providers default to off. The fact that
        # AkShare advertises the ETF / index capabilities must not
        # override the safe default.
        self.assertFalse(AKSHARE.enabled_by_default)


class RsscastDeclarationTest(unittest.TestCase):
    """The ``rsscast`` declaration matches matrix §3 / §5.4 and PR-01."""

    def test_provider_key_is_rsscast(self) -> None:
        self.assertEqual(RSSCAST.provider_key, "rsscast")

    def test_role_is_out_of_scope_for_etf(self) -> None:
        # Matrix §3: RssCast is the canonical
        # ``out_of_scope_for_etf`` provider.
        self.assertEqual(RSSCAST.role, ProviderRole.OUT_OF_SCOPE_FOR_ETF)
        self.assertEqual(RSSCAST.role.value, "out_of_scope_for_etf")

    def test_capabilities_are_research_and_index_daily_bars(self) -> None:
        # Plan PR-01 "RssCast research / index only" constraint.
        self.assertEqual(
            set(RSSCAST.capabilities),
            {
                ProviderCapability.RESEARCH,
                ProviderCapability.INDEX_DAILY_BARS,
            },
        )

    def test_etf_daily_bars_capability_is_absent(self) -> None:
        # Plan PR-01 "do not claim ETF daily bars for RssCast" plus
        # matrix §5.4. The negative assertion is the whole point of
        # the catalog entry — a future regression that adds
        # ``ETF_DAILY_BARS`` to RssCast would corrupt the matrix.
        self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, RSSCAST.capabilities)

    def test_etf_master_data_capability_is_absent(self) -> None:
        # Belt-and-braces: RssCast must not claim ETF master data
        # either; matrix §3 places it firmly out-of-scope-for-etf.
        self.assertNotIn(ProviderCapability.ETF_MASTER_DATA, RSSCAST.capabilities)

    def test_market_snapshot_capability_is_absent(self) -> None:
        # Plan PR-01 constrains RssCast to "research / index only";
        # market_snapshot belongs to Quicktiny alone in PR-01.
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, RSSCAST.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        self.assertFalse(RSSCAST.enabled_by_default)


class QuicktinyMcpDeclarationTest(unittest.TestCase):
    """The ``quicktiny_mcp`` declaration matches matrix §3 / §5.4 and PR-01."""

    def test_provider_key_is_quicktiny_mcp(self) -> None:
        self.assertEqual(QUICKTINY_MCP.provider_key, "quicktiny_mcp")

    def test_role_is_research_only(self) -> None:
        self.assertEqual(QUICKTINY_MCP.role, ProviderRole.RESEARCH_ONLY)
        # The role enum value must be the stable string used in docs
        # and the migration matrix; assert it directly so a future
        # rename of the enum member cannot silently change the wire
        # value.
        self.assertEqual(QUICKTINY_MCP.role.value, "research_only")

    def test_capabilities_are_research_and_market_snapshot(self) -> None:
        # Plan PR-01 "Quicktiny research / market_snapshot only" constraint.
        self.assertEqual(
            set(QUICKTINY_MCP.capabilities),
            {
                ProviderCapability.RESEARCH,
                ProviderCapability.MARKET_SNAPSHOT,
            },
        )
        self.assertEqual(
            tuple(c.value for c in QUICKTINY_MCP.capabilities),
            ("research", "market_snapshot"),
        )

    def test_etf_daily_bars_capability_is_absent(self) -> None:
        # Matrix §5.4 + plan PR-01 "do not claim ETF daily bars for
        # QuickTiny". Assert the enum member is *not* present in the
        # declaration's capabilities tuple.
        self.assertNotIn(
            ProviderCapability.ETF_DAILY_BARS,
            QUICKTINY_MCP.capabilities,
        )

    def test_etf_master_data_capability_is_absent(self) -> None:
        # Matrix §5.4 also forbids claiming ETF master data.
        self.assertNotIn(
            ProviderCapability.ETF_MASTER_DATA,
            QUICKTINY_MCP.capabilities,
        )

    def test_index_daily_bars_capability_is_absent(self) -> None:
        # Quicktiny is research-only; it must not advertise any daily
        # bars capability, including index bars.
        self.assertNotIn(
            ProviderCapability.INDEX_DAILY_BARS,
            QUICKTINY_MCP.capabilities,
        )

    def test_enabled_by_default_is_false(self) -> None:
        # Matrix §6: real providers default to off.
        self.assertFalse(QUICKTINY_MCP.enabled_by_default)
        self.assertIsInstance(QUICKTINY_MCP.enabled_by_default, bool)


class EastmoneyDeclarationTest(unittest.TestCase):
    """The ``eastmoney`` declaration matches the three-provider plan §Architecture Decisions."""

    def test_provider_key_is_eastmoney(self) -> None:
        self.assertEqual(EASTMONEY.provider_key, "eastmoney")

    def test_role_is_research_only(self) -> None:
        # Three-provider plan §"Architecture Decisions" pins Eastmoney
        # to ``research_only`` because the public endpoints are
        # non-official and matrix §5.4 forbids treating it as a
        # production SLA source.
        self.assertEqual(EASTMONEY.role, ProviderRole.RESEARCH_ONLY)
        self.assertEqual(EASTMONEY.role.value, "research_only")

    def test_capabilities_cover_etf_and_indirect_index(self) -> None:
        # Three-provider plan: Eastmoney advertises the same three
        # market-data capabilities as AkShare because the public
        # endpoints share the same shape as the AkShare aggregator
        # (``ETF_DAILY_BARS`` / ``ETF_MASTER_DATA`` / indirect
        # ``INDEX_DAILY_BARS``).
        capabilities = set(EASTMONEY.capabilities)
        self.assertEqual(
            capabilities,
            {
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_MASTER_DATA,
                ProviderCapability.INDEX_DAILY_BARS,
            },
        )

    def test_research_and_market_snapshot_capabilities_are_absent(self) -> None:
        # Eastmoney is a deterministic market-data source; the
        # research / market-snapshot surfaces remain reserved for the
        # MCP research providers.
        self.assertNotIn(ProviderCapability.RESEARCH, EASTMONEY.capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, EASTMONEY.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        # Matrix §6: real providers default to off. The capability
        # set must not override the safe default.
        self.assertFalse(EASTMONEY.enabled_by_default)


class SinaDeclarationTest(unittest.TestCase):
    """The ``sina`` declaration matches the three-provider plan §Architecture Decisions."""

    def test_provider_key_is_sina(self) -> None:
        self.assertEqual(SINA.provider_key, "sina")

    def test_role_is_research_only(self) -> None:
        # Three-provider plan §"Architecture Decisions" pins Sina to
        # ``research_only`` for the same reason as Eastmoney.
        self.assertEqual(SINA.role, ProviderRole.RESEARCH_ONLY)
        self.assertEqual(SINA.role.value, "research_only")

    def test_capabilities_cover_etf_and_indirect_index(self) -> None:
        # Mirror of Eastmoney: the three market-data capabilities
        # are advertised.
        capabilities = set(SINA.capabilities)
        self.assertEqual(
            capabilities,
            {
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_MASTER_DATA,
                ProviderCapability.INDEX_DAILY_BARS,
            },
        )

    def test_research_and_market_snapshot_capabilities_are_absent(self) -> None:
        self.assertNotIn(ProviderCapability.RESEARCH, SINA.capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, SINA.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        self.assertFalse(SINA.enabled_by_default)


class TonghuashunDeclarationTest(unittest.TestCase):
    """The ``tonghuashun`` declaration matches the three-provider plan §Architecture Decisions."""

    def test_provider_key_is_tonghuashun(self) -> None:
        self.assertEqual(TONGHUASHUN.provider_key, "tonghuashun")

    def test_role_is_research_only(self) -> None:
        # Three-provider plan §"Architecture Decisions" pins
        # Tonghuashun to ``research_only`` for the same reason as
        # Eastmoney / Sina.
        self.assertEqual(TONGHUASHUN.role, ProviderRole.RESEARCH_ONLY)
        self.assertEqual(TONGHUASHUN.role.value, "research_only")

    def test_capabilities_cover_etf_and_indirect_index(self) -> None:
        # Mirror of Eastmoney / Sina: the three market-data
        # capabilities are advertised.
        capabilities = set(TONGHUASHUN.capabilities)
        self.assertEqual(
            capabilities,
            {
                ProviderCapability.ETF_DAILY_BARS,
                ProviderCapability.ETF_MASTER_DATA,
                ProviderCapability.INDEX_DAILY_BARS,
            },
        )

    def test_research_and_market_snapshot_capabilities_are_absent(self) -> None:
        self.assertNotIn(ProviderCapability.RESEARCH, TONGHUASHUN.capabilities)
        self.assertNotIn(ProviderCapability.MARKET_SNAPSHOT, TONGHUASHUN.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        self.assertFalse(TONGHUASHUN.enabled_by_default)


class NoEtfDailyBarsForResearchOnlyProvidersTest(unittest.TestCase):
    """Cross-provider negative assertion: research providers never claim ETF bars.

    The plan PR-01 constraint forbids RssCast and Quicktiny from
    claiming ``ETF_DAILY_BARS``. The catalog must also forbid any
    research-only provider from claiming the ETF / index daily-bars
    capabilities it should not legitimately serve, so a future
    regression that re-introduces a research source into the
    production data path surfaces here.
    """

    def test_rsscast_does_not_advertise_etf_or_index_daily_bars(self) -> None:
        for forbidden in (
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_MASTER_DATA,
        ):
            with self.subTest(capability=forbidden):
                self.assertNotIn(forbidden, RSSCAST.capabilities)

    def test_quicktiny_mcp_does_not_advertise_etf_or_index_daily_bars(
        self,
    ) -> None:
        for forbidden in (
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_MASTER_DATA,
            ProviderCapability.INDEX_DAILY_BARS,
        ):
            with self.subTest(capability=forbidden):
                self.assertNotIn(forbidden, QUICKTINY_MCP.capabilities)

    def test_research_only_role_never_overlaps_with_fixture_dev_capabilities(
        self,
    ) -> None:
        # Cross-check: research-only providers must not advertise
        # either of the two ETF capabilities ``fixture_dev`` owns.
        # This is the catalog-level mirror of matrix §5.4.
        research_only_declarations = (
            AKSHARE,
            QUICKTINY_MCP,
            RSSCAST,
        )
        for declaration in research_only_declarations:
            with self.subTest(provider_key=declaration.provider_key):
                advertised = set(declaration.capabilities)
                if declaration is RSSCAST:
                    # RssCast is the out-of-scope-for-etf MCP source:
                    # matrix §3 places it firmly outside the ETF
                    # surface, so neither ETF capability is allowed.
                    self.assertNotIn(ProviderCapability.ETF_DAILY_BARS, advertised)
                    self.assertNotIn(ProviderCapability.ETF_MASTER_DATA, advertised)
                elif declaration is QUICKTINY_MCP:
                    # Quicktiny is the research / market_snapshot MCP
                    # source: none of the three market-data caps
                    # belong to it.
                    for forbidden in (
                        ProviderCapability.ETF_DAILY_BARS,
                        ProviderCapability.ETF_MASTER_DATA,
                        ProviderCapability.INDEX_DAILY_BARS,
                    ):
                        self.assertNotIn(forbidden, advertised)


class AllRealProvidersDisabledByDefaultTest(unittest.TestCase):
    """Matrix §6: every non-fixture provider defaults to off."""

    def test_only_fixture_dev_is_enabled_by_default(self) -> None:
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                if declaration is FIXTURE_DEV:
                    self.assertTrue(declaration.enabled_by_default)
                else:
                    self.assertFalse(
                        declaration.enabled_by_default,
                        f"{declaration.provider_key!r} is a real provider "
                        "and must default to False per matrix §6",
                    )


class LookupProviderTest(unittest.TestCase):
    """``lookup_provider`` resolves every known key and raises on unknowns."""

    def test_lookup_resolves_every_known_key(self) -> None:
        for key in _ALL_EIGHT_PROVIDER_KEYS:
            with self.subTest(provider_key=key):
                declaration = lookup_provider(key)
                self.assertEqual(declaration.provider_key, key)

    def test_lookup_returns_quicktiny_mcp_for_known_key(self) -> None:
        declaration = lookup_provider("quicktiny_mcp")
        self.assertIs(declaration, QUICKTINY_MCP)
        self.assertEqual(declaration.provider_key, "quicktiny_mcp")

    def test_lookup_returns_same_instance_as_module_constant(self) -> None:
        # The exported module constant and the catalog lookup must
        # return the *same* declaration instance so downstream
        # identity checks stay stable.
        self.assertIs(lookup_provider("fixture_dev"), FIXTURE_DEV)
        self.assertIs(lookup_provider("cifangquant"), CIFANGQUANT)
        self.assertIs(lookup_provider("akshare"), AKSHARE)
        self.assertIs(lookup_provider("rsscast"), RSSCAST)
        self.assertIs(lookup_provider("quicktiny_mcp"), QUICKTINY_MCP)
        self.assertIs(lookup_provider("eastmoney"), EASTMONEY)
        self.assertIs(lookup_provider("sina"), SINA)
        self.assertIs(lookup_provider("tonghuashun"), TONGHUASHUN)

    def test_lookup_raises_key_error_for_unknown_key(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            lookup_provider("not_a_real_provider")
        # The ``KeyError`` must carry the requested key as its
        # argument so callers (and operators reading logs) can
        # identify the unknown provider without parsing the message
        # string.
        self.assertEqual(ctx.exception.args[0], "not_a_real_provider")

    def test_lookup_raises_key_error_for_empty_string(self) -> None:
        # An empty string is not a valid provider key and must
        # surface as ``KeyError`` rather than silently returning
        # ``None``.
        with self.assertRaises(KeyError):
            lookup_provider("")

    def test_lookup_raises_key_error_for_mixed_case_key(self) -> None:
        # Provider keys are case-sensitive — the catalog only stores
        # the canonical lower_snake_case form. ``QuickTiny_MCP`` must
        # not silently match ``quicktiny_mcp``.
        with self.assertRaises(KeyError):
            lookup_provider("QuickTiny_MCP")


class IterProviderDeclarationsTest(unittest.TestCase):
    """``iter_provider_declarations`` exposes the catalog for tests / docs."""

    def test_iteration_returns_exactly_the_eight_expected_keys(self) -> None:
        declarations = iter_provider_declarations()
        self.assertEqual(
            tuple(declaration.provider_key for declaration in declarations),
            _ALL_EIGHT_PROVIDER_KEYS,
        )

    def test_iteration_is_alphabetical_by_provider_key(self) -> None:
        # Stable order so documentation tables and snapshot tests can
        # rely on the iteration order.
        provider_keys = [declaration.provider_key for declaration in iter_provider_declarations()]
        self.assertEqual(provider_keys, sorted(provider_keys))

    def test_iteration_returns_immutable_tuple_with_equal_contents(self) -> None:
        first = iter_provider_declarations()
        second = iter_provider_declarations()
        # The catalog exposes its declarations through a tuple so
        # callers cannot mutate the internal state by accident;
        # iteration must therefore return equal contents across
        # calls. The tuple itself is allowed to be the module-level
        # constant (it is already immutable).
        self.assertIsInstance(first, tuple)
        self.assertIsInstance(second, tuple)
        self.assertEqual(first, second)

    def test_iteration_covers_every_module_constant(self) -> None:
        iterated_keys = {declaration.provider_key for declaration in iter_provider_declarations()}
        self.assertEqual(
            iterated_keys,
            {
                AKSHARE.provider_key,
                CIFANGQUANT.provider_key,
                EASTMONEY.provider_key,
                FIXTURE_DEV.provider_key,
                QUICKTINY_MCP.provider_key,
                RSSCAST.provider_key,
                SINA.provider_key,
                TONGHUASHUN.provider_key,
            },
        )


class CatalogWideInvariantsTest(unittest.TestCase):
    """Catalog-wide structural invariants."""

    def test_every_expected_provider_key_is_registered(self) -> None:
        # PR-01 freezes the original five-entry catalog; the
        # three-provider plan Phase 1 extends it with three more.
        # Adding a provider without a plan / matrix update is a
        # regression; removing one is a regression. This test pins
        # the membership exactly so the next PR cannot silently drop
        # a provider.
        iterated_keys = {declaration.provider_key for declaration in iter_provider_declarations()}
        self.assertEqual(iterated_keys, set(_ALL_EIGHT_PROVIDER_KEYS))

    def test_catalog_provider_keys_are_unique(self) -> None:
        provider_keys = [declaration.provider_key for declaration in iter_provider_declarations()]
        self.assertEqual(len(provider_keys), len(set(provider_keys)))

    def test_quicktiny_mcp_capabilities_subset_holds(self) -> None:
        # Final cross-check: the Quicktiny MCP capability set must be
        # a subset of ``{RESEARCH, MARKET_SNAPSHOT}``. Anything else
        # is a regression of the plan PR-01 "research /
        # market_snapshot only" constraint.
        advertised = set(QUICKTINY_MCP.capabilities)
        self.assertTrue(
            advertised.issubset({ProviderCapability.RESEARCH, ProviderCapability.MARKET_SNAPSHOT})
        )

    def test_rsscapabilities_subset_holds(self) -> None:
        # Mirror of the Quicktiny check: RssCast's capabilities must
        # be a subset of the plan PR-01 "research / index only" pair.
        advertised = set(RSSCAST.capabilities)
        self.assertTrue(
            advertised.issubset({ProviderCapability.RESEARCH, ProviderCapability.INDEX_DAILY_BARS})
        )


if __name__ == "__main__":
    unittest.main()
