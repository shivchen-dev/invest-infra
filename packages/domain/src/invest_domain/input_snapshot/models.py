"""Pure domain models for the ``input_snapshot`` bounded context.

The ``input_snapshot`` bounded context pins the exact instrument
universe consumed by one candidate-pool calculation (ADR-0008 / plan
§5.6). Persisting the membership list and its deterministic
``content_hash`` lets downstream tooling audit, replay and re-derive
historical runs even after the live universe has drifted.

The module currently exposes one value object:

- :class:`InputSnapshot` — the immutable, hash-pinned record of one
  membership list. :meth:`InputSnapshot.create` is the only sanctioned
  constructor for fresh snapshots because it is the sole producer of a
  correct ``content_hash``. Loading from storage constructs the object
  directly with all fields populated.

The model is deliberately infrastructure-free: no SQLAlchemy, Alembic,
Dagster or environment access. ``datetime.now(timezone.utc)`` and
``uuid.uuid4`` are referenced only as defaults for the
:meth:`InputSnapshot.create` factory, never at module-import time, so
the model itself stays deterministic for tests that pin
``id_factory`` / ``now_factory``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

_CONTENT_HASH_HEX_LEN: int = 64


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    """The hash-pinned record of the instrument universe for one run.

    Mirrors ``analytics.input_snapshots`` (PR-07):

    - ``id`` (uuid PK) — surrogate identifier.
    - ``snapshot_date`` (date) — the trading day the snapshot describes
      (Asia/Shanghai local calendar).
    - ``instrument_ids`` (tuple[UUID, ...]) — the membership list,
      stored in the same lexicographic byte order used to compute
      ``content_hash``.
    - ``content_hash`` (varchar(64)) — lowercase hex SHA-256 digest of
      the concatenated big-endian bytes of ``instrument_ids`` sorted
      by their raw byte representation.
    - ``row_count`` (integer) — ``len(instrument_ids)``. Mirrored from
      the jsonb payload so the calculator can fast-path equality
      checks without expanding the payload.
    - ``created_at`` (timestamptz) — audit timestamp, timezone-aware
      UTC.

    Invariants enforced in :meth:`__post_init__`:

    - ``instrument_ids`` is non-empty and contains no duplicates.
    - ``row_count`` equals ``len(instrument_ids)`` (and therefore
      ``>= 1``).
    - ``content_hash`` is exactly 64 lowercase hex characters.

    Use :meth:`create` to build a fresh snapshot: it allocates the
    ``id`` and ``created_at``, sorts the membership list by UUID bytes
    and computes the ``content_hash`` so the storage layer can persist
    the row without re-deriving the digest.
    """

    id: UUID
    snapshot_date: date
    instrument_ids: tuple[UUID, ...]
    content_hash: str
    row_count: int
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError(
                f"InputSnapshot.id must be a UUID, got {type(self.id).__name__}"
            )
        if not isinstance(self.snapshot_date, date):
            raise TypeError(
                "InputSnapshot.snapshot_date must be a date, "
                f"got {type(self.snapshot_date).__name__}"
            )
        if not isinstance(self.instrument_ids, tuple):
            raise ValueError("InputSnapshot.instrument_ids must be a tuple[UUID, ...]")
        for entry in self.instrument_ids:
            if not isinstance(entry, UUID):
                raise TypeError(
                    "InputSnapshot.instrument_ids must contain only UUID instances, "
                    f"got {type(entry).__name__}"
                )
        if not self.instrument_ids:
            raise ValueError("InputSnapshot.instrument_ids must not be empty")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("InputSnapshot.instrument_ids must not contain duplicates")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool):
            raise TypeError(
                f"InputSnapshot.row_count must be an int, got {type(self.row_count).__name__}"
            )
        if self.row_count != len(self.instrument_ids):
            raise ValueError(
                "InputSnapshot.row_count must equal len(instrument_ids) "
                f"({self.row_count} != {len(self.instrument_ids)})"
            )
        if self.row_count < 1:
            raise ValueError(
                f"InputSnapshot.row_count must be >= 1, got {self.row_count}"
            )
        if not isinstance(self.content_hash, str):
            raise TypeError(
                "InputSnapshot.content_hash must be a str, "
                f"got {type(self.content_hash).__name__}"
            )
        if len(self.content_hash) != _CONTENT_HASH_HEX_LEN:
            raise ValueError(
                "InputSnapshot.content_hash must be exactly "
                f"{_CONTENT_HASH_HEX_LEN} lowercase hex characters, "
                f"got length {len(self.content_hash)}"
            )
        _require_aware_utc(self.created_at, "InputSnapshot.created_at")

    @classmethod
    def create(
        cls,
        snapshot_date: date,
        instrument_ids: Sequence[UUID] | Iterable[UUID],
        *,
        id_factory: Callable[[], UUID] = uuid4,
        now_factory: Callable[[], datetime] = _utcnow,
    ) -> "InputSnapshot":
        """Build a fresh snapshot with deterministic ``content_hash``.

        ``instrument_ids`` may be supplied in any order; the factory
        sorts the entries by their raw 16-byte big-endian UUID
        representation before hashing, so the resulting ``content_hash``
        is independent of the input ordering and stable across
        processes, platforms and Python versions.

        ``id_factory`` and ``now_factory`` exist for deterministic
        tests; production code can rely on the defaults
        (``uuid4`` / ``datetime.now(timezone.utc)``).
        """
        materialised = tuple(instrument_ids)
        if not materialised:
            raise ValueError("InputSnapshot.create requires at least one instrument_id")
        for entry in materialised:
            if not isinstance(entry, UUID):
                raise TypeError(
                    "InputSnapshot.create instrument_ids must contain only UUID "
                    f"instances, got {type(entry).__name__}"
                )
        sorted_uuids = tuple(sorted(materialised, key=lambda value: value.bytes))
        if len(set(sorted_uuids)) != len(sorted_uuids):
            raise ValueError("InputSnapshot.create instrument_ids must not contain duplicates")
        content_hash = hashlib.sha256(
            b"".join(entry.bytes for entry in sorted_uuids)
        ).hexdigest()
        return cls(
            id=id_factory(),
            snapshot_date=snapshot_date,
            instrument_ids=sorted_uuids,
            content_hash=content_hash,
            row_count=len(sorted_uuids),
            created_at=now_factory(),
        )


__all__ = ["InputSnapshot"]


def _require_aware_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime (UTC recommended)")