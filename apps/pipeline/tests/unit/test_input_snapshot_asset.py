from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import dagster as dg
import invest_storage
from invest_domain.input_snapshot import InputSnapshot
from invest_domain.instruments import Instrument, InstrumentId, InstrumentType
from invest_pipeline import assets
from invest_pipeline.personal_universe import PersonalUniverse, ResolvedPersonalUniverse


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.session = MagicMock()

    def __enter__(self) -> _FakeUnitOfWork:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _instrument(symbol: str, instrument_id: UUID, exchange: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=f"{symbol} ETF",
        exchange=exchange,
        instrument_type=InstrumentType.ETF,
        instrument_id=InstrumentId(instrument_id),
    )


def test_etf_input_snapshot_uses_partition_date_and_resolved_personal_ids(
    monkeypatch,
) -> None:
    ids = [
        UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        UUID("00000000-0000-0000-0000-000000000001"),
    ]
    uow = _FakeUnitOfWork()
    engine = MagicMock()
    universe = PersonalUniverse(version=1, symbols=("510300", "510500"), content_hash="a" * 64)
    resolved = ResolvedPersonalUniverse(
        instruments=(
            _instrument("510300", ids[0], "SSE"),
            _instrument("510500", ids[1], "SZSE"),
        )
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(assets, "build_engine", lambda _url: engine)
    monkeypatch.setattr(assets, "session_factory", lambda _engine: MagicMock())
    monkeypatch.setattr(invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: uow)
    monkeypatch.setattr(assets, "load_personal_universe", lambda _path: universe)
    monkeypatch.setattr(assets, "resolve_personal_universe", lambda _u, _lookup: resolved)

    def _create(uow_factory, snapshot_date: date, instrument_ids: list[UUID]) -> InputSnapshot:
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
    result = assets.etf_input_snapshot.op.compute_fn.decorated_fn(
        dg.build_asset_context(partition_key="2026-07-31")
    )

    assert captured["snapshot_date"] == date(2026, 7, 31)
    assert captured["instrument_ids"] == ids
    assert callable(captured["uow_factory"])
    assert result.metadata["partition_key"] == "2026-07-31"
    assert result.metadata["row_count"] == 2
    assert result.metadata["universe_size"] == 2
    engine.dispose.assert_called_once_with()


def test_etf_input_snapshot_is_partitioned_and_depends_on_etf_instruments() -> None:
    assert isinstance(assets.etf_input_snapshot.partitions_def, dg.DailyPartitionsDefinition)
    assert dg.AssetKey("etf_instruments") in assets.etf_input_snapshot.dependency_keys
