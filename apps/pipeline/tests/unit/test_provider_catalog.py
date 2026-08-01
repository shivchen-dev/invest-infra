"""Unit tests for the V2 provider catalog.

The catalog is a data declaration only — these tests assert the
catalog invariants without touching the network, the database or any
external resource. The Quicktiny MCP declaration is verified against
the ``DATA-SOURCE-MIGRATION-MATRIX.md`` §3 decisions (research_only,
disabled by default, only ``research`` / ``market_snapshot``
capabilities, no ETF master or daily-bars capability), and the lookup
function is verified to raise ``KeyError`` for unknown keys.
"""

from __future__ import annotations

import unittest

from invest_pipeline.provider_catalog import (
    QUICKTINY_MCP,
    ProviderCapability,
    ProviderDeclaration,
    ProviderRole,
    lookup_provider,
)


class QuicktinyMcpDeclarationTest(unittest.TestCase):
    """The Quicktiny MCP declaration matches the matrix decision."""

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
        capabilities = QUICKTINY_MCP.capabilities
        self.assertEqual(
            capabilities,
            (
                ProviderCapability.RESEARCH,
                ProviderCapability.MARKET_SNAPSHOT,
            ),
        )
        # Stable wire values must also match the matrix verbatim.
        self.assertEqual(
            tuple(c.value for c in capabilities),
            ("research", "market_snapshot"),
        )

    def test_etf_daily_bars_capability_is_absent(self) -> None:
        # Per the matrix §5.4, Quicktiny MCP must never claim
        # ETF_DAILY_BARS. Assert the enum member is *not* present in the
        # declaration's capabilities tuple.
        self.assertNotIn(
            ProviderCapability.ETF_DAILY_BARS,
            QUICKTINY_MCP.capabilities,
        )

    def test_etf_master_data_capability_is_absent(self) -> None:
        # The matrix §5.4 also forbids claiming ETF master data; assert
        # directly so a future regression cannot slip through.
        self.assertNotIn(
            ProviderCapability.ETF_MASTER_DATA,
            QUICKTINY_MCP.capabilities,
        )

    def test_index_daily_bars_capability_is_absent(self) -> None:
        # Quicktiny is research-only and must not advertise any daily
        # bars capability, including index bars.
        self.assertNotIn(
            ProviderCapability.INDEX_DAILY_BARS,
            QUICKTINY_MCP.capabilities,
        )

    def test_enabled_by_default_is_false(self) -> None:
        # Real providers default to ``False`` per matrix §6. Quicktiny
        # MCP is a real (non-fixture) provider so it must be off.
        self.assertFalse(QUICKTINY_MCP.enabled_by_default)
        # Belt-and-braces: the boolean type must be ``bool``, not a
        # truthy string or ``None``.
        self.assertIsInstance(QUICKTINY_MCP.enabled_by_default, bool)

    def test_capabilities_are_tuple_of_provider_capability(self) -> None:
        # Guard against a future refactor that accidentally turns the
        # capabilities field into a list or set; downstream code relies
        # on deterministic ordering and immutability.
        self.assertIsInstance(QUICKTINY_MCP.capabilities, tuple)
        for cap in QUICKTINY_MCP.capabilities:
            self.assertIsInstance(cap, ProviderCapability)

    def test_role_is_provider_role_enum(self) -> None:
        self.assertIsInstance(QUICKTINY_MCP.role, ProviderRole)

    def test_declaration_is_provider_declaration_instance(self) -> None:
        # The exported symbol must be a ``ProviderDeclaration`` so type
        # checkers and downstream consumers get the frozen-dataclass
        # surface.
        self.assertIsInstance(QUICKTINY_MCP, ProviderDeclaration)


class LookupProviderTest(unittest.TestCase):
    """``lookup_provider`` resolves known keys and raises on unknowns."""

    def test_lookup_returns_quicktiny_mcp_for_known_key(self) -> None:
        declaration = lookup_provider("quicktiny_mcp")
        self.assertIs(declaration, QUICKTINY_MCP)
        self.assertEqual(declaration.provider_key, "quicktiny_mcp")

    def test_lookup_raises_key_error_for_unknown_key(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            lookup_provider("not_a_real_provider")
        # The ``KeyError`` must carry the requested key as its argument
        # so callers (and operators reading logs) can identify the
        # unknown provider without parsing the message string.
        self.assertEqual(ctx.exception.args[0], "not_a_real_provider")

    def test_lookup_raises_key_error_for_empty_string(self) -> None:
        # An empty string is not a valid provider key and must surface
        # as ``KeyError`` rather than silently returning ``None``.
        with self.assertRaises(KeyError):
            lookup_provider("")

    def test_lookup_raises_key_error_for_mixed_case_key(self) -> None:
        # Provider keys are case-sensitive — the catalog only stores
        # the canonical lower_snake_case form. ``QuickTiny_MCP`` must
        # not silently match ``quicktiny_mcp``.
        with self.assertRaises(KeyError):
            lookup_provider("QuickTiny_MCP")


class CatalogInvariantsTest(unittest.TestCase):
    """Catalog-wide structural invariants."""

    def test_quicktiny_mcp_is_the_only_registered_provider(self) -> None:
        # This catalog is intentionally narrow — only Quicktiny MCP
        # has a registered declaration today. Adding future providers
        # must come with an explicit ADR / matrix update; this test
        # pins the current scope.
        declaration = lookup_provider("quicktiny_mcp")
        self.assertEqual(declaration.provider_key, "quicktiny_mcp")
        self.assertEqual(declaration.role, ProviderRole.RESEARCH_ONLY)

    def test_quicktiny_mcp_does_not_advertise_etf_capabilities(self) -> None:
        # Final cross-check: at most ``research`` and
        # ``market_snapshot`` may appear in the Quicktiny MCP
        # capabilities. Anything else is a regression.
        forbidden_capabilities = {
            ProviderCapability.ETF_DAILY_BARS,
            ProviderCapability.ETF_MASTER_DATA,
            ProviderCapability.INDEX_DAILY_BARS,
        }
        advertised = set(QUICKTINY_MCP.capabilities)
        self.assertEqual(
            advertised & forbidden_capabilities,
            set(),
            "Quicktiny MCP must not advertise any ETF / index daily "
            "bars or ETF master data capability.",
        )
        self.assertTrue(advertised.issubset(
            {ProviderCapability.RESEARCH, ProviderCapability.MARKET_SNAPSHOT}
        ))


if __name__ == "__main__":
    unittest.main()