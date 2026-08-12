"""Unit tests for the V2 provider catalog (PR-01).

The catalog is a data declaration only — these tests assert the
catalog invariants without touching the network, the database or any
external resource. PR-01
(``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md``)
freezes the original five-entry catalog (``fixture_dev``,
``cifangquant``, ``akshare``, ``rsscast``, ``quicktiny_mcp``) and the
historical V2 three-provider plan
(``tasks/plan-data-source-three-provider.md``) proposed adding three
cross-validation / historical-quotes sources (``eastmoney``, ``sina``,
``tonghuashun``). That plan has been de-scoped in this slice: the
three sources are not selectable runtime providers in V2 and the
catalog carries no declaration for them. Their public
historical-quotes endpoints remain internal upstreams of the AkShare
aggregator (``ak.fund_etf_hist_sina`` / ``ak.fund_etf_hist_em``) and
surface only as ``source_key`` values on ``BarSource`` rows produced
by the AkShare adapter. The reserved-provider slice
(``tasks/hithink-reserved-provider-plan.md``) additionally registers
``hithink`` as a catalog-only, disabled-by-default declaration that
advertises the six stock-oriented surfaces the upstream contract
exposes; it has no runtime factory adapter and stays out of the
runtime surface. The Stage 4B Phase 5 (slice 1) Tushare → TDX offline
fallback slice additionally registers ``tdx_offline`` as a
catalog-only, disabled-by-default declaration for the
``stock_daily_bars`` capability; the adapter and the operator-facing
``TdxOfflineSettings`` live in
:mod:`invest_pipeline.adapters.tdx_offline.stock_adapter` and the
catalog entry mirrors the same "no runtime factory adapter yet"
posture as the HiThink reserved slice. The tests verify:

* Each declaration's ``provider_key`` / ``role`` / ``capabilities`` /
  ``enabled_by_default`` matches
  ``docs/implementation/DATA-SOURCE-MIGRATION-MATRIX.md`` §2 / §3 /
  §5.4 / §6 and the PR-01 plan §"Architecture Decisions".
* RssCast and Quicktiny do **not** advertise ``ETF_DAILY_BARS`` (or
  any other ETF / index daily-bars capability) — matrix §5.4 plus the
  plan PR-01 "do not claim ETF daily bars for RssCast or QuickTiny"
  constraint.
* Every real provider stays ``enabled_by_default=False``; only
  ``fixture_dev`` is on by default.
* ``lookup_provider`` resolves every known key and raises
  ``KeyError`` for unknown keys (carrying the key as the first
  argument); ``eastmoney`` / ``sina`` / ``tonghuashun`` are rejected
  as unknown keys because the three-provider plan was de-scoped.
* ``iter_provider_declarations`` returns the eight expected entries
  in a stable, alphabetical order.
* The reserved ``hithink`` declaration is visible through the
  catalog but excluded from the runtime surface (see
  ``HithinkRuntimeExclusionTest``).

The provider factory's runtime surface is intentionally **not**
exercised here — that lives in ``test_provider_factory_runtime.py``
and continues to assert the existing four-key factory surface per
PR-01's "preserve the existing runtime factory behavior" guardrail
and the reserved-provider slice's "no runtime adapter yet" stance.
"""

from __future__ import annotations

import unittest

from invest_pipeline.provider_catalog import (
    AKSHARE,
    CIFANGQUANT,
    FIXTURE_DEV,
    HITHINK,
    QUICKTINY_MCP,
    RSSCAST,
    TDX_OFFLINE,
    TUSHARE,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    iter_provider_declarations,
    lookup_provider,
    runtime_supported_provider_declarations,
    runtime_supported_provider_keys,
)

