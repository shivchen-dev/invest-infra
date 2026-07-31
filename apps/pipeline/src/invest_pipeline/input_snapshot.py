from __future__ import annotations

from collections.abc import Callable
from datetime import date
from uuid import UUID

from invest_domain.input_snapshot import InputSnapshot
from invest_storage.unit_of_work import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]


def create_input_snapshot(
    uow_factory: UnitOfWorkFactory,
    snapshot_date: date,
    instrument_ids: list[UUID],
) -> InputSnapshot:
    if not instrument_ids:
        raise ValueError("instrument_ids must not be empty")
    if len(set(instrument_ids)) != len(instrument_ids):
        raise ValueError("instrument_ids must not contain duplicates")

    snapshot = InputSnapshot.create(snapshot_date, instrument_ids)
    with uow_factory() as uow:
        stored = uow.input_snapshot_repository.add(snapshot)
        uow.commit()
        return stored


__all__ = ["create_input_snapshot"]
