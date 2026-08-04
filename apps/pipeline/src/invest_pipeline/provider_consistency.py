"""Provider-to-provider consistency comparison for ``DailyBar`` batches.

The comparison takes two :class:`ProviderBatch`es of :class:`DailyBar`
records (typically the same logical batch produced by two different
data Providers) and reports, without mutating the inputs, which keys are
common, which are missing on either side, and which fields disagree on
the common keys. The report is fully deterministic so it can be used as
the regression artifact for ``etf_daily_bars`` migration smoke tests
and for ad-hoc reconciliation runs.

Validation contract:

- Inputs MUST be :class:`ProviderBatch` instances whose ``records`` are
  :class:`DailyBar` objects; anything else raises ``TypeError``.
- Each batch MUST be non-empty and contain exactly one
  ``source.provider_key`` across all of its records.
- The two batches MUST come from different Providers; comparing a batch
  to itself or to a same-provider twin raises ``ValueError``.
- Each batch MUST contain exactly one ``adjustment`` value across all
  of its records; mixed adjustments raise ``ValueError``.
- Records are keyed by ``(instrument_id.value, trade_date,
  adjustment.value)``; duplicate keys inside either batch raise
  ``ValueError`` so the comparison never silently averages over
  collisions.

Comparison contract:

- ``matched_count`` counts keys present in BOTH batches (after the
  validation above), independent of whether any field mismatches.
- ``missing_left`` / ``missing_right`` are tuples of
  :class:`DailyBarKey` sorted by ``(instrument_id, trade_date,
  adjustment)``.
- ``mismatches`` is a tuple of :class:`FieldMismatch` for the seven
  business fields (``open``, ``high``, ``low``, ``close``, ``prev_close``,
  ``volume``, ``amount``) compared with exact numeric ``!=`` (no
  tolerance; equivalent Decimal scales compare equal), ordered first by key
  (same order as the missing tuples) then by the field order listed in
  ``_COMPARED_FIELDS``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from invest_domain.market_data.models import DailyBar, ProviderBatch

__all__ = [
    "COMPARED_FIELDS",
    "DailyBarKey",
    "FieldMismatch",
    "ProviderConsistencyReport",
    "compare_daily_bar_batches",
]


COMPARED_FIELDS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "prev_close",
    "volume",
    "amount",
)


@dataclass(frozen=True, slots=True, order=True)
class DailyBarKey:
    """The natural key for one :class:`DailyBar` in a consistency report.

    Stored as primitive ``(UUID, date, str)`` so the report can be
    serialized and sorted without dragging domain objects along.
    Slots + ``order=True`` give a stable sort order used for both
    ``missing_*`` tuples and the leading axis of ``mismatches``.
    """

    instrument_id: UUID
    trade_date: date
    adjustment: str


@dataclass(frozen=True, slots=True)
class FieldMismatch:
    """A single field-level disagreement on a shared ``DailyBarKey``.

    ``left_value`` and ``right_value`` are the raw values (still
    ``Decimal | None`` for the OHLCV fields) so callers can re-render
    them without re-reading the inputs. Both sides are guaranteed to be
    present (the function only compares keys that exist on both sides).
    """

    key: DailyBarKey
    field: str
    left_value: object
    right_value: object


@dataclass(frozen=True, slots=True)
class ProviderConsistencyReport:
    """Result of comparing two ``ProviderBatch[DailyBar]`` inputs.

    ``matched_count`` counts every key present in both batches,
    regardless of whether its fields agree. ``missing_left`` and
    ``missing_right`` are the keys present only on one side; both are
    sorted by :class:`DailyBarKey` so the report is deterministic.
    ``mismatches`` is sorted by ``(key, field)`` with ``field`` taken
    from :data:`COMPARED_FIELDS` order.
    """

    left_provider: str
    right_provider: str
    matched_count: int
    missing_left: tuple[DailyBarKey, ...]
    missing_right: tuple[DailyBarKey, ...]
    mismatches: tuple[FieldMismatch, ...]


def _require_provider_batch(value: object, *, arg_name: str) -> ProviderBatch[DailyBar]:
    if not isinstance(value, ProviderBatch):
        raise TypeError(
            f"{arg_name} must be a ProviderBatch instance "
            f"(got {type(value).__name__})"
        )
    return value  # type: ignore[return-value]


def _all_daily_bars(records: Sequence[DailyBar]) -> list[DailyBar]:
    for index, record in enumerate(records):
        if not isinstance(record, DailyBar):
            raise TypeError(
                f"ProviderBatch.records[{index}] must be a DailyBar instance "
                f"(got {type(record).__name__})"
            )
    return list(records)


def _require_non_empty_bar_list(
    records: list[DailyBar], *, batch_label: str
) -> list[DailyBar]:
    if not records:
        raise ValueError(
            f"{batch_label} ProviderBatch must contain at least one DailyBar; "
            f"reconciliation over empty batches is rejected"
        )
    return records


def _require_single_provider_key(
    bars: list[DailyBar], *, batch_label: str
) -> str:
    provider_keys = {bar.source.provider_key for bar in bars}
    if len(provider_keys) != 1:
        raise ValueError(
            f"{batch_label} ProviderBatch must contain a single source.provider_key, "
            f"found {sorted(provider_keys)}"
        )
    (provider_key,) = provider_keys
    return provider_key


def _require_single_adjustment(
    bars: list[DailyBar], *, batch_label: str
) -> str:
    adjustments = {bar.adjustment.value for bar in bars}
    if len(adjustments) != 1:
        raise ValueError(
            f"{batch_label} ProviderBatch must contain a single adjustment, "
            f"found {sorted(adjustments)}"
        )
    (adjustment,) = adjustments
    return adjustment


def _index_by_key(
    bars: list[DailyBar], *, batch_label: str
) -> dict[DailyBarKey, DailyBar]:
    index: dict[DailyBarKey, DailyBar] = {}
    for bar in bars:
        key = DailyBarKey(
            instrument_id=bar.instrument_id.value,
            trade_date=bar.trade_date,
            adjustment=bar.adjustment.value,
        )
        if key in index:
            raise ValueError(
                f"{batch_label} ProviderBatch contains duplicate key "
                f"(instrument_id={key.instrument_id}, trade_date={key.trade_date.isoformat()}, "
                f"adjustment={key.adjustment!r}); reconciliation refuses to silently "
                f"average over collisions"
            )
        index[key] = bar
    return index


def _compared_fields_mismatches(
    key: DailyBarKey, left: DailyBar, right: DailyBar
) -> tuple[FieldMismatch, ...]:
    mismatches: list[FieldMismatch] = []
    for field_name in COMPARED_FIELDS:
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value != right_value:
            mismatches.append(
                FieldMismatch(
                    key=key,
                    field=field_name,
                    left_value=left_value,
                    right_value=right_value,
                )
            )
    return tuple(mismatches)


def compare_daily_bar_batches(
    left: ProviderBatch[DailyBar],
    right: ProviderBatch[DailyBar],
) -> ProviderConsistencyReport:
    """Compare two ``ProviderBatch[DailyBar]`` instances and report differences.

    See the module docstring for the full validation and comparison
    contract. Raises ``TypeError`` for wrong input types and
    ``ValueError`` for same-provider comparison, mixed
    ``provider_key`` / ``adjustment`` within either batch, duplicate
    natural keys, or empty batches.
    """

    left_batch = _require_provider_batch(left, arg_name="left")
    right_batch = _require_provider_batch(right, arg_name="right")

    left_bars = _require_non_empty_bar_list(
        _all_daily_bars(left_batch.records), batch_label="left"
    )
    right_bars = _require_non_empty_bar_list(
        _all_daily_bars(right_batch.records), batch_label="right"
    )

    left_provider = _require_single_provider_key(left_bars, batch_label="left")
    right_provider = _require_single_provider_key(right_bars, batch_label="right")

    if left_provider == right_provider:
        raise ValueError(
            f"left and right ProviderBatch must come from different providers "
            f"(both report provider_key={left_provider!r}); consistency checks "
            f"against the same source are rejected"
        )

    _require_single_adjustment(left_bars, batch_label="left")
    _require_single_adjustment(right_bars, batch_label="right")

    left_index = _index_by_key(left_bars, batch_label="left")
    right_index = _index_by_key(right_bars, batch_label="right")

    missing_left = tuple(
        sorted(key for key in left_index if key not in right_index)
    )
    missing_right = tuple(
        sorted(key for key in right_index if key not in left_index)
    )

    common_keys = sorted(key for key in left_index if key in right_index)

    mismatches: list[FieldMismatch] = []
    matched_count = 0
    for key in common_keys:
        matched_count += 1
        mismatches.extend(
            _compared_fields_mismatches(key, left_index[key], right_index[key])
        )

    return ProviderConsistencyReport(
        left_provider=left_provider,
        right_provider=right_provider,
        matched_count=matched_count,
        missing_left=missing_left,
        missing_right=missing_right,
        mismatches=tuple(mismatches),
    )
