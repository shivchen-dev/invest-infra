# quicktiny MCP — status

Status: **declaration only / research-only**.

ARC facts:

- Archive used quicktiny MCP for report / market-snapshot helpers.

v2 boundaries:

- No ETF_DAILY_BARS capability is declared. quicktiny is explicitly out of
  scope as a standard ETF daily-bar Provider.
- v2 does not ship an adapter class for quicktiny. The capability
  declaration is recorded for ADR-0003 auditability and so any future
  research-only asset is constrained.
- The factory raises ``ProviderAdapterNotImplementedError`` if anyone
  tries to instantiate it.

If quicktiny is ever adopted for a non-ETF asset (e.g. a research report
snapshot), it must come with a new ADR and a separate fixture contract.
