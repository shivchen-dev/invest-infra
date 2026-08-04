"""Unit tests for the V2 provider routing layer (PR-05).

PR-05 (see
``docs/plan/invest-infra-v2-all-data-sources-integration-plan.md``
Task 5 / PR-05) introduces a pure, deterministic
:func:`invest_pipeline.provider_routing.select_providers` function
and a read-only :func:`invest_pipeline.provider_routing.calculate_coverage`
calculator. These tests cover the routing layer only; the coverage
matrix has its own module (``test_provider_routing_coverage.py``)
and the catalogue-level invariants continue to live in
``test_provider_catalog.py``.

The tests assert:

* The dataset registry (:mod:`invest_pipeline.provider_routing.datasets`)
  freezes the five datasets and the capability they each require.
* :func:`select_providers` rejects declarations missing the required
  capability (capability mismatch).
* :func:`select_providers` honours ``enabled_by_default`` and refuses
  to enable a third-party API silently.
* :func:`select_providers` rejects ``RESEARCH_ONLY`` providers for the
  ETF daily-bars / ETF instruments surfaces — the matrix §5.4
  "no research-only source as production SLA" rule.
* :func:`select_providers` returns a deterministic, sorted tuple so
  the coverage calculator can rely on the result order.
* The :class:`NoEligibleProviderError` carries the dataset string as
  its first argument so callers can introspect the request.

The tests construct fresh
:class:`invest_pipeline.provider_catalog.ProviderDeclaration` instances
locally rather than reusing the module-level catalog constants; the
intent is to exercise the routing function independently of the
catalog so a future catalog edit cannot accidentally mask a routing
regression. The catalogue-level invariants stay in
``test_provider_catalog.py``.
"""

from __future__ import annotations

import unittest

from invest_pipeline.provider_catalog import (
    AKSHARE,
    CIFANGQUANT,
    FIXTURE_DEV,
    QUICKTINY_MCP,
    RSSCAST,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
)
from invest_pipeline.provider_routing.datasets import (
    DATASET_CAPABILITIES,
    Dataset,
    dataset_requires_capability,
    required_capability_for,
)
from invest_pipeline.provider_routing.selection import (
    NoEligibleProviderError,
    RoutingRequest,
    select_providers,
)


def _make_declaration(
    *,
    provider_key: str,
    role: ProviderRole,
    capabilities: tuple[ProviderCapability, ...],
    enabled_by_default: bool,
) -> ProviderDeclaration:
    """Build a fresh :class:`ProviderDeclaration` for routing tests.

    The helper is local to the test module so the tests do not depend
    on the catalogue module-level constants. The defaults are
    deterministic and the dataclass' ``frozen=True`` semantics keep
    the helper safe to use in subTests.
    """

    return ProviderDeclaration(
        provider_key=provider_key,
        role=role,
        capabilities=capabilities,
        enabled_by_default=enabled_by_default,
    )


class DatasetRegistryTest(unittest.TestCase):
    """The :class:`Dataset` enum and capability mapping are frozen by PR-05."""

    def test_dataset_enum_has_the_five_expected_values(self) -> None:
        # The five dataset strings are persisted in raw.provider_*
        # and must not change without a migration. Pin them so a
        # future regression surfaces here.
        self.assertEqual(
            tuple(member.value for member in Dataset),
            (
                "etf_daily_bars",
                "etf_instruments",
                "index_daily_bars",
                "research",
                "market_snapshot",
            ),
        )

    def test_dataset_capabilities_mapping_is_complete(self) -> None:
        # Every dataset has a required capability. A missing entry
        # would make :func:`select_providers` raise a ``KeyError``
        # instead of the documented :class:`NoEligibleProviderError`.
        self.assertEqual(set(DATASET_CAPABILITIES), set(Dataset))

    def test_etf_daily_bars_requires_etf_daily_bars_capability(self) -> None:
        self.assertTrue(
            dataset_requires_capability(Dataset.ETF_DAILY_BARS, ProviderCapability.ETF_DAILY_BARS)
        )
        self.assertIs(
            required_capability_for(Dataset.ETF_DAILY_BARS),
            ProviderCapability.ETF_DAILY_BARS,
        )

    def test_etf_instruments_requires_etf_master_data_capability(self) -> None:
        # The dataset string is ``etf_instruments`` to match the
        # existing raw.provider_* keys; the required capability is
        # ``ETF_MASTER_DATA`` so the routing layer filters the
        # catalog correctly.
        self.assertTrue(
            dataset_requires_capability(Dataset.ETF_INSTRUMENTS, ProviderCapability.ETF_MASTER_DATA)
        )
        self.assertIs(
            required_capability_for(Dataset.ETF_INSTRUMENTS),
            ProviderCapability.ETF_MASTER_DATA,
        )

    def test_index_daily_bars_requires_index_daily_bars_capability(self) -> None:
        self.assertTrue(
            dataset_requires_capability(
                Dataset.INDEX_DAILY_BARS, ProviderCapability.INDEX_DAILY_BARS
            )
        )

    def test_research_requires_research_capability(self) -> None:
        self.assertTrue(dataset_requires_capability(Dataset.RESEARCH, ProviderCapability.RESEARCH))

    def test_market_snapshot_requires_market_snapshot_capability(self) -> None:
        self.assertTrue(
            dataset_requires_capability(Dataset.MARKET_SNAPSHOT, ProviderCapability.MARKET_SNAPSHOT)
        )

    def test_required_capability_for_rejects_unknown_dataset(self) -> None:
        # A non-Dataset input would be a programming error. The
        # helper raises ``ValueError`` rather than silently returning
        # ``None`` so the call site surfaces the bug.
        with self.assertRaises(ValueError):
            required_capability_for("etf_daily_bars")  # type: ignore[arg-type]


