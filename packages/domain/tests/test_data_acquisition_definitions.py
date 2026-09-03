"""Contract tests for deployment-bound data acquisition definitions."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from invest_domain.strategy import APPROVED_DATA_CONNECTORS, DataRequest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFINITION_ROOT = REPOSITORY_ROOT / "config" / "data-acquisition-definitions"
EXPECTED_DEFINITIONS = {
    "sector-strength-ranking": {
        "strategy_artifact_hash": (
            "e05e2e191311fb3273a2f14748b7265c1cec47a37339f7a70a139a85a7bf68b2"
        ),
        "stage": "sector_selection",
        "dynamic_fields": ["request_id", "as_of"],
        "request_identity_fields": [
            "request_id",
            "definition_key",
            "definition_version",
            "strategy_key",
            "strategy_version",
            "strategy_artifact_hash",
            "stage",
            "as_of",
        ],
        "datasets": {
            "sector-ranking": {
                "group",
                "bd_code",
                "bd_name",
                "cje",
                "bd_zdf",
                "zgb",
            },
            "sector-constituents": {"group", "bd_code", "symbol", "name"},
        },
    },
    "tdx-native-tools-stock-screening": {
        "strategy_artifact_hash": (
            "84cecfaa486815ceb6b1833a678c280503f2465484509e762a53f7218cdca944"
        ),
        "stage": "stock_screening",
        "dynamic_fields": ["request_id", "as_of", "upstream_stage_result"],
        "request_identity_fields": [
            "request_id",
            "definition_key",
            "definition_version",
            "strategy_key",
            "strategy_version",
            "strategy_artifact_hash",
            "stage",
            "as_of",
            "upstream_stage_result",
        ],
        "datasets": {
            "stock-identity": {
                "symbol",
                "name",
                "is_st",
                "is_delisting",
                "is_suspended",
                "listing_date",
            },
            "stock-daily-bars": {
                "symbol",
                "trade_date",
                "close",
                "volume",
                "turnover",
                "return",
            },
            "stock-fund-flow": {"symbol", "zljlr_d5", "zljlr_d20"},
        },
    },
}
EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "definition_key",
    "definition_version",
    "strategy_ref",
    "stage",
    "allowed_connectors",
    "dynamic_fields",
    "data_request_template",
    "output_contract",
    "timeout_seconds",
    "idempotency",
    "failure_handling",
}


def _load_definition(definition_key: str) -> dict:
    path = DEFINITION_ROOT / definition_key / "1.0.0.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _materialize_request(definition: dict) -> dict:
    payload = deepcopy(definition["data_request_template"])
    payload.update(
        request_id=f"req_20260903_{definition['definition_key']}",
        as_of="2026-09-02",
    )
    if "upstream_stage_result" in definition["dynamic_fields"]:
        payload["upstream_stage_result"] = {
            "stage_result_id": "stage-sector-20260902-01",
            "stage_result_sha256": "b" * 64,
            "constituent_snapshot_sha256": "c" * 64,
            "group": "industry",
            "as_of": payload["as_of"],
        }
    return payload


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_envelope_is_version_bound_and_minimal(definition_key: str) -> None:
    expected = EXPECTED_DEFINITIONS[definition_key]
    definition = _load_definition(definition_key)

    assert set(definition) == EXPECTED_TOP_LEVEL_FIELDS
    assert definition["schema_version"] == "data-acquisition-definition/1.0"
    assert definition["definition_key"] == definition_key
    assert definition["definition_version"] == "1.0.0"
    assert definition["strategy_ref"] == {
        "strategy_key": definition_key,
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": expected["strategy_artifact_hash"],
    }
    assert definition["stage"] == expected["stage"]
    assert definition["dynamic_fields"] == expected["dynamic_fields"]
    assert all(
        field not in definition["data_request_template"]
        for field in definition["dynamic_fields"]
    )
    assert definition["output_contract"] == "workbuddy-data-bundle/1.0"


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_template_materializes_as_a_valid_data_request(
    definition_key: str,
) -> None:
    definition = _load_definition(definition_key)

    request = DataRequest.from_mapping(_materialize_request(definition))

    assert request.definition_key == definition_key
    assert request.definition_version == "1.0.0"
    assert request.strategy_key == definition_key
    assert request.strategy_version == "2.0.0"
    assert request.stage == EXPECTED_DEFINITIONS[definition_key]["stage"]
    assert request.output_contract == definition["output_contract"]


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_requests_only_the_required_acquisition_facts(
    definition_key: str,
) -> None:
    definition = _load_definition(definition_key)
    request = DataRequest.from_mapping(_materialize_request(definition))

    actual = {
        dataset.dataset_key: set(dataset.required_fields)
        for dataset in request.datasets
    }
    assert actual == EXPECTED_DEFINITIONS[definition_key]["datasets"]


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_connector_order_is_approved_and_consistent(
    definition_key: str,
) -> None:
    definition = _load_definition(definition_key)
    request = DataRequest.from_mapping(_materialize_request(definition))
    declared = tuple(definition["allowed_connectors"])

    assert declared
    assert len(declared) == len(set(declared))
    assert set(declared).issubset(APPROVED_DATA_CONNECTORS)
    assert {
        connector
        for dataset in request.datasets
        for connector in dataset.allowed_connectors
    } == set(declared)


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_keeps_strategy_semantics_and_credentials_out(
    definition_key: str,
) -> None:
    definition = _load_definition(definition_key)
    serialized = json.dumps(definition, ensure_ascii=False).lower()

    forbidden_terms = (
        "prompt",
        "formula",
        "threshold",
        "score",
        "eligibility",
        "recommendation",
        "api_key",
        "authorization",
        "client_secret",
        "password",
        "token",
    )
    assert all(term not in serialized for term in forbidden_terms)


@pytest.mark.parametrize("definition_key", EXPECTED_DEFINITIONS)
def test_definition_freezes_bounded_execution_and_failure_policy(
    definition_key: str,
) -> None:
    expected = EXPECTED_DEFINITIONS[definition_key]
    definition = _load_definition(definition_key)

    assert definition["timeout_seconds"] == 900
    assert definition["idempotency"] == {
        "request_identity_fields": expected["request_identity_fields"],
        "same_request_same_content": "idempotent",
        "same_request_different_content": "conflict",
    }
    assert definition["failure_handling"] == {
        "retry": "manual_new_request",
        "dataset_failure": "fail_closed",
        "incomplete_pagination": "fail_closed",
        "warnings": "continue_and_record",
    }


def test_stock_definition_binds_the_complete_upstream_stage_result_identity() -> None:
    definition = _load_definition("tdx-native-tools-stock-screening")
    request = _materialize_request(definition)
    identity_fields = definition["idempotency"]["request_identity_fields"]

    assert "upstream_stage_result" in identity_fields
    assert request["upstream_stage_result"] == {
        "stage_result_id": "stage-sector-20260902-01",
        "stage_result_sha256": "b" * 64,
        "constituent_snapshot_sha256": "c" * 64,
        "group": "industry",
        "as_of": "2026-09-02",
    }
