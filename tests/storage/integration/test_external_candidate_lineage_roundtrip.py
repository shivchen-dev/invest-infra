"""Integration tests for the WorkBuddy candidate Bridge lineage round-trip.

The bridge serializes the two-stage ``candidate-lineage/1.0`` lineage
into ``external_workflow_runs.metadata->lineage`` and writes the four
query-friendly terminal/upstream refs onto every observation's
metadata. This file proves that JSONB persistence preserves both
shapes end-to-end and that a re-import through a fresh ``UnitOfWork``
is idempotent and does not duplicate rows or rewrite metadata.
"""

from __future__ import annotations

from invest_pipeline.integrations.bridge_ingestor import import_archived_candidate_run
from invest_pipeline.workbuddy_candidates.archive import archive_candidates
from sqlalchemy import text

_TRADE_DATE = "2026-08-14"
_LINEAGE_SCHEMA = "candidate-lineage/1.0"
_OBS_LINEAGE_KEYS = (
    "terminal_stage_result_id",
    "terminal_stage_result_sha256",
    "upstream_stage_result_id",
    "upstream_stage_result_sha256",
)


def _sector_stage() -> dict:
    return {
        "stage_key": "sector_selection",
        "stage_result_id": "sector-result-001",
        "stage_result_sha256": "a" * 64,
        "strategy_key": "sector-strength-v1",
        "strategy_version": "1.0.0",
        "strategy_artifact_hash": "b" * 64,
        "as_of": _TRADE_DATE,
        "constituent_snapshot_sha256": "c" * 64,
    }


def _stock_stage() -> dict:
    return {
        "stage_key": "stock_screening",
        "stage_result_id": "stock-result-001",
        "stage_result_sha256": "d" * 64,
        "strategy_key": "stock-screen-v1",
        "strategy_version": "1.0.0",
        "strategy_artifact_hash": "e" * 64,
        "as_of": _TRADE_DATE,
        "upstream_stage_result_id": "sector-result-001",
        "upstream_stage_result_sha256": "a" * 64,
    }


def _lineage_payload() -> dict:
    return {
        "workflow_run_id": "wb-lineage-001",
        "trade_date": _TRADE_DATE,
        "strategy_id": "etf-screen-v1",
        "status": "succeeded",
        "candidates": [
            {
                "symbol": "510300",
                "reason": "板块强度共振",
                "terminal_stage_result_id": "stock-result-001",
                "terminal_stage_result_sha256": "d" * 64,
            }
        ],
        "lineage": {
            "schema_version": _LINEAGE_SCHEMA,
            "stages": [_sector_stage(), _stock_stage()],
        },
    }


def _legacy_payload() -> dict:
    return {
        "workflow_run_id": "wb-legacy-001",
        "trade_date": _TRADE_DATE,
        "strategy_id": "etf-screen-v1",
        "status": "succeeded",
        "candidates": [{"symbol": "510300", "reason": "liquid"}],
    }


def _count_rows(session_factory, *sql: str) -> list[int]:
    with session_factory() as session:
        return [session.execute(text(s)).scalar_one() for s in sql]


def test_valid_lineage_round_trips_through_postgres(
    tmp_path, uow_factory, session_factory_fixture
) -> None:
    """A v2 archive with lineage persists an ordered run lineage, four
    observation refs per row, no full lineage on observations, and a
    fresh-UoW re-import is idempotent without duplicating rows or
    rewriting metadata."""

    payload = _lineage_payload()
    archive_candidates(payload, str(tmp_path))

    with uow_factory() as uow:
        first = import_archived_candidate_run(
            tmp_path,
            trade_date=_TRADE_DATE,
            workflow_run_id="wb-lineage-001",
            uow=uow,
        )
        uow.commit()
        run_id = first.run.run_id

    with uow_factory() as verify_uow:
        run = verify_uow.external_workflow_runs.get_by_id(run_id)
        observations = verify_uow.external_observations.list_by_run(run_id, limit=10_000)

    assert run is not None
    lineage = run.metadata["lineage"]
    assert lineage["schema_version"] == _LINEAGE_SCHEMA
    assert [stage["stage_key"] for stage in lineage["stages"]] == [
        "sector_selection",
        "stock_screening",
    ]
    assert lineage["stages"][0]["stage_result_id"] == "sector-result-001"
    assert lineage["stages"][1]["upstream_stage_result_id"] == "sector-result-001"

    assert len(observations) == 1
    obs_metadata = observations[0].metadata
    for key in _OBS_LINEAGE_KEYS:
        assert key in obs_metadata
    assert "stages" not in obs_metadata
    assert "schema_version" not in obs_metadata

    counts_before = _count_rows(
        session_factory_fixture,
        "SELECT COUNT(*) FROM integration.external_workflow_runs",
        "SELECT COUNT(*) FROM integration.external_artifacts",
        "SELECT COUNT(*) FROM integration.external_observations",
    )
    assert counts_before == [1, 1, 1]

    metadata_snapshot = dict(observations[0].metadata)
    run_metadata_snapshot = dict(run.metadata)

    with uow_factory() as reimport_uow:
        second = import_archived_candidate_run(
            tmp_path,
            trade_date=_TRADE_DATE,
            workflow_run_id="wb-lineage-001",
            uow=reimport_uow,
        )
        reimport_uow.commit()

    assert second.idempotent is True

    counts_after = _count_rows(
        session_factory_fixture,
        "SELECT COUNT(*) FROM integration.external_workflow_runs",
        "SELECT COUNT(*) FROM integration.external_artifacts",
        "SELECT COUNT(*) FROM integration.external_observations",
    )
    assert counts_after == [1, 1, 1]

    with uow_factory() as verify_uow:
        run_again = verify_uow.external_workflow_runs.get_by_id(run_id)
        observations_again = verify_uow.external_observations.list_by_run(run_id, limit=10_000)

    assert run_again.metadata == run_metadata_snapshot
    assert dict(observations_again[0].metadata) == metadata_snapshot


def test_legacy_payload_round_trips_without_lineage_keys(tmp_path, uow_factory) -> None:
    """A legacy payload without a ``lineage`` block is ingested cleanly
    and neither the run metadata nor any observation metadata carries
    the lineage keys."""

    payload = _legacy_payload()
    archive_candidates(payload, str(tmp_path))

    with uow_factory() as uow:
        result = import_archived_candidate_run(
            tmp_path,
            trade_date=_TRADE_DATE,
            workflow_run_id="wb-legacy-001",
            uow=uow,
        )
        uow.commit()
        run_id = result.run.run_id

    with uow_factory() as verify_uow:
        run = verify_uow.external_workflow_runs.get_by_id(run_id)
        observations = verify_uow.external_observations.list_by_run(run_id, limit=10_000)

    assert run is not None
    assert "lineage" not in run.metadata

    assert len(observations) == 1
    for key in _OBS_LINEAGE_KEYS:
        assert key not in observations[0].metadata
