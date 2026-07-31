"""analytics.input_snapshots table (PR-07)

Revision ID: 20260731_0005
Revises: 20260731_0004
Create Date: 2026-07-31

PR-07 introduces the persistence layer for candidate-pool input snapshots
per plan §5.6 / ADR-0008:

- ``analytics.input_snapshots`` — one row per snapshot of the instrument
  universe that feeds a candidate-pool calculation. The table is the
  source of truth for ``analytics.candidate_pool_runs.input_snapshot_id``
  (introduced in PR-03) and lets replay / audit tooling reconstruct the
  exact input set a published run consumed, even after the live
  universe has drifted.

  Columns:
    - ``id`` (uuid PK) — surrogate identifier allocated by the storage
      layer; the natural business key is ``(snapshot_date, content_hash)``.
    - ``snapshot_date`` (date) — the trading day the snapshot describes
      (Asia/Shanghai local calendar; see ADR-0004). A given
      ``snapshot_date`` may legitimately carry several rows when the
      universe differs (e.g. universe re-derivation after a corporate
      action), which is why the unique key includes ``content_hash``.
    - ``instrument_ids`` (jsonb NOT NULL) — the ordered list of
      ``instrument_id`` UUIDs (canonical lowercase 8-4-4-4-12 form) that
      make up the snapshot. The application layer is responsible for
      storing the list in the same lexicographic byte order used to
      compute ``content_hash`` so the audit chain is unambiguous.
    - ``content_hash`` (varchar(64) NOT NULL) — lowercase hex SHA-256
      digest over the concatenated big-endian bytes of the sorted
      ``instrument_ids``. Fixed length 64 is enforced at the database
      level.
    - ``row_count`` (integer NOT NULL) — ``len(instrument_ids)``,
      duplicated for query convenience so the candidate-pool calculator
      can fast-path equality checks without expanding the jsonb payload.
      ``row_count >= 1`` is enforced because a snapshot with no inputs
      has nothing to compute.
    - ``created_at`` (timestamptz NOT NULL DEFAULT now()) — audit
      timestamp.

  Constraints:
    - ``uq_input_snapshots_date_hash`` — unique
      ``(snapshot_date, content_hash)``. Two snapshots on the same date
      with the same byte-sorted instrument set collapse to one row;
      distinct sets are kept distinct.
    - ``ck_input_snapshots_content_hash_len64`` — ``length(content_hash) = 64``.
    - ``ck_input_snapshots_row_count_positive`` — ``row_count >= 1``.

No foreign key targets ``core.instruments`` because the membership list
is encoded as a jsonb UUID array. Per ADR-0008 the application layer
guarantees referential integrity at write time (no snapshot row may
reference an instrument that does not exist in ``core.instruments``),
and the validator pipeline reconciles the membership list before any
candidate-pool run is published.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0005"
down_revision: str | None = "20260731_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "input_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("instrument_ids", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_input_snapshots"),
        sa.UniqueConstraint(
            "snapshot_date",
            "content_hash",
            name="uq_input_snapshots_date_hash",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_input_snapshots_content_hash_len64",
        ),
        sa.CheckConstraint(
            "row_count >= 1",
            name="ck_input_snapshots_row_count_positive",
        ),
        schema="analytics",
    )
    op.create_index(
        "ix_input_snapshots_snapshot_date",
        "input_snapshots",
        ["snapshot_date"],
        schema="analytics",
    )
    op.create_index(
        "ix_input_snapshots_content_hash",
        "input_snapshots",
        ["content_hash"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_input_snapshots_content_hash",
        table_name="input_snapshots",
        schema="analytics",
    )
    op.drop_index(
        "ix_input_snapshots_snapshot_date",
        table_name="input_snapshots",
        schema="analytics",
    )
    op.drop_table("input_snapshots", schema="analytics")