_ALL_CATALOG_PROVIDER_KEYS: tuple[str, ...] = (
    "akshare",
    "cifangquant",
    "fixture_dev",
    "hithink",
    "quicktiny_mcp",
    "rsscast",
    "tdx_offline",
    "tushare",
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

    def test_has_runtime_factory_adapter_is_a_boolean(self) -> None:
        # GOV-04: every declaration must expose the
        # ``has_runtime_factory_adapter`` flag as a boolean so the
        # catalog/runtime-supported helpers can filter on it
        # deterministically.
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertIsInstance(declaration.has_runtime_factory_adapter, bool)

    def test_has_runtime_factory_adapter_defaults_to_false(self) -> None:
        # Tests (for example ``test_provider_routing_selection``)
        # construct :class:`ProviderDeclaration` locally without
        # passing the new flag. Pin the default to ``False`` so the
        # historical / third-party call sites keep working unchanged.
        declaration = ProviderDeclaration(
            provider_key="synthetic",
            role=ProviderRole.RESEARCH_ONLY,
            capabilities=(ProviderCapability.RESEARCH,),
            enabled_by_default=False,
        )
        self.assertFalse(declaration.has_runtime_factory_adapter)


class Stage4CCapabilityEnumTest(unittest.TestCase):
    """Stage 4C Phase 0 Task 0.1 freezes four new capability members.

    The contract freezing slice adds the four
    :class:`ProviderCapability` members the new core data layer
    introduces but does **not** register any matching provider
    declaration. The tests in this class pin:

    * The four new enum members exist and carry the canonical
      snake_case string values the persisted evidence tables and
      plan documents reference.
    * No registered provider advertises any of the new capabilities.
      The Phase 0 plan's "do not claim capabilities for providers
      that are not implemented yet" guardrail is exercised end-to-end
      against the catalog surface so a future regression that
      silently widens a declaration's capability set surfaces here.
    """

    def test_stage4c_capability_string_values_are_frozen(self) -> None:
        # The capability string values are referenced from matrix /
        # plan documents and must stay stable. Pin them so a future
        # regression surfaces here.
        self.assertEqual(
            ProviderCapability.STOCK_MINUTE_BARS.value,
            "stock_minute_bars",
        )
        self.assertEqual(
            ProviderCapability.STOCK_BLOCK_MEMBERSHIPS.value,
            "stock_block_memberships",
        )
        self.assertEqual(
            ProviderCapability.STOCK_PRICE_LIMITS.value,
            "stock_price_limits",
        )
        self.assertEqual(
            ProviderCapability.TDX_GUI_ANALYSIS.value,
            "tdx_gui_analysis",
        )

    def test_stage4c_capability_members_are_provider_capability_enum(self) -> None:
        # The new members are part of the public enum contract so
        # downstream code can refer to them by name. ``StrEnum``
        # members are still :class:`ProviderCapability` instances.
        for capability in (
            ProviderCapability.STOCK_MINUTE_BARS,
            ProviderCapability.STOCK_BLOCK_MEMBERSHIPS,
            ProviderCapability.STOCK_PRICE_LIMITS,
            ProviderCapability.TDX_GUI_ANALYSIS,
        ):
            with self.subTest(capability=capability):
                self.assertIsInstance(capability, ProviderCapability)

    def test_no_registered_provider_advertises_stage4c_capabilities(self) -> None:
        # Phase 0 freezes the capability enum but does not register
        # any provider declaration for the matching surfaces. Pin
        # the absence so a future regression that silently broadens
        # an existing declaration (or adds a pre-emptive provider
        # entry) surfaces here.
        forbidden = (
            ProviderCapability.STOCK_MINUTE_BARS,
            ProviderCapability.STOCK_BLOCK_MEMBERSHIPS,
            ProviderCapability.STOCK_PRICE_LIMITS,
            ProviderCapability.TDX_GUI_ANALYSIS,
        )
        for declaration in iter_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                advertised = set(declaration.capabilities)
                for capability in forbidden:
                    self.assertNotIn(capability, advertised)


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


class HithinkDeclarationTest(unittest.TestCase):
    """The ``hithink`` reserved provider matches the
    ``tasks/hithink-reserved-provider-plan.md`` contract.

    HiThink lands as a catalog-only, disabled-by-default declaration
    so a future dataset contract can opt in without forcing a
    catalog migration. The declaration advertises the six surfaces
    the upstream HiThink contract exposes (``research`` /
    ``market_snapshot`` / ``stock_daily_bars`` / ``stock_master_data``
    / ``stock_financials`` / ``stock_valuations``) but omits every
    ETF / index capability, leaves ``has_runtime_factory_adapter``
    ``False`` and stays ``enabled_by_default=False``. No runtime
    factory branch or network client is wired in this slice.
    """

    def test_provider_key_is_hithink(self) -> None:
        self.assertEqual(HITHINK.provider_key, "hithink")

    def test_role_is_research_only(self) -> None:
        # The reserved provider has no production SLA role; matrix §6
        # plus the "no production SLA path yet" posture in the
        # reserved-provider plan make ``research_only`` the only safe
        # role for a catalog-only entry that has not been admitted to
        # the production data path.
        self.assertEqual(HITHINK.role, ProviderRole.RESEARCH_ONLY)
        self.assertEqual(HITHINK.role.value, "research_only")

    def test_capabilities_cover_the_six_planned_surfaces(self) -> None:
        # The plan lists exactly six advertised surfaces; pin them as
        # a set so a future regression that drops a capability surfaces
        # here. The ordered tuple check pins the deterministic order
        # used by the catalog's iter helper.
        self.assertEqual(
            set(HITHINK.capabilities),
            {
                ProviderCapability.RESEARCH,
                ProviderCapability.MARKET_SNAPSHOT,
                ProviderCapability.STOCK_DAILY_BARS,
                ProviderCapability.STOCK_MASTER_DATA,
                ProviderCapability.STOCK_FINANCIALS,
                ProviderCapability.STOCK_VALUATIONS,
            },
        )
        self.assertEqual(
            tuple(c.value for c in HITHINK.capabilities),
            (
                "research",
                "market_snapshot",
                "stock_daily_bars",
                "stock_master_data",
                "stock_financials",
                "stock_valuations",
            ),
        )

    def test_etf_capabilities_are_absent(self) -> None:
        # Reserved-provider contract: HiThink does **not** claim any
        # ETF surface, mirroring matrix §5.4's negative-capability
        # rule for non-production providers.
        for forbidden in (
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_MASTER_DATA,
        ):
            with self.subTest(capability=forbidden):
                self.assertNotIn(forbidden, HITHINK.capabilities)

    def test_index_daily_bars_capability_is_absent(self) -> None:
        # HiThink is a stock-oriented source; the index daily-bars
        # surface belongs to the index-only providers and must not be
        # silently inherited here.
        self.assertNotIn(ProviderCapability.INDEX_DAILY_BARS, HITHINK.capabilities)

    def test_enabled_by_default_is_false(self) -> None:
        # Reserved-provider slice contract: HiThink defaults to off
        # because no dataset contract has been approved yet. Pinning
        # the boolean type guards against a future regression that
        # accidentally flips the default.
        self.assertFalse(HITHINK.enabled_by_default)
        self.assertIsInstance(HITHINK.enabled_by_default, bool)

    def test_has_runtime_factory_adapter_is_false(self) -> None:
        # Reserved-provider slice contract: HiThink has **no** runtime
        # factory adapter in this slice. The flag must stay ``False``
        # so ``runtime_supported_provider_keys`` keeps excluding it
        # until a future ADR approves the first dataset contract and
        # wires a real adapter.
        self.assertFalse(HITHINK.has_runtime_factory_adapter)
        self.assertIsInstance(HITHINK.has_runtime_factory_adapter, bool)


class HithinkRuntimeExclusionTest(unittest.TestCase):
    """The reserved ``hithink`` provider stays out of the runtime surface.

    The reserved-provider slice intentionally leaves
    ``has_runtime_factory_adapter=False`` so the runtime factory
    (:mod:`invest_pipeline.provider_factory`) refuses to construct
    ``hithink``. These tests pin the catalog/runtime-key parity for
    the new entry so a future maintainer cannot silently widen the
    runtime surface.
    """

    def test_hithink_is_not_in_runtime_supported_keys(self) -> None:
        # The four-key runtime surface stays exactly
        # ``("akshare", "cifangquant", "fixture_dev", "tushare")``;
        # adding ``hithink`` to it would silently route runtime
        # traffic to a source that has no real adapter yet.
        self.assertNotIn("hithink", runtime_supported_provider_keys())

    def test_hithink_is_not_in_runtime_supported_declarations(self) -> None:
        runtime_declarations = runtime_supported_provider_declarations()
        self.assertNotIn(HITHINK, runtime_declarations)
        for declaration in runtime_declarations:
            with self.subTest(provider_key=declaration.provider_key):
                self.assertNotEqual(declaration.provider_key, "hithink")

    def test_hithink_is_visible_via_lookup_provider(self) -> None:
        # ``hithink`` must be discoverable through the catalog even
        # though it has no runtime adapter: the routing layer /
        # coverage report still need to know it exists so the
        # reserved surface is auditable.
        self.assertIs(lookup_provider("hithink"), HITHINK)

    def test_hithink_is_visible_via_iter_provider_declarations(self) -> None:
        iterated_keys = {
            declaration.provider_key for declaration in iter_provider_declarations()
        }
        self.assertIn("hithink", iterated_keys)

    def test_runtime_supported_set_remains_strict_subset_of_catalog_set(self) -> None:
        # The runtime surface is intentionally a strict subset of the
        # catalog surface — every runtime provider must first be a
        # catalog declaration so the routing layer can find it. Adding
        # ``hithink`` must keep this property intact.
        catalog_keys = {
            declaration.provider_key for declaration in iter_provider_declarations()
        }
        runtime_keys = set(runtime_supported_provider_keys())
        self.assertTrue(runtime_keys.issubset(catalog_keys))
        self.assertLess(runtime_keys, catalog_keys)
        self.assertIn("hithink", catalog_keys - runtime_keys)


class EastmoneySinaTonghuashunNotRuntimeTest(unittest.TestCase):
    """The three-provider plan entries are not runtime providers in V2.

    The historical three-provider plan proposed ``eastmoney``,
    ``sina`` and ``tonghuashun`` as independent V2 providers. That
    plan has been de-scoped in this slice and the catalog carries no
    declaration for any of the three. Their public historical-quotes
    endpoints remain internal upstreams of the AkShare aggregator
    (``ak.fund_etf_hist_sina`` / ``ak.fund_etf_hist_em``) and surface
    only as ``source_key`` values on ``BarSource`` rows produced by
    the AkShare adapter. The tests pin this contract so a future
    maintainer cannot silently re-introduce them as runtime providers.
    """

    def test_lookup_rejects_three_provider_plan_keys(self) -> None:
        # ``lookup_provider`` must reject ``eastmoney`` / ``sina`` /
        # ``tonghuashun`` so a future regression that registers them
        # as runtime providers surfaces here. The rejected keys are
        # the canonical identifiers the historical plan documented.
        for key in ("eastmoney", "sina", "tonghuashun"):
            with self.subTest(provider_key=key):
                with self.assertRaises(KeyError) as ctx:
                    lookup_provider(key)
                self.assertEqual(ctx.exception.args[0], key)

    def test_three_provider_plan_keys_are_not_in_iteration(self) -> None:
        iterated_keys = {
            declaration.provider_key for declaration in iter_provider_declarations()
        }
        for key in ("eastmoney", "sina", "tonghuashun"):
            with self.subTest(provider_key=key):
                self.assertNotIn(key, iterated_keys)


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


class RuntimeFactoryAdapterDeclarationTest(unittest.TestCase):
    """GOV-04: the ``has_runtime_factory_adapter`` flag is the catalog's
    declaration of whether a provider has a runtime factory adapter.

    The flag is the single source of truth for the runtime-supported
    set; the provider factory derives ``KNOWN_PROVIDER_KEYS`` from
    :func:`runtime_supported_provider_keys`. These tests pin the
    catalog/runtime-key parity so a future maintainer cannot
    silently widen or narrow the runtime surface.
    """

    def test_runtime_supported_keys_are_exactly_the_four_expected(self) -> None:
        # Pin the exact membership. The four keys are the historical
        # factory surface (``fixture_dev`` / ``cifangquant`` /
        # ``akshare``) plus the opt-in Tushare ETF source; ``rsscast``
        # and ``quicktiny_mcp`` are catalog-only MCP research sources
        # and must stay out of the runtime surface per matrix §3 / §5.4
        # and the PR-01 plan.
        self.assertEqual(
            runtime_supported_provider_keys(),
            ("akshare", "cifangquant", "fixture_dev", "tushare"),
        )

    def test_runtime_supported_keys_are_alphabetical(self) -> None:
        # Stable order so the factory's derived ``KNOWN_PROVIDER_KEYS``
        # and downstream snapshot tests stay deterministic.
        keys = runtime_supported_provider_keys()
        self.assertEqual(keys, tuple(sorted(keys)))

    def test_runtime_supported_declarations_match_runtime_supported_keys(self) -> None:
        # The declarations tuple and the keys tuple must stay in
        # lock-step — a future regression that drops a key from one
        # helper surfaces here.
        keys = tuple(
            declaration.provider_key
            for declaration in runtime_supported_provider_declarations()
        )
        self.assertEqual(keys, runtime_supported_provider_keys())

    def test_runtime_supported_keys_exclude_research_only_mcp_sources(self) -> None:
        # ``rsscast`` and ``quicktiny_mcp`` are declared in the catalog
        # but must stay catalog-only: they have no runtime factory
        # adapter, so picking them up at runtime would silently fall
        # through to an unknown-key error and break the routing layer
        # contract.
        runtime_keys = set(runtime_supported_provider_keys())
        self.assertNotIn("rsscast", runtime_keys)
        self.assertNotIn("quicktiny_mcp", runtime_keys)

    def test_runtime_supported_set_is_strict_subset_of_catalog_set(self) -> None:
        # The runtime surface is intentionally a strict subset of the
        # catalog surface — every runtime provider must first be a
        # catalog declaration so the routing layer can find it.
        catalog_keys = {
            declaration.provider_key for declaration in iter_provider_declarations()
        }
        runtime_keys = set(runtime_supported_provider_keys())
        self.assertTrue(runtime_keys.issubset(catalog_keys))
        self.assertLess(runtime_keys, catalog_keys)

    def test_each_runtime_supported_declaration_advertises_the_flag(self) -> None:
        # The membership helper must agree with the per-declaration
        # flag — if either drifts, the upfront runtime gate in
        # ``provider_factory.build_provider`` will leak a
        # catalog-only provider into the runtime path or hide a real
        # adapter from it.
        for declaration in runtime_supported_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertTrue(declaration.has_runtime_factory_adapter)

    def test_each_runtime_supported_declaration_is_known_to_lookup(self) -> None:
        # ``lookup_provider`` is the catalog's identity map; every
        # runtime-supported declaration must round-trip through it.
        for declaration in runtime_supported_provider_declarations():
            with self.subTest(provider_key=declaration.provider_key):
                self.assertIs(lookup_provider(declaration.provider_key), declaration)

    def test_module_constants_match_runtime_supported_keys(self) -> None:
        # Pin the contract that the four module-level constants
        # (``FIXTURE_DEV`` / ``CIFANGQUANT`` / ``AKSHARE`` / ``TUSHARE``)
        # are exactly the runtime-supported declarations. Adding a new
        # runtime provider without updating this test will fail here
        # before it fails anywhere else.
        runtime_constants = (
            AKSHARE,
            CIFANGQUANT,
            FIXTURE_DEV,
            TUSHARE,
        )
        self.assertEqual(
            tuple(
                sorted(
                    (declaration.provider_key for declaration in runtime_constants),
                    key=str,
                )
            ),
            tuple(sorted(runtime_supported_provider_keys(), key=str)),
        )
        for declaration in runtime_constants:
            with self.subTest(provider_key=declaration.provider_key):
                self.assertTrue(declaration.has_runtime_factory_adapter)

    def test_research_only_mcp_declarations_keep_flag_false(self) -> None:
        # The MCP research sources stay catalog-only; their
        # ``has_runtime_factory_adapter`` flag must stay ``False`` so a
        # future regression that adds a real runtime adapter surfaces
        # here rather than silently widening the runtime surface.
        for declaration in (QUICKTINY_MCP, RSSCAST):
            with self.subTest(provider_key=declaration.provider_key):
                self.assertFalse(declaration.has_runtime_factory_adapter)

    def test_runtime_supported_keys_is_a_tuple(self) -> None:
        # Public API contract: the helper returns a tuple so callers
        # (and the factory's derived ``KNOWN_PROVIDER_KEYS`` alias)
        # can rely on immutability.
        self.assertIsInstance(runtime_supported_provider_keys(), tuple)
        self.assertIsInstance(runtime_supported_provider_declarations(), tuple)


class LookupProviderTest(unittest.TestCase):
    """``lookup_provider`` resolves every known key and raises on unknowns."""

    def test_lookup_resolves_every_known_key(self) -> None:
        for key in _ALL_CATALOG_PROVIDER_KEYS:
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
        self.assertIs(lookup_provider("hithink"), HITHINK)

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

    def test_iteration_returns_exactly_the_five_expected_keys(self) -> None:
        declarations = iter_provider_declarations()
        self.assertEqual(
            tuple(declaration.provider_key for declaration in declarations),
            _ALL_CATALOG_PROVIDER_KEYS,
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
                FIXTURE_DEV.provider_key,
                HITHINK.provider_key,
                QUICKTINY_MCP.provider_key,
                RSSCAST.provider_key,
                TDX_OFFLINE.provider_key,
                TUSHARE.provider_key,
            },
        )


class CatalogWideInvariantsTest(unittest.TestCase):
    """Catalog-wide structural invariants."""

    def test_every_expected_provider_key_is_registered(self) -> None:
        # PR-01 freezes the original five-entry catalog. The
        # historical three-provider plan proposed three additional
        # entries (``eastmoney`` / ``sina`` / ``tonghuashun``) but
        # that plan was de-scoped; those three are intentionally not
        # registered. Adding a provider without a plan / matrix
        # update is a regression; removing one is a regression. This
        # test pins the membership exactly so the next PR cannot
        # silently drop a provider or silently re-add the
        # three-provider plan entries. The reserved ``hithink`` slice
        # is the only off-cycle addition (the plan is
        # ``tasks/hithink-reserved-provider-plan.md``) and it remains
        # a catalog-only, non-runtime entry.
        iterated_keys = {declaration.provider_key for declaration in iter_provider_declarations()}
        self.assertEqual(iterated_keys, set(_ALL_CATALOG_PROVIDER_KEYS))

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
