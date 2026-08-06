"""Application service for the read-only ``/api/v1/candidate-pool`` slice.

The service owns three read-side use cases the FastAPI router exposes:

* the most recent ``PUBLISHED`` candidate-pool run
  (:meth:`CandidatePoolQueryService.get_latest`),
* the diff of that latest run against the most recent earlier
  ``PUBLISHED`` run (:meth:`CandidatePoolQueryService.get_latest_diff`),
* the diff of any ``PUBLISHED`` run identified by ``run_id`` against its
  predecessor (:meth:`CandidatePoolQueryService.get_run_diff`).

The router delegates session handling, repository construction, the
``PUBLISHED`` filter, the input-snapshot lookup, the predecessor
selection, the included-only diff, the instrument lookup and the
:class:`sqlalchemy.exc.SQLAlchemyError` boundary to this service so the
HTTP layer only translates the small domain view dataclasses into
Pydantic response shapes and converts application exceptions into HTTP
errors.

Each repository is taken as a narrow :class:`typing.Protocol` so the
service depends only on the read-side surface it actually uses; the
dependency factory in :mod:`invest_api.dependencies` instantiates the
concrete
:class:`invest_storage.repositories.SqlAlchemyCandidatePoolRunRepository`,
:class:`invest_storage.repositories.SqlAlchemyCandidatePoolItemRepository`,
:class:`invest_storage.InputSnapshotRepository` and
:class:`invest_storage.repositories.SqlAlchemyInstrumentRepository` and
passes them in. There is intentionally no generic service framework
here: the application layer is a thin domain-use-case wrapper, not an
abstraction over FastAPI or SQLAlchemy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
)
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import Instrument
from invest_domain.instruments.models import InstrumentId
from sqlalchemy.exc import SQLAlchemyError

LATEST_LOOKBACK_LIMIT: int = 100
"""Maximum number of recent runs the predecessor-selection use case scans.

The run repository's :meth:`list_by_status` returns ``PUBLISHED`` runs
ordered by ``trade_date`` descending then ``id`` ascending; we walk the
page until we find a run whose ``trade_date`` is strictly less than the
current run's ``trade_date``, so the bound only needs to cover the
realistic gap between successive published trade days.
"""

MISSING_LATEST_DETAIL: str = "no published candidate pool found"
"""Exact 404 detail the router surfaces when no published run exists.

Kept as a module constant so the existing endpoint tests and any future
caller can assert the wire-format detail without re-deriving the
string.
"""

MISSING_RUN_DETAIL_TEMPLATE: str = "published candidate pool run {run_id} not found"
"""Format string the router substitutes ``run_id`` into for a missing run."""

MISSING_SNAPSHOT_DETAIL_TEMPLATE: str = (
    "input snapshot {snapshot_id} referenced by run {run_id} not found"
)
"""Format string the router substitutes into the sanitized 500 detail.