class SelectProvidersCapabilityTest(unittest.TestCase):
    """Capability mismatch filters the candidate down to the matching declaration."""

    def test_capability_mismatch_excludes_non_advertising_declaration(self) -> None:
        # ``fixture_dev`` advertises ETF capabilities; ``quicktiny_mcp``
        # only advertises RESEARCH / MARKET_SNAPSHOT. The routing
        # layer must exclude Quicktiny from the ETF daily-bars
        # selection so the capability contract is enforced before
        # the enabled-by-default gate.
        declarations = (FIXTURE_DEV, QUICKTINY_MCP)
        selected = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_capability_mismatch_with_no_match_raises(self) -> None:
        # When no declaration advertises the required capability
        # the routing layer must surface a typed error rather than
        # silently returning an empty tuple; the coverage calculator
        # and the runtime factory rely on the typed error to drive
        # operator alerting.
        declarations = (QUICKTINY_MCP,)
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(ctx.exception.args[0], "etf_daily_bars")

    def test_capability_mismatch_error_carries_dataset_value(self) -> None:
        # The :class:`NoEligibleProviderError` first argument must be
        # the dataset string so operators can assert on the request
        # without parsing the error message.
        declarations = (QUICKTINY_MCP,)
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(declarations, Dataset.ETF_INSTRUMENTS)
        self.assertEqual(ctx.exception.args[0], "etf_instruments")
        self.assertIs(ctx.exception.dataset, Dataset.ETF_INSTRUMENTS)

    def test_etf_instruments_excludes_research_only_quicktiny(self) -> None:
        # Quicktiny advertises no ETF capability, so the
        # research-only rule does not even fire here. Pin the result
        # so a future capability-set regression on Quicktiny is
        # caught even before the research-only rule applies.
        declarations = (QUICKTINY_MCP,)
        with self.assertRaises(NoEligibleProviderError):
            select_providers(declarations, Dataset.ETF_INSTRUMENTS)


class SelectProvidersEnabledDefaultTest(unittest.TestCase):
    """The default-enabled gate mirrors matrix §6 ``enabled_by_default`` rule."""

    def test_enabled_only_filters_out_off_by_default_provider(self) -> None:
        # Build a local declaration that advertises ETF_DAILY_BARS
        # but stays ``enabled_by_default=False`` (the matrix §6
        # default for real providers). The routing layer must drop
        # it so dev / tests never silently call a third-party API.
        off_by_default = _make_declaration(
            provider_key="future_real_provider",
            role=ProviderRole.SECONDARY,
            capabilities=(ProviderCapability.ETF_DAILY_BARS,),
            enabled_by_default=False,
        )
        declarations = (FIXTURE_DEV, off_by_default)
        selected = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_enabled_only_false_keeps_off_by_default_provider(self) -> None:
        # Operators may want to inspect the full eligible set
        # without flipping the default; ``enabled_only=False`` is
        # the explicit opt-in. The off-by-default provider is then
        # considered eligible, ranked by ``provider_key``.
        off_by_default = _make_declaration(
            provider_key="zeta_provider",
            role=ProviderRole.SECONDARY,
            capabilities=(ProviderCapability.ETF_DAILY_BARS,),
            enabled_by_default=False,
        )
        declarations = (off_by_default, FIXTURE_DEV)
        selected = select_providers(
            declarations,
            Dataset.ETF_DAILY_BARS,
            enabled_only=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev", "zeta_provider"),
        )


