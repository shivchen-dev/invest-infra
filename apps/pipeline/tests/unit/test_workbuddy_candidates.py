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


# ---------------------------------------------------------------------------
# Two-stage lineage contract (candidate-lineage/1.0).
# ---------------------------------------------------------------------------


_HEX = "0123456789abcdef" * 4  # 64 lowercase hex chars
_UNSAFE_ID = "wb/../escape"


def _sector_stage(**overrides):
    stage = {
        "stage_key": "sector_selection",
        "stage_result_id": "sector-result-1",
        "stage_result_sha256": "a" * 64,
        "strategy_key": "sector-strength-v1",
        "strategy_version": "1.0.0",
        "strategy_artifact_hash": "b" * 64,
        "as_of": "2026-08-14",
        "constituent_snapshot_sha256": "c" * 64,
    }
    stage.update(overrides)
    return stage


def _stock_stage(**overrides):
    stage = {
        "stage_key": "stock_screening",
        "stage_result_id": "stock-result-1",
        "stage_result_sha256": "d" * 64,
        "strategy_key": "stock-screen-v1",
        "strategy_version": "1.0.0",
        "strategy_artifact_hash": "e" * 64,
        "as_of": "2026-08-14",
        "upstream_stage_result_id": "sector-result-1",
        "upstream_stage_result_sha256": "a" * 64,
    }
    stage.update(overrides)
    return stage


def _lineage_dict(*stages):
    return {
        "schema_version": "candidate-lineage/1.0",
        "stages": list(stages),
    }


def _terminal_ref():
    stock = _stock_stage()
    return {
        "terminal_stage_result_id": stock["stage_result_id"],
        "terminal_stage_result_sha256": stock["stage_result_sha256"],
    }


def _missing_constituent_sector():
    stage = _sector_stage()
    stage.pop("constituent_snapshot_sha256")
    return stage


def _missing_hash_sector(hash_key):
    stage = _sector_stage()
    stage.pop(hash_key)
    return stage


def _non_string_hash_sector(hash_key):
    stage = _sector_stage()
    stage[hash_key] = 12345
    return stage


def _missing_hash_stock(hash_key):
    stage = _stock_stage()
    stage.pop(hash_key)
    return stage


def _non_string_hash_stock(hash_key):
    stage = _stock_stage()
    stage[hash_key] = 12345
    return stage


def test_valid_lineage_returns_normalized_two_stages():
    sector = _sector_stage()
    stock = _stock_stage()
    candidate = {"symbol": "600000", "reason": "板块强度共振", **_terminal_ref()}
    payload = _payload(candidates=[candidate], lineage=_lineage_dict(sector, stock))

    result = parse_candidates_payload(payload)

    assert result.lineage is not None
    assert result.lineage.schema_version == "candidate-lineage/1.0"
    assert len(result.lineage.stages) == 2
    sector_selection = result.lineage.sector_selection
    stock_screening = result.lineage.stock_screening
    assert sector_selection.stage_key == "sector_selection"
    assert sector_selection.constituent_snapshot_sha256 == sector["constituent_snapshot_sha256"]
    assert stock_screening.stage_key == "stock_screening"
    assert stock_screening.upstream_stage_result_id == sector["stage_result_id"]
    assert stock_screening.upstream_stage_result_sha256 == sector["stage_result_sha256"]
    assert [item.symbol for item in result.accepted] == ["600000"]
    assert result.rejected == []
    assert result.findings == []


def test_absent_or_null_lineage_preserves_legacy_read():
    for payload in (_payload(), _payload(lineage=None)):
        result = parse_candidates_payload(payload)
        assert result.lineage is None
        assert [item.symbol for item in result.accepted] == ["600000"]


