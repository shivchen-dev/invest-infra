from __future__ import annotations

import copy
import json

import pytest
from invest_domain.strategy import DataBundle, DataRequest
from invest_pipeline.integrations.sector_evaluator import (
    SectorEvaluationError,
    evaluate_sector_bundle,
)

HASH = "e05e2e191311fb3273a2f14748b7265c1cec47a37339f7a70a139a85a7bf68b2"
ARTIFACT = {
    "strategy_id": "sector-strength-ranking",
    "version_candidate": "2.0.0",
    "rules": [{"id": rule} for rule in ("R-A1", "R-A3", "R-A4", "R-A5")],
}


def _request() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "req_sector_20260902",
        "definition_key": "sector-strength-ranking",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength-ranking",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": HASH,
        "stage": "sector_selection",
        "as_of": "2026-09-02",
        "max_delivery_lag_days": 2,
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "required_fields": ["group", "bd_code", "bd_name", "cje", "bd_zdf", "zgb"],
                "allowed_connectors": ["tdx-connector"],
            },
            {
                "dataset_key": "sector-constituents",
                "required_fields": ["group", "bd_code", "symbol", "name"],
                "allowed_connectors": ["tdx-connector"],
            },
        ],
        "output_contract": "workbuddy-data-bundle/1.0",
    }


def _dataset(key: str, fields: list[str], records: list[dict]) -> dict:
    return {
        "dataset_key": key,
        "attempts": [
            {
                "connector": "tdx-connector",
                "tool": "get_data",
                "parameters": {},
                "status": "succeeded",
                "error_code": None,
            }
        ],
        "as_of": "2026-09-02",
        "pagination": {"complete": True},
        "sample_count": len(records),
        "fields": fields,
        "units": {},
        "records": records,
    }


def _bundle() -> dict:
    rankings = [
        {
            "group": "industry",
            "bd_code": "B",
            "bd_name": "Beta",
            "cje": 100,
            "bd_zdf": 2,
            "zgb": "1/10",
        },
        {
            "group": "industry",
            "bd_code": "A",
            "bd_name": "Alpha",
            "cje": 100,
            "bd_zdf": 2,
            "zgb": "1/10",
        },
        {
            "group": "concept",
            "bd_code": "C",
            "bd_name": "Concept",
            "cje": 50,
            "bd_zdf": -1,
            "zgb": "2/10",
        },
        {"group": "area", "bd_code": "D", "bd_name": "Area", "cje": 20, "bd_zdf": 0, "zgb": "0/5"},
    ]
    constituents = [
        {
            "group": row["group"],
            "bd_code": row["bd_code"],
            "symbol": f"S{row['bd_code']}",
            "name": row["bd_name"],
        }
        for row in rankings
    ]
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": "req_sector_20260902",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T00:00:00+00:00",
        "datasets": [
            _dataset(
                "sector-ranking", ["group", "bd_code", "bd_name", "cje", "bd_zdf", "zgb"], rankings
            ),
            _dataset("sector-constituents", ["group", "bd_code", "symbol", "name"], constituents),
        ],
        "warnings": [],
        "errors": [],
    }


def test_deterministic_ranking_hashes_groups_and_constant_tie_break() -> None:
    first = evaluate_sector_bundle(_request(), _bundle(), strategy_artifact=ARTIFACT)
    second = evaluate_sector_bundle(_request(), _bundle(), strategy_artifact=ARTIFACT)

    assert first == second
    assert first["groups"] == ["area", "concept", "industry"]
    industry = [row for row in first["rankings"] if row["group"] == "industry"]
    assert [(row["bd_code"], row["rank"], row["score"]) for row in industry] == [
        ("A", 1, 0.5),
        ("B", 2, 0.5),
    ]
    assert len(first["stage_result_sha256"]) == 64
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_mapping_and_domain_inputs_have_stable_stage_identity() -> None:
    mapping_result = evaluate_sector_bundle(_request(), _bundle(), strategy_artifact=ARTIFACT)
    domain_result = evaluate_sector_bundle(
        DataRequest.from_mapping(_request()),
        DataBundle.from_mapping(_bundle()),
        strategy_artifact=ARTIFACT,
    )
    assert mapping_result == domain_result