The router substitutes ``snapshot_id`` and ``run_id`` so the existing
wire-format detail survives the service extraction; the substitution
happens in the router because the application exception only carries
the identifiers.
"""

_QUERY_ERROR_DETAIL: str = "Candidate pool query failed"
"""Exact 500 detail the router surfaces for :class:`CandidatePoolQueryError`."""


class CandidatePoolRunReader(Protocol):
    """Narrow read-side surface of the candidate-pool run repository."""

    def get_by_id(self, run_id: UUID) -> CandidatePoolRun | None:
        """Return the run for ``run_id`` or ``None`` if absent."""

    def list_by_status(
        self,
        status: CandidatePoolStatus | str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CandidatePoolRun]:
        """Return runs in ``status`` ordered by ``trade_date`` desc then ``id`` asc."""


class CandidatePoolItemReader(Protocol):
    """Narrow read-side surface of the candidate-pool item repository."""

    def list_by_run_id(
        self,
        run_id: UUID,
        *,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[CandidatePoolItem]:
        """Return the items for ``run_id`` ordered by ``included`` desc then ``rank`` asc."""


class InputSnapshotReader(Protocol):
    """Narrow read-side surface of the input-snapshot repository."""

    def list_by_date(self, snapshot_date: date) -> list[InputSnapshot]:
        """Return snapshots for ``snapshot_date`` ordered by ``created_at`` asc."""


class InstrumentReader(Protocol):
    """Narrow read-side surface of the instrument repository."""

    def get_many_by_ids(
        self, instrument_ids: list[UUID | InstrumentId]
    ) -> dict[UUID, Instrument]:
        """Return a ``UUID -> Instrument`` map; missing rows are silently dropped."""


class CandidatePoolQueryError(RuntimeError):
    """Raised when any of the repositories raise :class:`SQLAlchemyError`.

    The HTTP layer converts this into a sanitized 500 response; the
    original driver-level exception is intentionally swallowed so the
    router never leaks a connection string or driver detail to the
    client.
    """


class CandidatePoolSnapshotMissingError(RuntimeError):
    """Raised when the snapshot referenced by a candidate-pool run is absent.

    Distinct from :class:`CandidatePoolQueryError` because the missing
    snapshot is a logical integrity violation (storage corruption) -
    not a transient driver error - so the router surfaces it as a
    non-sanitised ``500`` with the pre-existing detail string. The
    exception carries ``snapshot_id`` and ``run_id`` so the router can
    format the detail without re-reading the repositories.
    """

    def __init__(self, *, snapshot_id: UUID, run_id: UUID) -> None:
        self.snapshot_id = snapshot_id
        self.run_id = run_id
        super().__init__(
            MISSING_SNAPSHOT_DETAIL_TEMPLATE.format(
                snapshot_id=str(snapshot_id), run_id=str(run_id)
            )
        )


@dataclass(frozen=True, slots=True)
class CandidatePoolDiffEntryView:
    """One instrument entry in a candidate-pool diff bucket.

    Carries the raw ``instrument_id`` plus the resolved display fields
    so the router can render the diff without re-querying the
    instrument repository. ``symbol`` / ``name`` / ``exchange`` are
    ``None`` when the instrument row is missing; ordering is
    deterministic (``symbol`` ascending with ``instrument_id`` as the
    tiebreaker) and is applied by the service before the view is
    returned so the router does not need to re-sort.
    """

    instrument_id: UUID
    symbol: str | None
    name: str | None
    exchange: str | None


@dataclass(frozen=True, slots=True)
class LatestCandidatePoolView:
    """Small domain view backing :class:`CandidatePoolLatestResponse`.

    Bundles the published run, its referenced input snapshot, the
    per-instrument items and the resolved instrument map so the router
    only has to translate values into the Pydantic response shape.
    """

    run: CandidatePoolRun
    snapshot: InputSnapshot
    items: tuple[CandidatePoolItem, ...]
    instruments_by_id: dict[UUID, Instrument]


@dataclass(frozen=True, slots=True)
class CandidatePoolDiffView:
    """Small domain view backing :class:`CandidatePoolDiffResponse`.

    ``previous_trade_date`` is ``None`` when no earlier published run
    exists; in that case ``added`` carries every included instrument
    from the current run and ``retained`` / ``removed`` are both
    empty. Each bucket is pre-sorted (``symbol`` asc, ``instrument_id``
    asc) by the service.
    """

    trade_date: date
    previous_trade_date: date | None
    added: tuple[CandidatePoolDiffEntryView, ...]
    retained: tuple[CandidatePoolDiffEntryView, ...]
    removed: tuple[CandidatePoolDiffEntryView, ...]


class CandidatePoolQueryService:
    """Application service for the read-only candidate-pool use cases.

    The service owns the published-run filter, the predecessor
    selection, the snapshot lookup, the included-only diff and the
    :class:`SQLAlchemyError` -> :class:`CandidatePoolQueryError`
    translation. Domain-to-response mapping stays in the router so the
    application layer remains free of FastAPI / Pydantic imports.
    """

    def __init__(
        self,
        *,
        run_repository: CandidatePoolRunReader,
        item_repository: CandidatePoolItemReader,
        snapshot_repository: InputSnapshotReader,
        instrument_repository: InstrumentReader,
    ) -> None:
        self._runs = run_repository
        self._items = item_repository
        self._snapshots = snapshot_repository
        self._instruments = instrument_repository

    def get_latest(self) -> LatestCandidatePoolView | None:
        """Return the most recently published candidate-pool run, or ``None``.

        Selects the top row in ``PUBLISHED`` status (ordered by
        ``trade_date`` desc then ``id`` asc), resolves the input
        snapshot and per-instrument items, and joins the display fields
        for every item's instrument in a single repository call.
        Returns ``None`` when no published run exists;
        :class:`SQLAlchemyError` is translated to
        :class:`CandidatePoolQueryError` and a missing input snapshot
        surfaces as :class:`CandidatePoolSnapshotMissingError`.
        """

        try:
            published = self._runs.list_by_status(
                CandidatePoolStatus.PUBLISHED, limit=1, offset=0
            )
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc
        if not published:
            return None
        latest_run = published[0]

        snapshot = self._resolve_snapshot(latest_run)
        items = self._list_items(latest_run.id)
        instruments_by_id = self._resolve_instruments(items)

        return LatestCandidatePoolView(
            run=latest_run,
            snapshot=snapshot,
            items=items,
            instruments_by_id=instruments_by_id,
        )

    def get_latest_diff(self) -> CandidatePoolDiffView | None:
        """Diff the latest published run against the most recent earlier one.

        Returns ``None`` when no published run exists; the same
        :class:`CandidatePoolQueryError` /
        :class:`CandidatePoolSnapshotMissingError` translation rules as
        :meth:`get_latest` apply.
        """

        try:
            published = self._runs.list_by_status(
                CandidatePoolStatus.PUBLISHED, limit=1, offset=0
            )
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc
        if not published:
            return None
        return self._build_diff(published[0])

    def get_run_diff(self, run_id: UUID) -> CandidatePoolDiffView | None:
        """Diff the ``PUBLISHED`` run for ``run_id`` against its predecessor.

        Returns ``None`` when ``run_id`` does not exist or the
        resolved run is not in the ``PUBLISHED`` state so the router
        can surface a single indistinguishable ``404``. The same
        :class:`CandidatePoolQueryError` /
        :class:`CandidatePoolSnapshotMissingError` translation rules as
        :meth:`get_latest` apply.
        """

        try:
            current = self._runs.get_by_id(run_id)
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc
        if current is None or current.status is not CandidatePoolStatus.PUBLISHED:
            return None
        return self._build_diff(current)

    def _resolve_snapshot(self, run: CandidatePoolRun) -> InputSnapshot:
        try:
            snapshots_for_date = self._snapshots.list_by_date(run.trade_date)
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc
        matching = next(
            (snap for snap in snapshots_for_date if snap.id == run.input_snapshot_id),
            None,
        )
        if matching is None:
            raise CandidatePoolSnapshotMissingError(
                snapshot_id=run.input_snapshot_id,
                run_id=run.id,
            )
        return matching

    def _list_items(self, run_id: UUID) -> tuple[CandidatePoolItem, ...]:
        try:
            return tuple(self._items.list_by_run_id(run_id))
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc

    def _resolve_instruments(
        self, items: tuple[CandidatePoolItem, ...]
    ) -> dict[UUID, Instrument]:
        if not items:
            return {}
        try:
            return dict(self._instruments.get_many_by_ids([item.instrument_id for item in items]))
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc

    def _included_ids(self, items: tuple[CandidatePoolItem, ...]) -> set[UUID]:
        """Return the set of raw ``instrument_id`` UUIDs for included items only.

        Excluded items MUST NEVER participate in the diff: they reflect
        the input pool membership, not candidate pool membership, and
        would otherwise make "input pool unchanged" surfaces look like
        "candidate pool retained everything".
        """

        return {item.instrument_id.value for item in items if item.included}

    def _select_previous_published_run(
        self, current: CandidatePoolRun
    ) -> CandidatePoolRun | None:
        try:
            published = self._runs.list_by_status(
                CandidatePoolStatus.PUBLISHED,
                limit=LATEST_LOOKBACK_LIMIT,
                offset=0,
            )
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc
        return next(
            (
                run
                for run in published
                if run.trade_date < current.trade_date
            ),
            None,
        )

    def _build_diff_entries(
        self,
        instrument_ids: set[UUID],
        instruments_by_id: dict[UUID, Instrument],
    ) -> tuple[CandidatePoolDiffEntryView, ...]:
        entries = [
            CandidatePoolDiffEntryView(
                instrument_id=instrument_id,
                symbol=getattr(instruments_by_id.get(instrument_id), "symbol", None),
                name=getattr(instruments_by_id.get(instrument_id), "name", None),
                exchange=getattr(instruments_by_id.get(instrument_id), "exchange", None),
            )
            for instrument_id in instrument_ids
        ]
        entries.sort(
            key=lambda entry: (
                entry.symbol or "",
                str(entry.instrument_id),
            )
        )
        return tuple(entries)

    def _build_diff(self, current: CandidatePoolRun) -> CandidatePoolDiffView:
        current_items = self._list_items(current.id)
        current_ids = self._included_ids(current_items)

        previous = self._select_previous_published_run(current)

        if previous is None:
            instruments_by_id = self._resolve_instruments_for_ids(current_ids)
            return CandidatePoolDiffView(
                trade_date=current.trade_date,
                previous_trade_date=None,
                added=self._build_diff_entries(current_ids, instruments_by_id),
                retained=(),
                removed=(),
            )

        previous_items = self._list_items(previous.id)
        previous_ids = self._included_ids(previous_items)

        added_ids = current_ids - previous_ids
        removed_ids = previous_ids - current_ids
        retained_ids = current_ids & previous_ids

        instrument_ids = added_ids | removed_ids | retained_ids
        instruments_by_id = self._resolve_instruments_for_ids(instrument_ids)

        return CandidatePoolDiffView(
            trade_date=current.trade_date,
            previous_trade_date=previous.trade_date,
            added=self._build_diff_entries(added_ids, instruments_by_id),
            retained=self._build_diff_entries(retained_ids, instruments_by_id),
            removed=self._build_diff_entries(removed_ids, instruments_by_id),
        )

    def _resolve_instruments_for_ids(
        self, instrument_ids: set[UUID]
    ) -> dict[UUID, Instrument]:
        if not instrument_ids:
            return {}
        try:
            return dict(self._instruments.get_many_by_ids(list(instrument_ids)))
        except SQLAlchemyError as exc:
            raise CandidatePoolQueryError(_QUERY_ERROR_DETAIL) from exc


__all__ = [
    "CandidatePoolDiffEntryView",
    "CandidatePoolDiffView",
    "CandidatePoolItemReader",
    "CandidatePoolQueryError",
    "CandidatePoolQueryService",
    "CandidatePoolRunReader",
    "CandidatePoolSnapshotMissingError",
    "InputSnapshotReader",
    "InstrumentReader",
    "LATEST_LOOKBACK_LIMIT",
    "LatestCandidatePoolView",
    "MISSING_LATEST_DETAIL",
    "MISSING_RUN_DETAIL_TEMPLATE",
    "MISSING_SNAPSHOT_DETAIL_TEMPLATE",
]