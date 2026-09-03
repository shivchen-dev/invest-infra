"""Public-contract tests for WorkBuddy data acquisition payloads."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from invest_domain.strategy import (
    APPROVED_DATA_CONNECTORS,
    DataBundle,
    DataRequest,
    validate_data_bundle_for_evaluation,
)


def _request_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "req_20260903_sector_01",
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "as_of": "2026-09-02",
        "max_delivery_lag_days": 2,
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "required_fields": ["sector_code", "change_percent"],
                "allowed_connectors": ["tdx-connector"],
            }
        ],
        "output_contract": "workbuddy-data-bundle/1.0",
    }


def _bundle_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": "req_20260903_sector_01",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "connector": "tdx-connector",
                "tool": "get_sector_ranking",
                "parameters": {"market": "cn", "page": 1},
                "as_of": "2026-09-02",
                "pagination": {"complete": True},
                "sample_count": 1,
                "fields": ["sector_code", "change_percent"],
                "units": {"change_percent": "percent"},
                "records": [{"sector_code": "BK1036", "change_percent": 2.5}],
                "quality_note": {"coverage": "full"},
            }
        ],
        "warnings": ["source reports delayed quotes"],
        "errors": [],
    }


def test_data_request_from_mapping_accepts_minimal_valid_request() -> None:
    request = DataRequest.from_mapping(_request_payload())

    assert request.request_id == "req_20260903_sector_01"
    assert request.stage == "sector_selection"
    assert request.as_of.isoformat() == "2026-09-02"
    assert request.datasets[0].required_fields == ("sector_code", "change_percent")


def test_connector_authority_is_frozen_and_rejects_unknown_connectors() -> None:
    assert frozenset(
        {"tdx-connector", "westock-mcp", "mx-ds-mcp"}
    ) == APPROVED_DATA_CONNECTORS

    request_payload = _request_payload()
    request_payload["datasets"][0]["allowed_connectors"] = ["forged-connector"]
    with pytest.raises(ValueError, match="^allowed_connectors contains an unapproved connector$"):
        DataRequest.from_mapping(request_payload)

    bundle_payload = _bundle_payload()
    bundle_payload["datasets"][0]["connector"] = "forged-connector"
    with pytest.raises(ValueError, match="^connector is not approved$"):
        DataBundle.from_mapping(bundle_payload)


def test_data_request_accepts_bounded_delivery_lag() -> None:
    payload = _request_payload()
    payload["max_delivery_lag_days"] = 2

    assert DataRequest.from_mapping(payload).max_delivery_lag_days == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schema_version="workbuddy-data-request/2.0"),
        lambda payload: payload.update(request_id="../unsafe"),
        lambda payload: payload.update(request_id="request:unsafe"),
        lambda payload: payload.update(request_id="r" * 129),
        lambda payload: payload.update(stage="arbitrary_stage"),
        lambda payload: payload.update(as_of="2026-02-30"),
        lambda payload: payload.update(max_delivery_lag_days=True),
        lambda payload: payload.update(max_delivery_lag_days=-1),
        lambda payload: payload.update(max_delivery_lag_days=8),
        lambda payload: payload.update(datasets=[]),
        lambda payload: payload["datasets"].append(copy.deepcopy(payload["datasets"][0])),
        lambda payload: payload["datasets"][0].update(required_fields=[]),
        lambda payload: payload["datasets"][0].update(
            allowed_connectors=["../../connector"]
        ),
        lambda payload: payload.update(unexpected="value"),
    ],
)
def test_data_request_rejects_unsafe_or_ambiguous_envelopes(mutate) -> None:
    payload = _request_payload()
    mutate(payload)

    with pytest.raises((TypeError, ValueError)):
        DataRequest.from_mapping(payload)


def test_data_request_is_immutable_and_detached_from_input() -> None:
    payload = _request_payload()
    request = DataRequest.from_mapping(payload)

    payload["datasets"][0]["required_fields"].append("late_mutation")

    assert request.datasets[0].required_fields == ("sector_code", "change_percent")
    with pytest.raises(FrozenInstanceError):
        request.stage = "stock_screening"  # type: ignore[misc]


def test_data_bundle_from_mapping_preserves_immutable_business_extensions() -> None:
    payload = _bundle_payload()
    bundle = DataBundle.from_mapping(payload)

    payload["datasets"][0]["parameters"]["page"] = 2
    payload["datasets"][0]["records"][0]["sector_code"] = "MUTATED"
    payload["datasets"][0]["quality_note"]["coverage"] = "partial"

    dataset = bundle.datasets[0]
    assert bundle.generated_at.isoformat() == "2026-09-03T04:00:00+00:00"
    assert dataset.parameters["page"] == 1
    assert dataset.records[0]["sector_code"] == "BK1036"
    assert dataset.extensions["quality_note"]["coverage"] == "full"
    with pytest.raises(TypeError):
        dataset.parameters["page"] = 3  # type: ignore[index]


def test_data_bundle_accepts_timezone_aware_datetime_value() -> None:
    payload = _bundle_payload()
    generated_at = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)
    payload["generated_at"] = generated_at

    assert DataBundle.from_mapping(payload).generated_at is generated_at


def test_data_bundle_preserves_immutable_top_level_business_extensions() -> None:
    payload = _bundle_payload()
    payload["summary"] = "password and token are ordinary words in this report"
    payload["quality"] = {"coverage": ["industry", "concept", "area"]}

    bundle = DataBundle.from_mapping(payload)
    payload["quality"]["coverage"].append("mutated")

    assert bundle.extensions["summary"].startswith("password")
    assert bundle.extensions["quality"]["coverage"] == (
        "industry",
        "concept",
        "area",
    )
    with pytest.raises(TypeError):
        bundle.extensions["summary"] = "mutated"  # type: ignore[index]


@pytest.mark.parametrize("key", ["api_key", "Authorization"])
def test_data_bundle_rejects_sensitive_top_level_extension_keys(key: str) -> None:
    payload = _bundle_payload()
    payload[key] = "super-secret-value"

    with pytest.raises(
        ValueError,
        match="^DataBundle contains a forbidden credential key$",
    ) as exc_info:
        DataBundle.from_mapping(payload)
    assert "super-secret-value" not in str(exc_info.value)


def test_data_bundle_scans_all_object_keys_without_scanning_scalar_values() -> None:
    valid = _bundle_payload()
    valid["summary"] = "authorization_header client_secret_value apiKey accessToken"
    valid["datasets"][0]["records"][0].update(
        monkey="token is ordinary text here",
        secretary_name="password is ordinary text here",
    )
    DataBundle.from_mapping(valid)

    def in_record(payload: dict) -> None:
        payload["datasets"][0]["records"][0]["authorization_header"] = "hidden"

    def in_units(payload: dict) -> None:
        payload["datasets"][0]["units"]["client_secret_value"] = "hidden"

    def in_warnings(payload: dict) -> None:
        payload["warnings"].append({"apiKey": "hidden"})

    def in_errors(payload: dict) -> None:
        payload["errors"].append({"accessToken": "hidden"})

    for mutate in (in_record, in_units, in_warnings, in_errors):
        payload = _bundle_payload()
        mutate(payload)
        with pytest.raises(
            ValueError,
            match="^DataBundle contains a forbidden credential key$",
        ):
            DataBundle.from_mapping(payload)


def test_data_bundle_preserves_immutable_pagination_evidence() -> None:
    payload = _bundle_payload()
    pagination = payload["datasets"][0]["pagination"]
    pagination.update(
        page_count=2,
        cursor_exhausted=True,
        termination_reason="last_page",
    )

    bundle = DataBundle.from_mapping(payload)
    pagination["page_count"] = 99

    parsed = bundle.datasets[0].pagination
    assert parsed.complete is True
    assert parsed.extensions == {
        "page_count": 2,
        "cursor_exhausted": True,
        "termination_reason": "last_page",
    }
    with pytest.raises(TypeError):
        parsed.extensions["page_count"] = 3  # type: ignore[index]

    sensitive = _bundle_payload()
    sensitive["datasets"][0]["pagination"]["client_secret_value"] = "hidden"
    with pytest.raises(
        ValueError,
        match="^DataBundle contains a forbidden credential key$",
    ):
        DataBundle.from_mapping(sensitive)


def test_data_bundle_rejects_credential_keys_without_scanning_business_values() -> None:
    valid = _bundle_payload()
    valid["datasets"][0]["records"][0]["note"] = "password=business headline"
    assert DataBundle.from_mapping(valid).datasets[0].records[0]["note"].startswith(
        "password="
    )

    for mutate in (
        lambda payload: payload["datasets"][0]["parameters"].update(
            Authorization="super-secret-value"
        ),
        lambda payload: payload["datasets"][0].update(api_key="super-secret-value"),
    ):
        payload = _bundle_payload()
        mutate(payload)
        with pytest.raises(ValueError) as exc_info:
            DataBundle.from_mapping(payload)
        assert "super-secret-value" not in str(exc_info.value)


def test_matching_data_bundle_with_warnings_is_ready_for_evaluation() -> None:
    request = DataRequest.from_mapping(_request_payload())
    bundle = DataBundle.from_mapping(_bundle_payload())

    assert validate_data_bundle_for_evaluation(request, bundle) is None


@pytest.mark.parametrize(
    ("request_lag", "generated_at", "message"),
    [
        (
            2,
            "2026-09-01T23:59:59+00:00",
            "DataBundle generated_at precedes DataRequest as_of",
        ),
        (
            0,
            "2026-09-03T00:00:00+00:00",
            "DataBundle delivery exceeds max_delivery_lag_days",
        ),
    ],
)
def test_data_bundle_validation_rejects_stale_delivery(
    request_lag: int, generated_at: str, message: str
) -> None:
    request_payload = _request_payload()
    request_payload["max_delivery_lag_days"] = request_lag
    bundle_payload = _bundle_payload()
    bundle_payload["generated_at"] = generated_at

    with pytest.raises(ValueError, match=f"^{message}$"):
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(request_payload),
            DataBundle.from_mapping(bundle_payload),
        )


@pytest.mark.parametrize(
    "generated_at",
    ["2026-09-02T00:30:00+08:00", "2026-09-01T16:30:00+00:00"],
)
def test_delivery_freshness_uses_utc_date_for_equivalent_instants(
    generated_at: str,
) -> None:
    request_payload = _request_payload()
    request_payload["as_of"] = "2026-09-01"
    request_payload["max_delivery_lag_days"] = 0
    bundle_payload = _bundle_payload()
    bundle_payload["generated_at"] = generated_at
    bundle_payload["datasets"][0]["as_of"] = "2026-09-01"

    assert (
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(request_payload),
            DataBundle.from_mapping(bundle_payload),
        )
        is None
    )


def _mutate_missing_requested_dataset(request: dict, bundle: dict) -> None:
    request["datasets"].append(
        {
            "dataset_key": "sector-constituents",
            "required_fields": ["sector_code", "symbol"],
            "allowed_connectors": ["tdx-connector"],
        }
    )


def _mutate_duplicate_bundle_dataset(request: dict, bundle: dict) -> None:
    bundle["datasets"].append(copy.deepcopy(bundle["datasets"][0]))


def _mutate_extra_bundle_dataset(request: dict, bundle: dict) -> None:
    extra = copy.deepcopy(bundle["datasets"][0])
    extra["dataset_key"] = "unrequested-data"
    bundle["datasets"].append(extra)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda request, bundle: bundle.update(request_id="req_other"),
            "DataBundle request identity does not match DataRequest",
        ),
        (
            _mutate_missing_requested_dataset,
            "DataBundle is missing a requested dataset",
        ),
        (
            _mutate_duplicate_bundle_dataset,
            "DataBundle contains a duplicate dataset_key",
        ),
        (
            _mutate_extra_bundle_dataset,
            "DataBundle contains an unrequested dataset",
        ),
        (
            lambda request, bundle: bundle["datasets"][0].update(connector="mx-ds-mcp"),
            "DataBundle dataset connector is not allowed",
        ),
        (
            lambda request, bundle: bundle["datasets"][0].update(as_of="2026-09-01"),
            "DataBundle dataset as_of does not match DataRequest",
        ),
        (
            lambda request, bundle: bundle["datasets"][0]["pagination"].update(
                complete=False
            ),
            "DataBundle dataset pagination is incomplete",
        ),
        (
            lambda request, bundle: bundle["datasets"][0].update(
                fields=["sector_code"]
            ),
            "DataBundle dataset is missing a required field",
        ),
        (
            lambda request, bundle: bundle["datasets"][0]["records"][0].pop(
                "change_percent"
            ),
            "DataBundle record is missing a required field",
        ),
        (
            lambda request, bundle: bundle["datasets"][0].update(sample_count=2),
            "DataBundle dataset sample_count does not match records",
        ),
        (
            lambda request, bundle: bundle.update(errors=[{"code": "upstream_failed"}]),
            "DataBundle reports acquisition errors",
        ),
    ],
)
def test_data_bundle_validation_fails_closed(mutate, message: str) -> None:
    request_payload = _request_payload()
    bundle_payload = _bundle_payload()
    mutate(request_payload, bundle_payload)
    request = DataRequest.from_mapping(request_payload)
    bundle = DataBundle.from_mapping(bundle_payload)

    with pytest.raises(ValueError, match=f"^{message}$"):
        validate_data_bundle_for_evaluation(request, bundle)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schema_version="workbuddy-data-bundle/2.0"),
        lambda payload: payload.update(producer="invest-infra"),
        lambda payload: payload.update(generated_at="2026-09-03T04:00:00"),
        lambda payload: payload.update(request_id="../../request"),
        lambda payload: payload.update(request_id=r"folder\request"),
        lambda payload: payload.update(request_id="request:unsafe"),
        lambda payload: payload.update(request_id="r" * 129),
        lambda payload: payload.update(datasets=[]),
        lambda payload: payload["datasets"][0].update(fields=[]),
        lambda payload: payload["datasets"][0].update(sample_count=True),
        lambda payload: payload["datasets"][0]["records"].append("not-an-object"),
        lambda payload: payload["datasets"][0].update({7: "non-json-key"}),
    ],
)
def test_data_bundle_rejects_invalid_envelope_or_dataset_shape(mutate) -> None:
    payload = _bundle_payload()
    mutate(payload)

    with pytest.raises((TypeError, ValueError)):
        DataBundle.from_mapping(payload)