@pytest.mark.parametrize("zgb", ["bad", "-1/2", "2/1", "1/0"])
def test_malformed_zgb_fails_closed(zgb: str) -> None:
    bundle = _bundle()
    bundle["datasets"][0]["records"][0]["zgb"] = zgb
    with pytest.raises(SectorEvaluationError, match="malformed zgb"):
        evaluate_sector_bundle(_request(), bundle, strategy_artifact=ARTIFACT)


@pytest.mark.parametrize("field,value", [("cje", 0), ("bd_zdf", float("nan")), ("bd_name", "")])
def test_malformed_candidate_fails_closed(field: str, value: object) -> None:
    bundle = _bundle()
    bundle["datasets"][0]["records"][0][field] = value
    with pytest.raises(SectorEvaluationError):
        evaluate_sector_bundle(_request(), bundle, strategy_artifact=ARTIFACT)


def test_domain_bundle_validation_failure_is_sanitized() -> None:
    bundle = _bundle()
    bundle["datasets"][0]["pagination"]["complete"] = False
    with pytest.raises(SectorEvaluationError, match="failed evaluation validation"):
        evaluate_sector_bundle(_request(), bundle, strategy_artifact=ARTIFACT)


@pytest.mark.parametrize("mutation", ["missing", "mixed", "extra"])
def test_missing_mixed_or_extra_constituents_fail_closed(mutation: str) -> None:
    bundle = _bundle()
    records = bundle["datasets"][1]["records"]
    if mutation == "missing":
        records.pop()
    elif mutation == "mixed":
        records[0]["as_of"] = "2026-09-01"
    else:
        records.append({"group": "industry", "bd_code": "EXTRA", "symbol": "SX", "name": "Extra"})
    bundle["datasets"][1]["sample_count"] = len(records)
    with pytest.raises(SectorEvaluationError):
        evaluate_sector_bundle(_request(), bundle, strategy_artifact=ARTIFACT)


def test_top_twenty_is_applied_before_scoring() -> None:
    bundle = _bundle()
    ranking_records = bundle["datasets"][0]["records"]
    constituent_records = bundle["datasets"][1]["records"]
    ranking_records[:] = [row for row in ranking_records if row["group"] != "industry"]
    constituent_records[:] = [row for row in constituent_records if row["group"] != "industry"]
    for number in range(21):
        code = f"I{number:02d}"
        ranking_records.append(
            {
                "group": "industry",
                "bd_code": code,
                "bd_name": code,
                "cje": 21 - number,
                "bd_zdf": number,
                "zgb": "0/1",
            }
        )
        if number < 20:
            constituent_records.append(
                {"group": "industry", "bd_code": code, "symbol": f"S{number:02d}", "name": code}
            )
    for dataset in bundle["datasets"]:
        dataset["sample_count"] = len(dataset["records"])
    result = evaluate_sector_bundle(_request(), bundle, strategy_artifact=ARTIFACT)
    industry = [row for row in result["rankings"] if row["group"] == "industry"]
    assert len(industry) == 20
    assert {row["bd_code"] for row in industry} == {f"I{number:02d}" for number in range(20)}


def test_requires_reviewed_artifact_without_file_or_network_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pytest.fail("filesystem accessed"))
    with pytest.raises(SectorEvaluationError, match="artifact is required"):
        evaluate_sector_bundle(_request(), _bundle())
    result = evaluate_sector_bundle(
        _request(), _bundle(), strategy_artifact=copy.deepcopy(ARTIFACT)
    )
    assert result["status"] == "SUCCEEDED"
