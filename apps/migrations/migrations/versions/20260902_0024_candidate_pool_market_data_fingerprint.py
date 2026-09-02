"""Candidate pool market-data fingerprint (bounded storage-schema slice).

Revision ID: 20260902_0024
Revises: 20260826_0023
Create Date: 2026-09-02

Adds ``analytics.candidate_pool_runs.market_data_fingerprint`` so each
candidate-pool run is bound to the exact set of market-data revisions
that fed it. The natural unique key
``(trade_date, algorithm_key, algorithm_version, parameter_hash,
input_snapshot_id, market_data_fingerprint)`` is what guarantees the
immutable run identity — two distinct runs are only allowed to share
the prior five columns when they also share the same fingerprint, so a
re-run with different market data creates a new row instead of
overwriting the audit history.

The upgrade is safe for the existing fleet of candidate-pool rows:

- ``market_data_fingerprint`` is added as a NULLABLE ``VARCHAR(64)`` so
  the column append itself cannot fail on a populated table;
- every legacy row is backfilled with a deterministic per-row
  lowercase 64-hex sentinel built from the built-in ``md5()``
  function (``md5('legacy:' || id::text) || md5('legacy2:' || id::text)``),
  then the column is tightened to ``NOT NULL`` so every subsequent
  insert must supply a value;
- a ``CHECK`` constraint enforces the 64-character lowercase-hex
  shape so a buggy application-service path cannot smuggle a malformed
  value past the validator;
- the prior unique constraint ``uq_candidate_pool_runs_natural_key``
  is dropped and replaced by one with the same name that now includes
  ``market_data_fingerprint`` after ``input_snapshot_id``.

The downgrade is **only lossless when the legacy five-part natural key
is still unique** in ``analytics.candidate_pool_runs`` — that is, when
no two rows share ``(trade_date, algorithm_key, algorithm_version,
parameter_hash, input_snapshot_id)`` while differing on
``market_data_fingerprint``. Once the six-part key has been live long
enough for distinct fingerprints to accumulate per legacy key tuple,
recreating the five-part unique constraint on the way down would
fail because the constraint recreation cannot succeed for duplicate
key tuples. ``downgrade()`` therefore performs a bounded, existence-
based preflight at its very start: a ``GROUP BY`` over the five legacy
columns with ``HAVING COUNT(*) > 1`` raises a clear exception before
any schema mutation when any conflict exists, and
``analytics.candidate_pool_runs`` / ``analytics.candidate_pool_items``
rows are never deleted, merged, overwritten or otherwise mutated as
part of either upgrade or downgrade.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0024"
down_revision: str | None = "20260826_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "candidate_pool_runs"
_SCHEMA = "analytics"
_COLUMN = "market_data_fingerprint"
_CHECK_NAME = "ck_candidate_pool_runs_market_data_fingerprint_lower_hex64"
_NATURAL_KEY_NAME = "uq_candidate_pool_runs_natural_key"
_BACKFILL_SQL = (
    "UPDATE analytics.candidate_pool_runs "
    "SET market_data_fingerprint = "
    "md5('legacy:' || id::text) || md5('legacy2:' || id::text) "
    "WHERE market_data_fingerprint IS NULL"
)
_DOWNGRADE_PREFLIGHT_SQL = (
    "SELECT EXISTS ("
    "SELECT 1 FROM analytics.candidate_pool_runs "
    "GROUP BY trade_date, algorithm_key, algorithm_version, parameter_hash, input_snapshot_id "
    "HAVING COUNT(*) > 1) AS has_legacy_natural_key_conflict"
)


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.String(length=64), nullable=True),
        schema=_SCHEMA,
    )
    op.execute(sa.text(_BACKFILL_SQL))
    op.alter_column(
        _TABLE,
        _COLUMN,
        existing_type=sa.String(length=64),
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        _CHECK_NAME,
        _TABLE,
        "market_data_fingerprint ~ '^[0-9a-f]{64}$'",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        _NATURAL_KEY_NAME,
        _TABLE,
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        _NATURAL_KEY_NAME,
        _TABLE,
        [
            "trade_date",
            "algorithm_key",
            "algorithm_version",
            "parameter_hash",
            "input_snapshot_id",
            _COLUMN,
        ],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    has_conflict = op.get_bind().execute(
        sa.text(_DOWNGRADE_PREFLIGHT_SQL),
    ).scalar()
    if has_conflict:
        raise RuntimeError(
            "candidate_pool_runs legacy five-part natural key is no longer "
            "unique on (trade_date, algorithm_key, algorithm_version, "
            "parameter_hash, input_snapshot_id); downgrade cannot recreate "
            "uq_candidate_pool_runs_natural_key without mutating business "
            "rows, so the migration aborts before any schema change. "
            "Resolve the duplicate groups first (e.g. by archiving rows "
            "out-of-band) and re-run downgrade."
        )
    op.drop_constraint(
        _NATURAL_KEY_NAME,
        _TABLE,
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        _NATURAL_KEY_NAME,
        _TABLE,
        [
            "trade_date",
            "algorithm_key",
            "algorithm_version",
            "parameter_hash",
            "input_snapshot_id",
        ],
        schema=_SCHEMA,
    )
    op.drop_constraint(
        _CHECK_NAME,
        _TABLE,
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(_TABLE, _COLUMN, schema=_SCHEMA)
