from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import dagster as dg
import invest_storage
from invest_domain.input_snapshot import InputSnapshot
from invest_pipeline import assets


class _FakeUnitOfWork:
    def __init__(self, instrument_ids: list[UUID]) -> None:
        self.session = MagicMock()
        self.session.scalars.return_value.all.return_value = instrument_ids

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def test_etf_input_snapshot_uses_partition_date_and_all_etf_ids(
    monkeypatch,
) -> None:
    etf_ids = [
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        UUID("00000000-0000-0000-0000-000000000001"),
    ]
    uow = _FakeUnitOfWork(etf_ids)
    engine = MagicMock()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(assets, "build_engine", lambda _url: engine)
    monkeypatch.setattr(assets, "session_factory", lambda _engine: MagicMock())
    monkeypatch.setattr(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow)

    def _create(
        uow_factory,
        snapshot_date: date,
        instrument_ids: list[UUID],
    ) -> InputSnapshot:
        captured["uow_factory"] = uow_factory
        captured["snapshot_date"] = snapshot_date
        captured["instrument_ids"] = instrument_ids
        return InputSnapshot.create(
            snapshot_date,
            instrument_ids,
            id_factory=lambda: UUID("10000000-0000-0000-0000-000000000000"),
            now_factory=lambda: datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
        )

    monkeypatch.setattr(assets, "create_input_snapshot", _create)
    context = dg.build_asset_context(partition_key="2026-07-31")

    result = assets.etf_input_snapshot.op.compute_fn.decorated_fn(context)

    assert captured["snapshot_date"] == date(2026, 7, 31)
    assert captured["instrument_ids"] == etf_ids
    assert callable(captured["uow_factory"])
    uow.session.scalars.assert_called_once()
    statement = uow.session.scalars.call_args.args[0]
    sql = str(statement)
    assert "core.instruments" in sql
    assert "instrument_type" in sql
    assert "is_active" not in sql
    assert result.metadata["partition_key"] == "2026-07-31"
    assert result.metadata["row_count"] == 2
    engine.dispose.assert_called_once_with()


def test_etf_input_snapshot_is_partitioned_and_depends_on_etf_instruments() -> None:
    assert isinstance(assets.etf_input_snapshot.partitions_def, dg.DailyPartitionsDefinition)
    assert dg.AssetKey("etf_instruments") in assets.etf_input_snapshot.dependency_keys
