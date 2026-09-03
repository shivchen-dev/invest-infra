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


def _attempt(
    connector: str = "tdx-connector",
    *,
    status: str = "succeeded",
    tool: str = "get_sector_ranking",
    parameters: dict | None = None,
    error_code: str | None = None,
) -> dict:
    if status == "failed" and error_code is None:
        error_code = "UPSTREAM_TIMEOUT"
    return {
        "connector": connector,
        "tool": tool,
        "parameters": (
            parameters if parameters is not None else {"market": "cn", "page": 1}
        ),
        "status": status,
        "error_code": error_code,
    }


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


def _stock_request_payload() -> dict:
    payload = _request_payload()
    payload.update(
        request_id="req_20260903_stock_01",
        definition_key="stock-market-data",
        strategy_key="stock-screening",
        stage="stock_screening",
        upstream_stage_result={
            "stage_result_id": "stage-sector-20260902-01",
            "stage_result_sha256": "b" * 64,
            "constituent_snapshot_sha256": "c" * 64,
            "group": "industry",
            "as_of": "2026-09-02",
        },
    )
    return payload


def _bundle_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": "req_20260903_sector_01",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "attempts": [_attempt()],
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
    assert request.max_delivery_lag_days == 2
    assert request.datasets[0].required_fields == ("sector_code", "change_percent")
    assert request.datasets[0].optional_fields == ()
    assert request.upstream_stage_result is None


def test_data_request_accepts_distinct_optional_acquisition_fields() -> None:
    payload = _request_payload()
    payload["datasets"][0]["optional_fields"] = ["news_annotation", "ladder_annotation"]

    request = DataRequest.from_mapping(payload)

    assert request.datasets[0].optional_fields == (
        "news_annotation",
        "ladder_annotation",
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda dataset: dataset.update(optional_fields=[]),
        lambda dataset: dataset.update(optional_fields=["unsafe/field"]),
        lambda dataset: dataset.update(optional_fields=["annotation", "annotation"]),
        lambda dataset: dataset.update(optional_fields=["sector_code"]),
        lambda dataset: dataset.update(
            required_fields=["sector_code", "sector_code"]
        ),
    ],
)
def test_data_request_rejects_invalid_duplicate_or_overlapping_field_names(
    mutate,
) -> None:
    payload = _request_payload()
    mutate(payload["datasets"][0])

    with pytest.raises((TypeError, ValueError)):
        DataRequest.from_mapping(payload)


@pytest.mark.parametrize("group", ["industry", "concept", "area"])
def test_stock_request_requires_and_preserves_upstream_stage_result_binding(
    group: str,
) -> None:
    payload = _stock_request_payload()
    payload["upstream_stage_result"]["group"] = group
    request = DataRequest.from_mapping(payload)

    payload["upstream_stage_result"]["stage_result_id"] = "mutated"

    binding = request.upstream_stage_result
    assert binding is not None
    assert binding.stage_result_id == "stage-sector-20260902-01"
    assert binding.stage_result_sha256 == "b" * 64
    assert binding.constituent_snapshot_sha256 == "c" * 64
    assert binding.group == group
    assert binding.as_of == request.as_of


def test_sector_request_must_not_carry_upstream_stage_result_binding() -> None:
    payload = _request_payload()
    payload["upstream_stage_result"] = _stock_request_payload()[
        "upstream_stage_result"
    ]

    with pytest.raises(
        ValueError,
        match="^sector_selection DataRequest must not bind an upstream StageResult$",
    ):
        DataRequest.from_mapping(payload)


def test_stock_request_must_carry_upstream_stage_result_binding() -> None:
    payload = _request_payload()
    payload["stage"] = "stock_screening"

    with pytest.raises(
        ValueError,
        match="^stock_screening DataRequest requires an upstream StageResult$",
    ):
        DataRequest.from_mapping(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda binding: binding.update(stage_result_id="../unsafe"),
            "stage_result_id",
        ),
        (
            lambda binding: binding.update(stage_result_sha256="B" * 64),
            "stage_result_sha256",
        ),
        (
            lambda binding: binding.update(constituent_snapshot_sha256="short"),
            "constituent_snapshot_sha256",
        ),
        (lambda binding: binding.update(group="theme"), "group"),
        (lambda binding: binding.update(as_of="2026-09-01"), "as_of"),
        (lambda binding: binding.pop("stage_result_id"), "fields"),
        (lambda binding: binding.update(unexpected="value"), "fields"),
    ],
)
def test_stock_request_rejects_invalid_upstream_stage_result_binding(
    mutate, message: str
) -> None:
    payload = _stock_request_payload()
    mutate(payload["upstream_stage_result"])

    with pytest.raises((TypeError, ValueError), match=message):
        DataRequest.from_mapping(payload)


