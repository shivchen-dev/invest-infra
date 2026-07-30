# AkShare ETF Provider — status

Status: **placeholder / research-only candidate**.

Why this directory exists:

- ARC-confirmed archive evidence shows AkShare (`akshare>=1.18.64`,
  `data-pipeline/src/collector/etf.py` + `quotes.py` + `scripts/save_trading_calendar.py`)
  covered ETF main data, historical daily quotes, and a trading-calendar
  helper. Authentication was via `AKSHARE_TOKEN`.
- ARC also noted archive records include rate-limit / blocking events.

What v2 does NOT do:

- Does **not** import the AkShare SDK.
- Does **not** call any public aggregator endpoint.
- Does **not** treat AkShare as a production SLA source.

What v2 ships for AkShare:

- A capability declaration that mirrors ARC facts (ETF instruments,
  ETF daily bars, ETF trading calendar, plus stock / index coverage).
- A redacted config object (URL placeholder, no real endpoint).
- A placeholder adapter that raises
  ``ProviderAdapterNotImplementedError`` for every fetch method until
  ADR-0003 explicitly selects AkShare and O-1 has been confirmed.

To unlock real AkShare usage, an ADR + PR must:

- Confirm license / redistribution rights for production automation.
- Re-confirm the endpoint and rate-limit guarantees (O-1 / O-6).
- Define the provider-level fixture contract (decimal OHLC, units, holidays).
- Pass through M0 codified secrets management (`INVEST_PIPELINE_AKSHARE_TOKEN`
  only injected into the Pipeline; never logged; never committed).
