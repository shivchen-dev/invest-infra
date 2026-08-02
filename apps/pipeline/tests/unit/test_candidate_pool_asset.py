"""Unit tests for the PR-3 slice 2 ``personal_candidate_pool`` Dagster asset.

The slice wires the slice-1 application service into a Dagster asset
without duplicating any calculation or persistence logic. The tests
exercise three contracts:

* **Partition / dependency metadata** — the asset is partitioned on the
  same ``DailyPartitionsDefinition`` as ``etf_input_snapshot`` and
  depends on ``etf_input_snapshot`` + ``etf_daily_bars``.
* **Happy path** — the asset builds the engine / session / UoW with the
  existing factory pipeline, looks up the persisted
  :class:`InputSnapshot` for the partition date, loads the
  ``config/candidate-pool-personal.yaml`` policy, delegates to
  :func:`invest_pipeline.candidate_pool_service.calculate_and_publish_candidate_pool`,
  surfaces the run / trade_date / status / input_count / included_count
  / item_count as Dagster metadata, and disposes the engine.
* **Missing snapshot** — when
  :meth:`InputSnapshotRepository.list_by_date` returns an empty list for
  the partition date the asset raises the slice-specific
  :class:`CandidatePoolSnapshotNotFoundError` with a message the operator
  can act on (re-run the upstream ``etf_input_snapshot`` asset).

No PostgreSQL container is booted: the engine / session factory /
service are monkey-patched and the UoW is replaced with a hand-rolled
fake that exposes the production-side repositories wired against a mock
session, mirroring the approach used by
``tests/unit/test_input_snapshot_asset.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import dagster as dg
import invest_storage
import pytest
from invest_domain.candidate_pool.models import CandidatePoolStatus
from invest_domain.input_snapshot import InputSnapshot
from invest_pipeline import assets
from invest_pipeline.candidate_pool_service import (
    CandidatePoolPublishResult,
    CandidatePoolSnapshotNotFoundError,
)

_TRADE_DATE = date(2026, 7, 31)


class _FakeInputSnapshotRepository:
    """Pre-seeded stand-in for :class:`InputSnapshotRepository.list_by_date`."""

    def __init__(self, snapshots: list[InputSnapshot]) -> None:
        self._snapshots = list(snapshots)

    def list_by_date(self, snapshot_date: date) -> list[InputSnapshot]:
        assert snapshot_date == _TRADE_DATE
        return list(self._snapshots)


class _FakeUoW:
    """Stand-in for :class:`SqlAlchemyUnitOfWork` used inside the lookup.

    The lookup only needs :attr:`input_snapshot_repository`; the
    rest of the surface stays open so accidental usage surfaces
    clearly in test output rather than as a silent ``AttributeError``.
    """

    def __init__(self, snapshot_repository: _FakeInputSnapshotRepository) -> None:
        self._snapshot_repository = snapshot_repository

    @property
    def input_snapshot_repository(self) -> _FakeInputSnapshotRepository:
        return self._snapshot_repository

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _build_snapshot(
    *,
    snapshot_id: UUID | None = None,
    snapshot_date: date = _TRADE_DATE,
) -> InputSnapshot:
    instrument_id = UUID("00000000-0000-0000-0000-000000000001")
    return InputSnapshot(
        id=snapshot_id or uuid4(),
        snapshot_date=snapshot_date,
        instrument_ids=(instrument_id,),
        content_hash="a" * 64,
        row_count=1,
        created_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
    )


def _make_service_result(snapshot_id: UUID) -> CandidatePoolPublishResult:
    run_id = uuid4()
    item = SimpleNamespace(
        instrument_id=SimpleNamespace(value=UUID("00000000-0000-0000-0000-000000000099")),
        included=True,
        rank=1,
    )
    # The asset only reads these surface attributes off the publish
    # result; using plain SimpleNamespace keeps the fixture scoped to
    # the slice-2 wiring contract and avoids re-asserting the
    # CandidatePoolRun / CandidatePoolResult domain invariants (those
    # are owned by slice 1).
    result = SimpleNamespace(
        run=SimpleNamespace(
            id=run_id,
            trade_date=_TRADE_DATE,
            status=CandidatePoolStatus.PUBLISHED,
            input_snapshot_id=snapshot_id,
            input_row_count=3,
            included_count=2,
        ),
        result=SimpleNamespace(items=(item, item)),
    )
    return CandidatePoolPublishResult(
        run=result.run,  # type: ignore[arg-type]
        result=result.result,  # type: ignore[arg-type]
    )


def _patch_engine(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace ``build_engine`` / ``session_factory`` and return a mock engine."""

    engine = MagicMock(name="Engine")
    monkeypatch.setattr(assets, "build_engine", lambda _url: engine)
    monkeypatch.setattr(assets, "session_factory", lambda _engine: MagicMock())
    return engine


def test_personal_candidate_pool_uses_same_partition_definition_as_etf_input_snapshot() -> None:
    assert isinstance(
        assets.personal_candidate_pool.partitions_def, dg.DailyPartitionsDefinition
    )
    # Reusing the same _ETF_INPUT_SNAPSHOT_PARTITIONS instance ensures
    # the start date / timezone / cron / partition-fn stay byte-equal;
    # plain attribute comparison isn't supported on the
    # TimestampWithTimezone-backed DailyPartitionsDefinition.
    assert (
        assets.personal_candidate_pool.partitions_def
        == assets.etf_input_snapshot.partitions_def
    )


def test_personal_candidate_pool_depends_on_etf_input_snapshot_and_etf_daily_bars() -> None:
    dependency_keys = assets.personal_candidate_pool.dependency_keys
    assert dg.AssetKey("etf_input_snapshot") in dependency_keys
    assert dg.AssetKey("etf_daily_bars") in dependency_keys


