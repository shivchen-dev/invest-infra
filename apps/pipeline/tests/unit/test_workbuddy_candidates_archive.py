from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from invest_pipeline.workbuddy_candidates.archive import archive_candidates


def _payload(**overrides):
    payload = {
        "workflow_run_id": "wb-archive-001",
        "trade_date": "2026-08-14",
        "strategy_id": "demo",
        "status": "succeeded",
        "candidates": [{"symbol": "600000", "reason": "观察"}],
    }
    payload.update(overrides)
    return payload


def test_archive_writes_manifest_and_is_idempotent(tmp_path: Path):
    first = archive_candidates(_payload(), tmp_path)
    second = archive_candidates(_payload(), tmp_path)
    run_dir = Path(first.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    raw = (run_dir / "candidates.json").read_bytes()
    entry = manifest["files"][0]

    assert first.idempotent is False
    assert second.idempotent is True
    assert entry["size_bytes"] == len(raw)
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()


def test_archive_conflict_does_not_overwrite(tmp_path: Path):
    archive_candidates(_payload(), tmp_path)
    outcome = archive_candidates(
        _payload(candidates=[{"symbol": "000001", "reason": "不同"}]), tmp_path
    )
    assert outcome.conflict is True
    assert json.loads(
        (Path(outcome.run_dir) / "candidates.json").read_text()
    )["candidates"][0]["symbol"] == "600000"


def test_bad_items_are_archived_with_findings(tmp_path: Path):
    outcome = archive_candidates(
        _payload(candidates=[{"symbol": "600000", "reason": "好"}, {"symbol": ""}]),
        tmp_path,
    )
    assert outcome.accepted_count == 1
    assert outcome.rejected_count == 1
    assert outcome.findings


def test_unsafe_identity_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        archive_candidates(_payload(workflow_run_id="../escape"), tmp_path)
