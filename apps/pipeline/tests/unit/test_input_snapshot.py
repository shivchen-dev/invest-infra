from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from invest_domain.input_snapshot import InputSnapshot
from invest_pipeline.input_snapshot import create_input_snapshot

_SNAPSHOT_DATE = date(2026, 7, 31)
_IDS = [
    UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    UUID("00000000-0000-0000-0000-000000000001"),
]


def _build_uow() -> tuple[MagicMock, MagicMock]:
    uow = MagicMock(name="UnitOfWork")
    uow.__enter__.return_value = uow
    uow.input_snapshot_repository.add.side_effect = lambda snapshot: snapshot
    return uow, MagicMock(name="uow_factory", return_value=uow)


def test_create_input_snapshot_builds_persists_and_commits() -> None:
    uow, factory = _build_uow()

    result = create_input_snapshot(factory, _SNAPSHOT_DATE, list(_IDS))

    assert isinstance(result, InputSnapshot)
    assert result.snapshot_date == _SNAPSHOT_DATE
    assert result.instrument_ids == tuple(sorted(_IDS, key=lambda value: value.bytes))
    assert result.row_count == 2
    uow.input_snapshot_repository.add.assert_called_once_with(result)
    uow.commit.assert_called_once_with()
    uow.__exit__.assert_called_once_with(None, None, None)


def test_create_input_snapshot_returns_existing_snapshot_from_repository() -> None:
    uow, factory = _build_uow()
    existing = InputSnapshot.create(
        _SNAPSHOT_DATE,
        _IDS,
        id_factory=uuid4,
        now_factory=lambda: datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
    )
    uow.input_snapshot_repository.add.return_value = existing
    uow.input_snapshot_repository.add.side_effect = None

    result = create_input_snapshot(factory, _SNAPSHOT_DATE, list(_IDS))

    assert result is existing
    uow.commit.assert_called_once_with()


@pytest.mark.parametrize("instrument_ids", [[], list(_IDS) + [_IDS[0]]])
def test_create_input_snapshot_rejects_invalid_membership(
    instrument_ids: list[UUID],
) -> None:
    _, factory = _build_uow()

    with pytest.raises(ValueError):
        create_input_snapshot(factory, _SNAPSHOT_DATE, instrument_ids)

    factory.assert_not_called()