def test_connector_authority_is_frozen_and_rejects_unknown_connectors() -> None:
    assert frozenset(
        {"tdx-connector", "westock-mcp", "mx-ds-mcp"}
    ) == APPROVED_DATA_CONNECTORS

    request_payload = _request_payload()
    request_payload["datasets"][0]["allowed_connectors"] = ["forged-connector"]
    with pytest.raises(ValueError, match="^allowed_connectors contains an unapproved connector$"):
        DataRequest.from_mapping(request_payload)

    bundle_payload = _bundle_payload()
    bundle_payload["datasets"][0]["attempts"][0]["connector"] = "forged-connector"
    with pytest.raises(ValueError, match="^attempt connector is not approved$"):
        DataBundle.from_mapping(bundle_payload)


def test_data_request_rejects_duplicate_ordered_fallback_connectors() -> None:
    payload = _request_payload()
    payload["datasets"][0]["allowed_connectors"] = [
        "tdx-connector",
        "tdx-connector",
    ]

    with pytest.raises(
        ValueError,
        match="^allowed_connectors contains a duplicate connector$",
    ):
        DataRequest.from_mapping(payload)


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
        lambda payload: payload["datasets"][0].update(allowed_connectors=["../../connector"]),
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

    payload["datasets"][0]["attempts"][0]["parameters"]["page"] = 2
    payload["datasets"][0]["records"][0]["sector_code"] = "MUTATED"
    payload["datasets"][0]["quality_note"]["coverage"] = "partial"

    dataset = bundle.datasets[0]
    attempt = dataset.attempts[0]
    assert bundle.generated_at.isoformat() == "2026-09-03T04:00:00+00:00"
    assert (attempt.connector, attempt.tool, attempt.status, attempt.error_code) == (
        "tdx-connector", "get_sector_ranking", "succeeded", None
    )
    assert attempt.parameters["page"] == 1
    assert dataset.records[0]["sector_code"] == "BK1036"
    assert dataset.extensions["quality_note"]["coverage"] == "full"
    with pytest.raises(TypeError):
        attempt.parameters["page"] = 2  # type: ignore[index]


@pytest.mark.parametrize("unknown_field", ["error_message", "diagnostic", "latency_ms"])
def test_data_bundle_attempt_rejects_unknown_fields(unknown_field: str) -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"][0][unknown_field] = "not-allowed"

    with pytest.raises(
        ValueError,
        match="^DataBundle attempt fields are invalid$",
    ):
        DataBundle.from_mapping(payload)


@pytest.mark.parametrize("legacy_field", ["connector", "tool", "parameters"])
def test_data_bundle_dataset_rejects_legacy_final_source_fields(
    legacy_field: str,
) -> None:
    payload = _bundle_payload()
    payload["datasets"][0][legacy_field] = "legacy"

    with pytest.raises(
        ValueError,
        match="^DataBundle dataset contains a forbidden legacy source field$",
    ):
        DataBundle.from_mapping(payload)


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
    assert bundle.extensions["quality"]["coverage"] == ("industry", "concept", "area")
    with pytest.raises(TypeError):
        bundle.extensions["summary"] = "mutated"  # type: ignore[index]


def test_data_bundle_does_not_scan_business_scalar_values() -> None:
    valid = _bundle_payload()
    valid["summary"] = "authorization_header client_secret_value apiKey accessToken"
    valid["datasets"][0]["records"][0].update(
        monkey="token is ordinary text here",
        secretary_name="password is ordinary text here",
    )
    DataBundle.from_mapping(valid)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(api_key="hidden"),
        lambda p: p["datasets"][0]["records"][0].update(authorization="hidden"),
        lambda p: p["datasets"][0]["units"].update(client_secret_value="hidden"),
        lambda p: p["datasets"][0]["pagination"].update(apiKey="hidden"),
        lambda p: p["datasets"][0]["attempts"][0]["parameters"].update(token="hidden"),
        lambda p: p["datasets"][0].update(credentials="hidden"),
        lambda p: p["warnings"].append({"accessToken": "hidden"}),
        lambda p: p["errors"].append({"private_key": "hidden"}),
    ],
)
def test_data_bundle_rejects_sensitive_keys_anywhere(mutate) -> None:
    payload = _bundle_payload()
    mutate(payload)
    with pytest.raises(ValueError, match="forbidden credential key") as exc_info:
        DataBundle.from_mapping(payload)
    assert "hidden" not in str(exc_info.value)


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



