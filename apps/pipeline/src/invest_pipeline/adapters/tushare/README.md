# Tushare Pro

The adapter supports the existing ETF surfaces and the A-share stock
surfaces `stock_basic` and `daily`. Stock access is exposed by
`StockTushareProvider`; it is deliberately separate from the ETF provider.

The client resolves the configured token lazily from the centralized
credential store. Enable real calls with
`INVEST_PIPELINE_TUSHARE_ENABLED=true`; daily requests are unadjusted and use
Tushare's `YYYYMMDD` date format.
