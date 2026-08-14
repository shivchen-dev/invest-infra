from __future__ import annotations

import pytest
from invest_pipeline.workbuddy_candidates import (
    extract_legacy_candidates,
    parse_candidates_payload,
)


def _payload(**overrides):
    payload = {
        "workflow_run_id": "wb-001",
        "trade_date": "2026-08-14",
        "strategy_id": "sector-seven-step-v2",
        "status": "succeeded",
        "candidates": [{"symbol": "600000", "reason": "政策催化"}],
    }
    payload.update(overrides)
    return payload


def test_minimal_valid_payload():
    result = parse_candidates_payload(_payload())
    assert result.status == "succeeded"
    assert len(result.accepted) == 1
    assert result.accepted[0].status == "needs_symbol_resolution"
    assert result.accepted[0].raw["symbol"] == "600000"
    assert result.rejected == []


def test_bad_items_are_isolated():
    result = parse_candidates_payload(
        _payload(
            candidates=[
                {"symbol": "600000", "reason": "ok"},
                {"symbol": "", "reason": "bad"},
                "bad",
            ]
        )
    )
    assert [item.symbol for item in result.accepted] == ["600000"]
    assert len(result.rejected) == 2
    assert {finding["index"] for finding in result.findings} == {1, 2}


def test_unknown_fields_are_preserved():
    raw = {"symbol": "000001", "reason": "观察", "score": 0.9, "extra": {"x": 1}}
    item = parse_candidates_payload(_payload(candidates=[raw])).accepted[0]
    assert item.raw is raw
    assert item.raw["extra"] == {"x": 1}


def test_batch_errors_fail_without_items():
    with pytest.raises(ValueError):
        parse_candidates_payload(_payload(candidates="not-a-list"))


def test_invalid_date_and_run_id_fail_batch():
    for payload in (_payload(trade_date="2026-02-30"), _payload(workflow_run_id="wb/../escape")):
        with pytest.raises(ValueError):
            parse_candidates_payload(payload)


def test_legacy_extraction_ignores_missing_report_fields():
    result = extract_legacy_candidates({
        "workflow_run_id": "legacy-1",
        "trade_date": "2026-08-14",
        "strategy_id": "legacy-strategy",
        "status": "succeeded",
        "candidates": [{"symbol": "600519", "reason": "基本面"}],
    })
    assert len(result.accepted) == 1
    assert result.status == "legacy_extracted"


def test_legacy_strategy_version_fallback():
    result = extract_legacy_candidates({
        "workflow_run_id": "legacy-1",
        "trade_date": "2026-08-14",
        "strategy_version": "legacy-v1",
        "scores": [],
        "candidates": [],
    })
    assert result.strategy_id == "legacy-v1"


def test_legacy_missing_candidates_is_batch_failure():
    with pytest.raises(ValueError):
        extract_legacy_candidates({"workflow_run_id": "legacy-1", "scores": []})
