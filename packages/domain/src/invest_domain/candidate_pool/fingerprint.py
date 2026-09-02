"""Deterministic market-data fingerprint for the selected DailyBar revisions.

The candidate-pool calculator picks at most one :class:`DailyBar`
revision per ``(instrument_id, trade_date, adjustment)`` identity. To
turn that exact selection into an audit-stable run identity, this
module computes a canonical SHA-256 fingerprint over the selected
revisions.

Guarantees enforced here:

- order-independent: the result depends only on the set of selected
  revisions, not on the order the caller hands them in;
- deterministic: the same selection always produces the same digest;
- revision-sensitive: a changed selected revision yields a different
  fingerprint even when the underlying business ``row_hash`` is
  unchanged (so two candidate-run identities are always distinguishable);
- duplicate-rejecting: two :class:`DailyBar` rows sharing the
  ``(instrument_id, trade_date, adjustment, revision)`` identity cannot
  both be selected.

The canonical payload per bar is restricted to the exact selected
identity: instrument UUID string, ``trade_date`` ISO date, ``adjustment``
value, ``revision`` and the validated ``row_hash``. Audit fields
(``source``, ``observed_at``, ``provider_key`` ...) are deliberately
excluded so that re-collecting the same logical rows yields the same
fingerprint.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from invest_domain.market_data.models import DailyBar
from invest_domain.market_data.values import Adjust
from invest_domain.shared.canonical import content_hash


def _require_daily_bar(bar: object) -> DailyBar:
    if not isinstance(bar, DailyBar):
        raise TypeError(
            "compute_market_data_fingerprint requires DailyBar instances, "
            f"got {type(bar).__name__}"
        )
    if not isinstance(bar.row_hash, str) or not bar.row_hash.strip():
        raise ValueError(
            "compute_market_data_fingerprint requires bars with a validated row_hash"
        )
    return bar


def _identity_key(bar: DailyBar) -> tuple[UUID, date, Adjust, int]:
    return (bar.instrument_id.value, bar.trade_date, bar.adjustment, bar.revision)


def _bar_payload(bar: DailyBar) -> dict[str, object]:
    return {
        "adjustment": bar.adjustment.value,
        "instrument_id": str(bar.instrument_id.value),
        "revision": bar.revision,
        "row_hash": bar.row_hash,
        "trade_date": bar.trade_date.isoformat(),
    }


def compute_market_data_fingerprint(bars: Iterable[DailyBar]) -> str:
    """Return the deterministic SHA-256 fingerprint of the selected DailyBars.

    The returned 64-character lowercase hex string is the digest of the
    canonical JSON encoding of the sorted selected identities, computed
    via :func:`invest_domain.shared.canonical.content_hash`.

    Raises:
        TypeError: if any element of ``bars`` is not a :class:`DailyBar`.
        ValueError: if any bar is missing a validated ``row_hash``, or if two bars share the same
            ``(instrument_id, trade_date, adjustment, revision)`` identity.
    """

    selected: list[DailyBar] = [_require_daily_bar(bar) for bar in bars]
    seen: set[tuple[UUID, date, Adjust, int]] = set()
    for bar in selected:
        key = _identity_key(bar)
        if key in seen:
            raise ValueError(
                "duplicate DailyBar identity "
                f"(instrument_id={key[0]}, trade_date={key[1].isoformat()}, "
                f"adjustment={key[2].value}, revision={key[3]}); "
                "candidate-pool selection must yield at most one revision per identity"
            )
        seen.add(key)

    selected.sort(
        key=lambda bar: (
            bar.instrument_id.value.bytes,
            bar.trade_date,
            bar.adjustment.value,
            bar.revision,
        )
    )

    return content_hash([_bar_payload(bar) for bar in selected])


__all__ = ["compute_market_data_fingerprint"]