class SelectProvidersResearchOnlyRejectionTest(unittest.TestCase):
    """``RESEARCH_ONLY`` providers are rejected for ETF production surfaces.

    The tests isolate the research-only rule by passing
    ``enabled_only=False`` so the matrix §5.4 contract is exercised
    independently of the matrix §6 default-enabled gate (which would
    otherwise drop the catalogued real providers before the
    research-only check fires).
    """

    def test_etf_daily_bars_rejects_research_only_akshare(self) -> None:
        # AkShare is catalogued as ``RESEARCH_ONLY`` per matrix §3
        # but advertises the ETF_DAILY_BARS capability. The routing
        # layer must drop it for the ETF daily-bars surface so the
        # matrix §5.4 "no research-only source as production SLA"
        # rule survives the catalog capability advertisement.
        # ``enabled_only=False`` keeps the focus on the
        # research-only rule; the only declaration in the input
        # set is the rejected AkShare so the selection is empty
        # by design.
        declarations = (AKSHARE,)
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(
                declarations,
                Dataset.ETF_DAILY_BARS,
                enabled_only=False,
            )
        self.assertEqual(ctx.exception.args[0], "etf_daily_bars")

    def test_etf_instruments_rejects_research_only_akshare(self) -> None:
        # Mirror of the daily-bars rule: the ETF master-data
        # surface is also a "ETF production" surface and rejects
        # ``RESEARCH_ONLY`` providers, even when they advertise the
        # required capability.
        declarations = (AKSHARE,)
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(
                declarations,
                Dataset.ETF_INSTRUMENTS,
                enabled_only=False,
            )
        self.assertEqual(ctx.exception.args[0], "etf_instruments")

    def test_index_daily_bars_keeps_research_only_provider(self) -> None:
        # The research-only-rejection rule is intentionally scoped
        # to the ETF production surfaces. The index / research /
        # market-snapshot surfaces must keep the research-only MCP
        # sources as eligible providers (that is their only
        # production-grade consumer).
        declarations = (AKSHARE, RSSCAST)
        selected = select_providers(
            declarations,
            Dataset.INDEX_DAILY_BARS,
            enabled_only=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("akshare", "rsscast"),
        )

    def test_research_surface_keeps_research_only_provider(self) -> None:
        declarations = (RSSCAST, QUICKTINY_MCP)
        selected = select_providers(
            declarations,
            Dataset.RESEARCH,
            enabled_only=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("quicktiny_mcp", "rsscast"),
        )

    def test_market_snapshot_surface_keeps_research_only_provider(self) -> None:
        declarations = (QUICKTINY_MCP, RSSCAST)
        selected = select_providers(
            declarations,
            Dataset.MARKET_SNAPSHOT,
            enabled_only=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("quicktiny_mcp",),
        )

    def test_research_only_rule_can_be_disabled_for_inspection(self) -> None:
        # Operators may want to inspect the full eligible set
        # including the research-only providers, so the rule is a
        # keyword that defaults to ``True`` and can be flipped off.
        declarations = (AKSHARE, FIXTURE_DEV)
        selected = select_providers(
            declarations,
            Dataset.ETF_DAILY_BARS,
            enabled_only=False,
            exclude_research_only_for_etf_daily_bars=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("akshare", "fixture_dev"),
        )


class SelectProvidersDeterministicOrderTest(unittest.TestCase):
    """The output is a sorted tuple so callers can rely on deterministic order."""

    def test_output_is_sorted_by_provider_key(self) -> None:
        declarations = (RSSCAST, FIXTURE_DEV, CIFANGQUANT)
        selected = select_providers(
            declarations,
            Dataset.INDEX_DAILY_BARS,
            enabled_only=False,
        )
        # RSSCAST and CIFANGQUANT both advertise INDEX_DAILY_BARS;
        # FIXTURE_DEV does not, so the surviving tuple must be in
        # alphabetical ``provider_key`` order.
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("cifangquant", "rsscast"),
        )

    def test_output_is_a_tuple(self) -> None:
        declarations = (FIXTURE_DEV,)
        selected = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertIsInstance(selected, tuple)

    def test_repeated_calls_with_same_input_return_equal_tuples(self) -> None:
        # Determinism is the property the coverage calculator
        # depends on; pin it here so a future refactor that
        # introduces non-determinism (for example set ordering)
        # surfaces immediately. ``enabled_only=False`` keeps the
        # test focused on determinism rather than the default gate.
        declarations = (AKSHARE, RSSCAST, FIXTURE_DEV, QUICKTINY_MCP)
        first = select_providers(declarations, Dataset.INDEX_DAILY_BARS, enabled_only=False)
        second = select_providers(declarations, Dataset.INDEX_DAILY_BARS, enabled_only=False)
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(declaration.provider_key for declaration in first),
            tuple(declaration.provider_key for declaration in second),
        )