def test_matching_data_bundle_with_warnings_is_ready_for_evaluation() -> None:
    request = DataRequest.from_mapping(_request_payload())
    bundle = DataBundle.from_mapping(_bundle_payload())

    assert validate_data_bundle_for_evaluation(request, bundle) is None


def test_missing_optional_acquisition_fields_remain_ready_for_evaluation() -> None:
    request_payload = _request_payload()
    request_payload["datasets"][0]["optional_fields"] = [
        "news_annotation",
        "ladder_annotation",
    ]
    request = DataRequest.from_mapping(request_payload)
    bundle = DataBundle.from_mapping(_bundle_payload())

    assert validate_data_bundle_for_evaluation(request, bundle) is None


def test_evaluation_rejects_fallback_that_skips_primary_connector() -> None:
    request_payload = _fallback_request_payload()
    bundle_payload = _bundle_payload()
    bundle_payload["datasets"][0]["attempts"] = [
        _attempt("westock-mcp", tool="get_sector_ranking_fallback")
    ]

    with pytest.raises(
        ValueError,
        match="^DataBundle attempt connectors must match the allowed connector prefix$",
    ):
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(request_payload),
            DataBundle.from_mapping(bundle_payload),
        )


def test_primary_failure_then_ordered_fallback_success_is_ready_for_evaluation() -> None:
    request_payload = _fallback_request_payload()
    bundle_payload = _bundle_payload()
    bundle_payload["datasets"][0]["attempts"] = [
        _attempt(status="failed"),
        _attempt("westock-mcp", tool="get_sector_ranking_fallback"),
    ]

    assert (
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(request_payload),
            DataBundle.from_mapping(bundle_payload),
        )
        is None
    )


def test_multiple_datasets_can_use_different_approved_connectors() -> None:
    request_payload = _request_payload()
    request_payload["datasets"].append(
        {
            "dataset_key": "market-breadth",
            "required_fields": ["up_count", "total_count"],
            "allowed_connectors": ["mx-ds-mcp"],
        }
    )
    bundle_payload = _bundle_payload()
    bundle_payload["datasets"].append(
        {
            "dataset_key": "market-breadth",
            "attempts": [_attempt("mx-ds-mcp", tool="get_market_breadth")],
            "as_of": "2026-09-02",
            "pagination": {"complete": True},
            "sample_count": 1,
            "fields": ["up_count", "total_count"],
            "units": {"up_count": "count", "total_count": "count"},
            "records": [{"up_count": 21, "total_count": 180}],
        }
    )

    assert (
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(request_payload),
            DataBundle.from_mapping(bundle_payload),
        )
        is None
    )


def _fallback_request_payload() -> dict:
    payload = _request_payload()
    payload["datasets"][0]["allowed_connectors"] = [
        "tdx-connector",
        "westock-mcp",
    ]
    return payload


def test_evaluation_rejects_out_of_order_attempts() -> None:
    bundle_payload = _bundle_payload()
    bundle_payload["datasets"][0]["attempts"] = [
        _attempt("westock-mcp", status="failed"),
        _attempt(),
    ]

    with pytest.raises(
        ValueError,
        match="^DataBundle attempt connectors must match the allowed connector prefix$",
    ):
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(_fallback_request_payload()),
            DataBundle.from_mapping(bundle_payload),
        )


@pytest.mark.parametrize(
    ("attempts", "message"),
    [
        (
            [_attempt(), _attempt("westock-mcp")],
            "DataBundle dataset attempts has multiple successes",
        ),
        (
            [_attempt(), _attempt("westock-mcp", status="failed")],
            "succeeded DataBundle attempt must be last",
        ),
    ],
)
def test_data_bundle_rejects_invalid_success_attempt_sequence(
    attempts: list[dict], message: str
) -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"] = attempts

    with pytest.raises(ValueError, match=f"^{message}$"):
        DataBundle.from_mapping(payload)


def test_data_bundle_rejects_duplicate_attempt_connectors_during_parsing() -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"] = [
        _attempt(status="failed"),
        _attempt(status="failed"),
    ]

    with pytest.raises(
        ValueError,
        match="^DataBundle dataset attempts contains a duplicate connector$",
    ):
        DataBundle.from_mapping(payload)


