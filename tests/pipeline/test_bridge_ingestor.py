"""Focused tests for the safe WorkBuddy archive bridge."""

from invest_pipeline.integrations.bridge_ingestor import import_archived_candidate_run
from invest_pipeline.workbuddy_candidates.archive import archive_candidates


class _Repo:
    def __init__(self):
        self.items = {}

    def add(self, item):
        key = next(
            getattr(item, name)
            for name in ("observation_id", "artifact_id", "run_id")
            if hasattr(item, name)
        )
        self.items[key] = item
        return item

    def get_by_id(self, key):
        return self.items.get(key)

    def list_by_run(self, run_id, *, limit=100, offset=0):
        items = [item for item in self.items.values() if item.run_id == run_id]
        return items[offset : offset + limit]


class _Uow:
    def __init__(self):
        self.external_workflow_runs = _Repo()
        self.external_artifacts = _Repo()
        self.external_observations = _Repo()


def _payload():
    return {
        "workflow_run_id": "wb-run-001",
        "trade_date": "2026-08-14",
        "strategy_id": "etf-screen-v1",
        "status": "succeeded",
        "candidates": [
            {"symbol": " 510300 ", "reason": "liquid"},
            {"symbol": "", "reason": "bad item"},
            {"symbol": "159915", "reason": "growth"},
        ],
    }


def test_bridge_imports_valid_candidates_and_is_idempotent(tmp_path):
    archive_candidates(_payload(), str(tmp_path))
    uow = _Uow()

    first = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-14",
        workflow_run_id="wb-run-001",
        uow=uow,
        resolver=lambda symbol: "510300" if symbol.strip() == "510300" else None,
    )
    second = import_archived_candidate_run(
        tmp_path,
        trade_date="2026-08-14",
        workflow_run_id="wb-run-001",
        uow=uow,
    )

    assert first.run.intake_status.value == "partial"
    assert first.run.producer_status.value == "partial"
    assert len(first.observations) == 2
    assert {item.metadata["candidate_status"] for item in first.observations} == {
        "pending_validation",
        "needs_symbol_resolution",
    }
    assert second.idempotent
    assert second.observations == first.observations
    assert len(uow.external_observations.items) == 2


def test_bridge_rejects_manifest_tampering(tmp_path):
    archive_candidates(_payload(), str(tmp_path))
    candidates = tmp_path / "runs" / "2026-08-14" / "wb-run-001" / "candidates.json"
    candidates.write_text(candidates.read_text() + "\n", encoding="utf-8")

    try:
        import_archived_candidate_run(
            tmp_path,
            trade_date="2026-08-14",
            workflow_run_id="wb-run-001",
            uow=_Uow(),
        )
    except ValueError as exc:
        assert "hash or size" in str(exc)
    else:
        raise AssertionError("tampered archive must be rejected")
