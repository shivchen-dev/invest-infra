from __future__ import annotations

from invest_pipeline.workbuddy_candidates import parse_candidates_payload
from invest_pipeline.workbuddy_candidates.projection import project_candidates


def _result(candidates):
    return parse_candidates_payload(
        {
            "workflow_run_id": "wb-projection-001",
            "trade_date": "2026-08-14",
            "strategy_id": "demo",
            "status": "succeeded",
            "candidates": candidates,
        }
    )


def test_resolves_and_marks_pending_validation():
    result = project_candidates(_result([{"symbol": "600000", "reason": "观察"}]), str.upper)
    assert [item.symbol for item in result.accepted] == ["600000"]
    assert result.accepted[0].status == "pending_validation"


def test_unresolved_symbol_isolated():
    result = project_candidates(_result([{"symbol": "UNKNOWN", "reason": "观察"}]), lambda _: None)
    assert len(result.needs_symbol_resolution) == 1
    assert result.accepted == []


def test_same_batch_and_seen_keys_are_deduplicated():
    payload = _result(
        [
            {"symbol": "600000", "reason": "一"},
            {"symbol": "600000", "reason": "二"},
        ]
    )
    first = project_candidates(payload, lambda value: value)
    assert len(first.accepted) == 1
    assert len(first.duplicates) == 1
    key = (payload.trade_date, payload.strategy_id, "600000")
    second = project_candidates(
        _result([{"symbol": "600000", "reason": "三"}]), lambda value: value, [key]
    )
    assert second.accepted == []
    assert len(second.duplicates) == 1


def test_resolver_error_is_isolated():
    def fail(_: str) -> str:
        raise RuntimeError("master data unavailable")

    result = project_candidates(_result([{"symbol": "600000", "reason": "观察"}]), fail)
    assert len(result.needs_symbol_resolution) == 1
    assert any("resolver failed" in finding["error"] for finding in result.findings)


def test_rejected_intake_items_remain_findings():
    result = project_candidates(
        _result([{"symbol": "", "reason": "坏"}, {"symbol": "600000", "reason": "好"}]),
        lambda value: value,
    )
    assert len(result.accepted) == 1
    assert any(finding["error"] == "rejected_by_intake" for finding in result.findings)