@pytest.mark.parametrize(
    "lineage_value, expected_reason",
    [
        # invalid_lineage_shape
        ("not-a-dict", "invalid_lineage_shape"),
        (
            {"schema_version": "candidate-lineage/0.9",
             "stages": [_sector_stage(), _stock_stage()]},
            "invalid_lineage_shape",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(),
                        _stock_stage(),
                        _stock_stage(stage_result_id="extra",
                                     stage_result_sha256="9" * 64)]},
            "invalid_lineage_shape",
        ),
        # invalid_stage_order
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_stock_stage(), _sector_stage()]},
            "invalid_stage_order",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(stage_key="wrong"), _stock_stage()]},
            "invalid_stage_order",
        ),
        # upstream_binding_mismatch
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(),
                        _stock_stage(upstream_stage_result_id="different-id")]},
            "upstream_binding_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(),
                        _stock_stage(upstream_stage_result_sha256="f" * 64)]},
            "upstream_binding_mismatch",
        ),
        # as_of_mismatch
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(as_of="2026-08-14"),
                        _stock_stage(as_of="2026-08-15")]},
            "as_of_mismatch",
        ),
        # strategy_identity_mismatch (hash, identity, unsafe IDs)
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(stage_result_sha256="not-hex"), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(stage_result_sha256=_HEX.upper()),
                        _stock_stage(upstream_stage_result_sha256=_HEX.upper())]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_missing_constituent_sector(), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(stage_result_id=_UNSAFE_ID), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(),
                        _stock_stage(stage_result_id=_UNSAFE_ID)]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(),
                        _stock_stage(upstream_stage_result_id=_UNSAFE_ID)]},
            "upstream_binding_mismatch",
        ),
        # strategy_identity_mismatch — missing/non-string stage_result_sha256
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_missing_hash_sector("stage_result_sha256"), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_non_string_hash_sector("stage_result_sha256"), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _missing_hash_stock("stage_result_sha256")]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _non_string_hash_stock("stage_result_sha256")]},
            "strategy_identity_mismatch",
        ),
        # strategy_identity_mismatch — missing/non-string strategy_artifact_hash
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_missing_hash_sector("strategy_artifact_hash"), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_non_string_hash_sector("strategy_artifact_hash"), _stock_stage()]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _missing_hash_stock("strategy_artifact_hash")]},
            "strategy_identity_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _non_string_hash_stock("strategy_artifact_hash")]},
            "strategy_identity_mismatch",
        ),
        # upstream_binding_mismatch — missing/non-string upstream_stage_result_sha256
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _missing_hash_stock("upstream_stage_result_sha256")]},
            "upstream_binding_mismatch",
        ),
        (
            {"schema_version": "candidate-lineage/1.0",
             "stages": [_sector_stage(), _non_string_hash_stock("upstream_stage_result_sha256")]},
            "upstream_binding_mismatch",
        ),
    ],
)
def test_lineage_batch_failures(lineage_value, expected_reason):
    payload = _payload(lineage=lineage_value)
    with pytest.raises(ValueError) as exc_info:
        parse_candidates_payload(payload)
    assert str(exc_info.value) == expected_reason


def test_candidate_terminal_mismatch_isolates_one_bad_item():
    """One wrong-id and one missing-ref candidate are rejected without
    discarding the valid sibling."""
    payload = _payload(
        candidates=[
            {"symbol": "600000", "reason": "ok", **_terminal_ref()},
            {"symbol": "000001", "reason": "wrong-id", **_terminal_ref(),
             "terminal_stage_result_id": "WRONG-ID"},
            {"symbol": "000002", "reason": "missing-ref"},
        ],
        lineage=_lineage_dict(_sector_stage(), _stock_stage()),
    )

    result = parse_candidates_payload(payload)

    assert [item.symbol for item in result.accepted] == ["600000"]
    assert sorted(item.symbol for item in result.rejected) == ["000001", "000002"]
    terminal_findings = [
        f for f in result.findings if f.get("error") == "candidate_terminal_mismatch"
    ]
    assert {f["index"] for f in terminal_findings} == {1, 2}


def test_unknown_candidate_fields_remain_preserved_when_lineage_present():
    raw = {
        "symbol": "000001",
        "reason": "观察",
        "score": 0.9,
        "extra": {"x": 1},
        "third_party": [1, 2, 3],
        **_terminal_ref(),
    }
    payload = _payload(candidates=[raw], lineage=_lineage_dict(_sector_stage(), _stock_stage()))

    result = parse_candidates_payload(payload)

    item = result.accepted[0]
    assert item.raw is raw
    assert item.raw["extra"] == {"x": 1}
    assert item.raw["third_party"] == [1, 2, 3]
    assert item.raw["score"] == 0.9


def test_legacy_extraction_keeps_lineage_none():
    result = extract_legacy_candidates({
        "workflow_run_id": "legacy-1",
        "trade_date": "2026-08-14",
        "strategy_id": "legacy-strategy",
        "status": "succeeded",
        "candidates": [{"symbol": "600519", "reason": "基本面"}],
    })
    assert result.lineage is None