class RoutingRequestTest(unittest.TestCase):
    """The :class:`RoutingRequest` dataclass is the explicit form of the call."""

    def test_routing_request_round_trip_returns_same_selection(self) -> None:
        declarations = (FIXTURE_DEV, CIFANGQUANT)
        request = RoutingRequest(
            dataset=Dataset.ETF_DAILY_BARS,
            declarations=declarations,
        )
        via_request = select_providers(request)
        via_kwargs = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(via_request, via_kwargs)

    def test_routing_request_ignores_positional_dataset(self) -> None:
        # When a :class:`RoutingRequest` is passed, the positional
        # ``dataset`` is ignored. The dataclass' own fields are
        # authoritative so a caller cannot accidentally route to
        # the wrong dataset.
        request = RoutingRequest(
            dataset=Dataset.ETF_DAILY_BARS,
            declarations=(FIXTURE_DEV,),
        )
        selected = select_providers(request, Dataset.RESEARCH)
        # ``fixture_dev`` does not advertise ``RESEARCH`` so the
        # request's own ``dataset=ETF_DAILY_BARS`` wins and the
        # selection picks ``fixture_dev`` (the only declaration
        # matching the required ETF capability).
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_routing_request_rejects_non_dataset_dataset(self) -> None:
        with self.assertRaises(TypeError):
            RoutingRequest(
                dataset="etf_daily_bars",  # type: ignore[arg-type]
                declarations=(FIXTURE_DEV,),
            )

    def test_routing_request_rejects_non_declaration_entry(self) -> None:
        with self.assertRaises(TypeError):
            RoutingRequest(
                dataset=Dataset.ETF_DAILY_BARS,
                declarations=(FIXTURE_DEV, "not_a_declaration"),  # type: ignore[arg-type]
            )

    def test_select_providers_without_dataset_raises_value_error(self) -> None:
        # The raw-sequence call shape requires an explicit dataset
        # so the caller cannot accidentally request "all
        # declarations" with no filter.
        with self.assertRaises(ValueError):
            select_providers((FIXTURE_DEV,))  # type: ignore[call-arg]

    def test_select_providers_rejects_non_sequence_declarations(self) -> None:
        with self.assertRaises(TypeError):
            select_providers(FIXTURE_DEV, Dataset.ETF_DAILY_BARS)  # type: ignore[arg-type]


class SelectProvidersCatalogIntegrationTest(unittest.TestCase):
    """End-to-end selection over the full catalog freezes the V2 routing story."""

    _FULL_CATALOG: tuple[ProviderDeclaration, ...] = (
        AKSHARE,
        CIFANGQUANT,
        FIXTURE_DEV,
        QUICKTINY_MCP,
        RSSCAST,
    )

    def test_etf_daily_bars_selection_over_full_catalog(self) -> None:
        # Over the full five-entry catalog the only on-by-default
        # provider for ETF daily bars is ``fixture_dev``. The
        # catalog's real providers advertise the capability but
        # either default off (``cifangquant``, ``akshare``) or are
        # research-only / out-of-scope for ETF (``akshare``,
        # ``rsscast``, ``quicktiny_mcp``). The historical
        # three-provider plan (``eastmoney`` / ``sina`` /
        # ``tonghuashun``) was de-scoped: those entries are not in
        # the catalog and the routing layer never observes them.
        declarations = self._FULL_CATALOG
        selected = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_etf_instruments_selection_over_full_catalog(self) -> None:
        declarations = self._FULL_CATALOG
        selected = select_providers(declarations, Dataset.ETF_INSTRUMENTS)
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("fixture_dev",),
        )

    def test_research_selection_over_full_catalog(self) -> None:
        declarations = self._FULL_CATALOG
        # No catalog entry is ``enabled_by_default=True`` for
        # RESEARCH, so the default-enabled gate must surface a
        # :class:`NoEligibleProviderError`.
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(declarations, Dataset.RESEARCH)
        self.assertEqual(ctx.exception.args[0], "research")

    def test_market_snapshot_selection_disables_default_gate(self) -> None:
        # ``enabled_only=False`` is the operator-facing opt-in for
        # the surfaces that have no on-by-default provider.
        declarations = self._FULL_CATALOG
        selected = select_providers(
            declarations,
            Dataset.MARKET_SNAPSHOT,
            enabled_only=False,
        )
        self.assertEqual(
            tuple(declaration.provider_key for declaration in selected),
            ("quicktiny_mcp",),
        )

    def test_index_daily_bars_full_catalog_with_default_enabled_gate(self) -> None:
        # The catalog's ``akshare`` provider advertises
        # ``INDEX_DAILY_BARS`` but defaults off per matrix §6, so
        # the default-enabled gate must surface a
        # :class:`NoEligibleProviderError` for ``INDEX_DAILY_BARS``
        # just like the RESEARCH surface. The historical
        # three-provider plan entries (``eastmoney`` / ``sina`` /
        # ``tonghuashun``) were de-scoped and are not in the
        # catalog; the routing layer never observes them.
        declarations = self._FULL_CATALOG
        with self.assertRaises(NoEligibleProviderError) as ctx:
            select_providers(declarations, Dataset.INDEX_DAILY_BARS)
        self.assertEqual(ctx.exception.args[0], "index_daily_bars")