def test_data_bundle_rejects_attempt_count_above_approved_connector_bound() -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"] = [
        _attempt("tdx-connector", status="failed"),
        _attempt("westock-mcp", status="failed"),
        _attempt("mx-ds-mcp", status="failed"),
        _attempt("tdx-connector", status="failed"),
    ]

    with pytest.raises(
        ValueError,
        match="^DataBundle dataset attempts exceeds approved connector count$",
    ):
        DataBundle.from_mapping(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda attempt: attempt.update(error_code=""),
            "attempt error_code must be a non-blank string",
        ),
        (
            lambda attempt: attempt.update(error_code=None),
            "attempt error_code must be a non-blank string",
        ),
        (
            lambda attempt: attempt.update(status="succeeded", error_code="TIMEOUT"),
            "succeeded DataBundle attempt must not have an error_code",
        ),
        (
            lambda attempt: attempt.update(connector="unknown-connector"),
            "attempt connector is not approved",
        ),
        (
            lambda attempt: attempt.update(tool="../unsafe"),
            "attempt tool contains unsafe characters",
        ),
    ],
)
def test_data_bundle_rejects_invalid_attempt_fields(mutate, message: str) -> None:
    payload = _bundle_payload()
    attempt = _attempt(status="failed")
    mutate(attempt)
    payload["datasets"][0]["attempts"] = [attempt]

    with pytest.raises((TypeError, ValueError), match=f"^{message}$"):
        DataBundle.from_mapping(payload)


@pytest.mark.parametrize(
    "error_code",
    [
        "UNKNOWN_UPSTREAM_FAILURE",
        "X" * 512,
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature",
    ],
)
def test_data_bundle_rejects_unapproved_or_token_shaped_error_codes(
    error_code: str,
) -> None:
    payload = _bundle_payload()
    attempt = _attempt(status="failed")
    attempt["error_code"] = error_code
    payload["datasets"][0]["attempts"] = [attempt]

    with pytest.raises(
        ValueError,
        match="^DataBundle attempt error_code is unsupported$",
    ):
        DataBundle.from_mapping(payload)


def test_data_bundle_rejects_sensitive_attempt_parameters() -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"][0]["parameters"]["api_key"] = "hidden"

    with pytest.raises(
        ValueError,
        match="^DataBundle contains a forbidden credential key$",
    ):
        DataBundle.from_mapping(payload)


def test_all_failed_attempts_parse_but_are_rejected_for_evaluation() -> None:
    payload = _bundle_payload()
    payload["datasets"][0]["attempts"] = [_attempt(status="failed")]
    bundle = DataBundle.from_mapping(payload)

    assert bundle.datasets[0].attempts[0].status == "failed"
    with pytest.raises(
        ValueError,
        match="^DataBundle dataset must have exactly one successful attempt$",
    ):
        validate_data_bundle_for_evaluation(
            DataRequest.from_mapping(_request_payload()), bundle
        )


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
        (lambda _r, b: b.update(request_id="req_other"), "request identity"),
        (_mutate_missing_requested_dataset, "missing a requested dataset"),
        (_mutate_duplicate_bundle_dataset, "duplicate dataset_key"),
        (_mutate_extra_bundle_dataset, "unrequested dataset"),
        (lambda _r, b: b["datasets"][0].update(as_of="2026-09-01"), "as_of"),
        (lambda _r, b: b["datasets"][0]["pagination"].update(complete=False), "pagination"),
        (lambda _r, b: b["datasets"][0].update(fields=["sector_code"]), "required field"),
        (lambda _r, b: b["datasets"][0]["records"][0].pop("change_percent"), "record"),
        (lambda _r, b: b["datasets"][0].update(sample_count=2), "sample_count"),
        (lambda _r, b: b.update(errors=[{"code": "upstream_failed"}]), "acquisition errors"),
    ],
)
def test_data_bundle_validation_fails_closed(mutate, message: str) -> None:
    request_payload = _request_payload()
    bundle_payload = _bundle_payload()
    mutate(request_payload, bundle_payload)
    request = DataRequest.from_mapping(request_payload)
    bundle = DataBundle.from_mapping(bundle_payload)

    with pytest.raises(ValueError, match=message):
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
        lambda payload: payload["datasets"][0].pop("attempts"),
        lambda payload: payload["datasets"][0].update(attempts=[]),
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
