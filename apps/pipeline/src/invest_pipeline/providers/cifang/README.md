# Cifang Quant ETF Provider — status

Status: **placeholder / secondary candidate (blocked by ADR-0003)**.

ARC facts:

- Archive (`data-pipeline/src/collector/cifang.py` + `src/config.py` +
  `scripts/cron_etf_kline_evening.py` + `scripts/sync_cifang_backfill.py`)
  used ``CIFANG_TOKEN`` and the base URL ``https://www.cifangquant.com/api``.
- Archive covered ETF list, real-time quotes, and historical daily K.
- Archive default was `qfq`.

v2 boundaries:

- M0 ADR-0005 freezes ``adjustment="none"``. The archive default ``qfq`` is
  explicitly **forbidden** for v2 production until a new ADR lifts this.
- The adapter (``apps/pipeline/src/invest_pipeline/providers/cifang/``)
  does not import any Cifang SDK and does not make HTTP calls.
- The settings class validates ``adjustment`` and refuses to construct
  with anything except ``none`` for ``Adjust``-typed queries.

To unlock real Cifang usage, an ADR + PR must:

- Confirm license / redistribution rights for production automation (O-1).
- Document the contract for ``adjustment="none"`` semantics, including
  how Cifang identifies the unadjusted K line.
- Provide a contract fixture suite (decimal OHLC, units, holidays).
- Re-introduce historical / intraday endpoints as separate typed methods
  if needed, each with their own capability declaration.
