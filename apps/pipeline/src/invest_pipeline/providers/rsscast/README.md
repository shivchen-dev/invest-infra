# RssCast — status

Status: **declaration only / out-of-scope for ETF daily bars**.

ARC facts:

- Archive used `data-pipeline/src/collector/rsscast.py` for stock / index
  MCP quotes.

v2 boundaries:

- No ETF_DAILY_BARS capability is declared. The capability declaration is
  explicit about this so a future contributor cannot accidentally treat
  RssCast as a v2 ETF daily-bar source.
- The declaration is recorded for auditability per ADR-0003; v2 does NOT
  ship an adapter class for RssCast.
- No `request_key`, fixture, or route may pretend to consume an ETF
  daily bar from RssCast.

If we ever adopt RssCast in v2 for non-ETF purposes (e.g. a research
report asset), it must be tracked as a research-only capability behind an
explicit ADR.