class ThreeProviderPlanRoutingTest(unittest.TestCase):
    """The historical three-provider plan is de-scoped in this slice.

    The three-provider plan proposed ``eastmoney`` / ``sina`` /
    ``tonghuashun`` as independent V2 read-only providers. The plan
    has been de-scoped: the three sources are not selectable runtime
    providers in V2 and the catalog carries no
    :class:`ProviderDeclaration` for them. Their public
    historical-quotes endpoints remain internal upstreams of the
    AkShare aggregator (``ak.fund_etf_hist_sina`` /
    ``ak.fund_etf_hist_em``). The routing layer therefore never sees
    them, and the catalog-level de-scope is the only contract left.
    The routing-layer rules exercised here pin that contract: a
    locally-constructed :class:`ProviderDeclaration` that mirrors the
    historical three-provider plan shape is still subject to the
    catalog's research-only / default-disabled rules when the routing
    function is asked to evaluate it directly, but no such declaration
    lives in the catalog anymore.
    """

    def test_three_provider_plan_keys_are_unknown_to_lookup(self) -> None:
        # The catalog has no entry for the three-provider plan keys;
        # routing-layer tests therefore cannot reach them through
        # the catalog surface and the local-declaration form below
        # is the only contract left for the routing rules.
        # Pin the negative lookup so a future regression that
        # re-introduces one of the three entries surfaces here.
        from invest_pipeline.provider_catalog import lookup_provider

        for key in ("eastmoney", "sina", "tonghuashun"):
            with self.subTest(provider_key=key):
                with self.assertRaises(KeyError) as ctx:
                    lookup_provider(key)
                self.assertEqual(ctx.exception.args[0], key)

    def test_local_three_provider_shape_is_research_only_by_default(self) -> None:
        # The historical plan shape (three research-only providers
        # advertising ETF / index market-data capabilities and
        # defaulting off) is still evaluated correctly by the
        # routing layer when a caller passes an equivalent local
        # declaration. The routing rules therefore remain
        # observable for future plan resurrections without the
        # catalog carrying the entries.
        expected_capabilities = {
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_MASTER_DATA,
            ProviderCapability.INDEX_DAILY_BARS,
        }
        for key in ("eastmoney", "sina", "tonghuashun"):
            declaration = _make_declaration(
                provider_key=key,
                role=ProviderRole.RESEARCH_ONLY,
                capabilities=tuple(expected_capabilities),
                enabled_by_default=False,
            )
            with self.subTest(provider_key=key):
                self.assertFalse(declaration.enabled_by_default)
                self.assertTrue(
                    expected_capabilities.issubset(set(declaration.capabilities))
                )
                with self.assertRaises(NoEligibleProviderError) as ctx:
                    select_providers(
                        (declaration,),
                        Dataset.ETF_DAILY_BARS,
                        enabled_only=False,
                    )
                self.assertEqual(ctx.exception.args[0], "etf_daily_bars")

    def test_full_five_catalog_yields_only_fixture_dev_by_default(self) -> None:
        # End-to-end check over the full five-entry catalog: with
        # ``enabled_only=True`` every real provider (matrix §6
        # default-off) is dropped, leaving ``fixture_dev`` as the
        # sole eligible provider for the production ETF surfaces.
        # The historical three-provider plan entries were never in
        # the catalog; this assertion confirms the V2 routing
        # story does not depend on them.
        declarations = (
            AKSHARE,
            CIFANGQUANT,
            FIXTURE_DEV,
            QUICKTINY_MCP,
            RSSCAST,
        )
        selected = select_providers(declarations, Dataset.ETF_DAILY_BARS)
        self.assertEqual(
            tuple(d.provider_key for d in selected),
            ("fixture_dev",),
        )


if __name__ == "__main__":
    unittest.main()