def test_personal_candidate_pool_happy_path_resolves_snapshot_invokes_service_and_surfaces_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid4()
    snapshot = _build_snapshot(snapshot_id=snapshot_id)
    fake_repo = _FakeInputSnapshotRepository(snapshots=[snapshot])
    fake_uow = _FakeUoW(snapshot_repository=fake_repo)
    engine = _patch_engine(monkeypatch)
    monkeypatch.setattr(
        invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: fake_uow
    )

    captured: dict[str, Any] = {}

    def _fake_calculate(
        *, uow_factory, trade_date, snapshot_id, policy
    ) -> CandidatePoolPublishResult:
        captured["uow_factory"] = uow_factory
        captured["trade_date"] = trade_date
        captured["snapshot_id"] = snapshot_id
        captured["policy"] = policy
        captured_service_result = _make_service_result(snapshot_id=snapshot_id)
        captured["service_result"] = captured_service_result
        return captured_service_result

    monkeypatch.setattr(
        assets, "calculate_and_publish_candidate_pool", _fake_calculate
    )

    context = dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
    result = assets.personal_candidate_pool.op.compute_fn.decorated_fn(context)

    assert captured["trade_date"] == _TRADE_DATE
    assert captured["snapshot_id"] == snapshot_id
    # The asset hands the service the same lambda factory it uses for
    # its own snapshot lookup; that factory must produce the fake UoW
    # so a single backing storage boundary is shared end-to-end.
    assert callable(captured["uow_factory"])
    assert captured["uow_factory"]() is fake_uow
    assert captured["policy"].algorithm_key == "minimum_v1"

    # The fake calculate returns a fresh publish result; compare
    # metadata against what the asset saw so re-running the test
    # doesn't churn on uuid4().
    expected_service_result = captured["service_result"]
    assert result.metadata["run_id"] == str(expected_service_result.run.id)
    assert result.metadata["trade_date"] == _TRADE_DATE.isoformat()
    assert result.metadata["status"] == CandidatePoolStatus.PUBLISHED.value
    assert result.metadata["input_count"] == expected_service_result.run.input_row_count
    assert (
        result.metadata["included_count"]
        == expected_service_result.run.included_count
    )
    assert result.metadata["item_count"] == len(expected_service_result.result.items)

    engine.dispose.assert_called_once_with()


def test_personal_candidate_pool_uses_partition_date_not_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back-fill runs must target the partition date, never ``date.today()``."""

    snapshot = _build_snapshot()
    fake_repo = _FakeInputSnapshotRepository(snapshots=[snapshot])
    fake_uow = _FakeUoW(snapshot_repository=fake_repo)
    engine = _patch_engine(monkeypatch)
    monkeypatch.setattr(
        invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: fake_uow
    )

    captured: dict[str, Any] = {}

    def _fake_calculate(
        *, uow_factory, trade_date, snapshot_id, policy
    ) -> CandidatePoolPublishResult:
        captured["trade_date"] = trade_date
        return _make_service_result(snapshot_id=snapshot.id)

    monkeypatch.setattr(
        assets, "calculate_and_publish_candidate_pool", _fake_calculate
    )

    context = dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
    assets.personal_candidate_pool.op.compute_fn.decorated_fn(context)

    assert captured["trade_date"] == date.fromisoformat(context.partition_key)
    # ``date.today()`` must never be used as the business input.
    assert captured["trade_date"] != date.today()
    engine.dispose.assert_called_once_with()


def test_personal_candidate_pool_raises_when_no_snapshot_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _FakeInputSnapshotRepository(snapshots=[])
    fake_uow = _FakeUoW(snapshot_repository=fake_repo)
    engine = _patch_engine(monkeypatch)
    monkeypatch.setattr(
        invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: fake_uow
    )

    service_invoked = MagicMock(name="calculate_and_publish_candidate_pool")
    monkeypatch.setattr(
        assets, "calculate_and_publish_candidate_pool", service_invoked
    )

    context = dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
    with pytest.raises(CandidatePoolSnapshotNotFoundError) as exc_info:
        assets.personal_candidate_pool.op.compute_fn.decorated_fn(context)

    message = str(exc_info.value)
    assert _TRADE_DATE.isoformat() in message
    assert "etf_input_snapshot" in message
    # The service must not be called when the upstream snapshot is absent
    # so a re-materialisation of etf_input_snapshot can supply a row
    # before the service is invoked.
    service_invoked.assert_not_called()
    engine.dispose.assert_called_once_with()


def test_personal_candidate_pool_metadata_keys_are_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot_id = uuid4()
    snapshot = _build_snapshot(snapshot_id=snapshot_id)
    fake_repo = _FakeInputSnapshotRepository(snapshots=[snapshot])
    fake_uow = _FakeUoW(snapshot_repository=fake_repo)
    _patch_engine(monkeypatch)
    monkeypatch.setattr(
        invest_storage, "SqlAlchemyUnitOfWork", lambda _factory: fake_uow
    )

    monkeypatch.setattr(
        assets,
        "calculate_and_publish_candidate_pool",
        lambda **_: _make_service_result(snapshot_id=snapshot_id),
    )

    context = dg.build_asset_context(partition_key=_TRADE_DATE.isoformat())
    result = assets.personal_candidate_pool.op.compute_fn.decorated_fn(context)

    expected_keys = {
        "run_id",
        "trade_date",
        "status",
        "input_count",
        "included_count",
        "item_count",
    }
    assert expected_keys.issubset(result.metadata.keys())
