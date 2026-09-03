import copy
import dataclasses
import json
import re
import traceback
from types import MappingProxyType

import pytest
from invest_domain.strategy import DataBundle, DataRequest
from invest_pipeline.integrations.workbuddy_data_bundle_codec import (
    DataBundleDecodeError,
    DataBundleValidationError,
    ValidatedDataBundle,
    decode_and_validate_data_bundle,
)

_MINIMAL_RAW_BYTES = (
    b'{"schema_version":"workbuddy-data-bundle/1.0","request_id":"codec-minimal-001",'
    b'"producer":"workbuddy","generated_at":"2026-09-03T04:00:00+00:00","datasets":'
    b'[{"dataset_key":"sector-ranking","attempts":[{"connector":"tdx-connector",'
    b'"tool":"get_sector_ranking","parameters":{"market":"cn","page":1},'
    b'"status":"succeeded","error_code":null}],"as_of":"2026-09-02",'
    b'"pagination":{"complete":true},"sample_count":1,"fields":'
    b'["sector_code","change_percent"],"units":{"change_percent":"percent"},'
    b'"records":[{"sector_code":"BK1036","change_percent":2.5}]}],"warnings":[],"errors":[]}'
)
_EXPECTED_RAW_SHA256 = "e91f2b0bc89da08325af9eae9fd7c4f1e7c6d0ad07d92512815a215844516311"
_EXPECTED_CANONICAL_BYTES = (
    b'{"datasets":[{"as_of":"2026-09-02","attempts":[{"connector":"tdx-connector",'
    b'"error_code":null,"parameters":{"market":"cn","page":1},"status":"succeeded",'
    b'"tool":"get_sector_ranking"}],"dataset_key":"sector-ranking",'
    b'"fields":["sector_code","change_percent"],"pagination":{"complete":true},'
    b'"records":[{"change_percent":"2.5","sector_code":"BK1036"}],"sample_count":1,'
    b'"units":{"change_percent":"percent"}}],"errors":[],"generated_at":'
    b'"2026-09-03T04:00:00+00:00","producer":"workbuddy","request_id":'
    b'"codec-minimal-001","schema_version":"workbuddy-data-bundle/1.0","warnings":[]}'
)
_EXPECTED_CANONICAL_SHA256 = "b5f68db3f764b8f016cecf1bb4e8d61888a6cba2720165e1e2dbdb2b5cbbc7dd"


def _request_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "codec-minimal-001",
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


def _attempt(
    connector: str = "tdx-connector",
    *,
    tool: str = "get_sector_ranking",
    status: str = "succeeded",
    error_code: str | None = None,
) -> dict:
    if status == "failed" and error_code is None:
        error_code = "UPSTREAM_TIMEOUT"
    return {
        "connector": connector,
        "tool": tool,
        "parameters": {"market": "cn", "page": 1},
        "status": status,
        "error_code": error_code,
    }


def _bundle_payload(
    request_payload: dict,
    *,
    generated_at: str = "2026-09-03T04:00:00+00:00",
) -> dict:
    request_dataset = request_payload["datasets"][0]
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": request_payload["request_id"],
        "producer": "workbuddy",
        "generated_at": generated_at,
        "datasets": [
            {
                "dataset_key": request_dataset["dataset_key"],
                "attempts": [_attempt()],
                "as_of": request_payload["as_of"],
                "pagination": {"complete": True},
                "sample_count": 1,
                "fields": list(request_dataset["required_fields"]),
                "units": {"change_percent": "percent"},
                "records": [{"sector_code": "BK1036", "change_percent": 2.5}],
            }
        ],
        "warnings": [],
        "errors": [],
    }


def _raw(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _raw_with_change_percent(number: str) -> bytes:
    needle = b'"change_percent":2.5'
    assert _MINIMAL_RAW_BYTES.count(needle) == 1
    return _MINIMAL_RAW_BYTES.replace(
        needle,
        b'"change_percent":' + number.encode("ascii"),
    )


def _assert_sanitized_traceback(exc: BaseException, *untrusted: str) -> None:
    assert exc.__cause__ is None
    assert exc.__context__ is None
    rendered = "".join(traceback.format_exception(exc))
    for fragment in untrusted:
        assert fragment not in rendered


def _assert_decode_error(
    exc: DataBundleDecodeError,
    code: str,
    message: str,
) -> None:
    assert exc.code == code
    assert exc.message == message
    assert str(exc) == message


def test_minimal_valid_bundle_returns_frozen_projection_with_literal_hashes() -> None:
    input_mapping = json.loads(_MINIMAL_RAW_BYTES)
    original_input = copy.deepcopy(input_mapping)
    request_payload = _request_payload()
    request = DataRequest.from_mapping(request_payload)
    original_request = copy.deepcopy(request)
    expected_bundle = DataBundle.from_mapping(input_mapping)

    result = decode_and_validate_data_bundle(request, _MINIMAL_RAW_BYTES)

    assert isinstance(result, ValidatedDataBundle)
    assert [field.name for field in dataclasses.fields(ValidatedDataBundle)] == [
        "bundle",
        "raw_sha256",
        "canonical_bytes",
        "canonical_sha256",
        "lineage",
    ]
    assert result.bundle == expected_bundle
    assert request == original_request
    assert input_mapping == original_input
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.raw_sha256 = "0" * 64
    assert result.raw_sha256 == _EXPECTED_RAW_SHA256
    assert result.canonical_bytes == _EXPECTED_CANONICAL_BYTES
    assert result.canonical_sha256 == _EXPECTED_CANONICAL_SHA256
    assert re.fullmatch(r"[0-9a-f]{64}", result.raw_sha256)
    assert re.fullmatch(r"[0-9a-f]{64}", result.canonical_sha256)
    assert set(result.lineage) == {
        "request_id",
        "definition_key",
        "definition_version",
        "strategy_key",
        "strategy_version",
        "strategy_artifact_hash",
        "stage",
        "producer",
        "generated_at",
        "datasets",
    }
    assert tuple(result.lineage["datasets"]) == (
        {
            "dataset_key": "sector-ranking",
            "sample_count": 1,
            "fields": ("sector_code", "change_percent"),
            "pagination_complete": True,
            "attempts": (
                {
                    "connector": "tdx-connector",
                    "tool": "get_sector_ranking",
                    "status": "succeeded",
                    "error_code": None,
                },
            ),
        },
    )


def test_equivalent_objects_with_different_key_order_and_whitespace_are_canonical() -> None:
    payload = json.loads(_MINIMAL_RAW_BYTES)
    request = DataRequest.from_mapping(_request_payload())
    first = decode_and_validate_data_bundle(request, _raw(payload))
    reordered = {
        "producer": payload["producer"],
        "datasets": payload["datasets"],
        "errors": payload["errors"],
        "warnings": payload["warnings"],
        "generated_at": payload["generated_at"],
        "request_id": payload["request_id"],
        "schema_version": payload["schema_version"],
    }
    second = decode_and_validate_data_bundle(
        request,
        json.dumps(reordered, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"),
    )

    assert first.raw_sha256 != second.raw_sha256
    assert first.canonical_bytes == second.canonical_bytes
    assert first.canonical_sha256 == second.canonical_sha256

    reordered["datasets"][0]["fields"].reverse()
    changed_order = decode_and_validate_data_bundle(request, _raw(reordered))

    assert changed_order.canonical_bytes != first.canonical_bytes
    assert changed_order.canonical_sha256 != first.canonical_sha256


def test_fractional_numbers_preserve_exact_json_semantics_before_float_projection() -> None:
    request = DataRequest.from_mapping(_request_payload())

    lower = decode_and_validate_data_bundle(
        request,
        _raw_with_change_percent("9007199254740992.0"),
    )
    higher = decode_and_validate_data_bundle(
        request,
        _raw_with_change_percent("9007199254740993.0"),
    )

    assert lower.bundle.datasets[0].records[0]["change_percent"] == float(
        "9007199254740992.0"
    )
    assert higher.bundle.datasets[0].records[0]["change_percent"] == float(
        "9007199254740993.0"
    )
    assert lower.canonical_bytes != higher.canonical_bytes
    assert lower.canonical_sha256 != higher.canonical_sha256
    assert b'"change_percent":"9007199254740992"' in lower.canonical_bytes
    assert b'"change_percent":"9007199254740993"' in higher.canonical_bytes


def test_fractional_exponents_and_signed_zero_follow_stable_canonical_rules() -> None:
    request = DataRequest.from_mapping(_request_payload())

    plain = decode_and_validate_data_bundle(request, _raw_with_change_percent("2.5"))
    exponent = decode_and_validate_data_bundle(
        request,
        _raw_with_change_percent("25e-1"),
    )
    positive_zero = decode_and_validate_data_bundle(
        request,
        _raw_with_change_percent("0.0"),
    )
    negative_zero = decode_and_validate_data_bundle(
        request,
        _raw_with_change_percent("-0.0"),
    )

    assert exponent.canonical_bytes == plain.canonical_bytes
    assert exponent.canonical_sha256 == plain.canonical_sha256
    assert negative_zero.canonical_bytes == positive_zero.canonical_bytes
    assert negative_zero.canonical_sha256 == positive_zero.canonical_sha256
    assert b'"change_percent":"0"' in negative_zero.canonical_bytes


def test_integer_and_fractional_json_numbers_remain_distinct_in_canonical_form() -> None:
    request = DataRequest.from_mapping(_request_payload())

    integer = decode_and_validate_data_bundle(request, _raw_with_change_percent("1"))
    fractional = decode_and_validate_data_bundle(request, _raw_with_change_percent("1.0"))

    assert integer.canonical_bytes != fractional.canonical_bytes
    assert integer.canonical_sha256 != fractional.canonical_sha256
    assert b'"change_percent":1' in integer.canonical_bytes
    assert b'"change_percent":"1"' in fractional.canonical_bytes


@pytest.mark.parametrize(
    ("number", "code"),
    [
        ("2.5e", "invalid_json"),
        ("1e309", "invalid_data_bundle"),
        ("1e-999", "invalid_data_bundle"),
    ],
)
def test_malformed_or_unrepresentable_fractional_numbers_are_rejected(
    number: str,
    code: str,
) -> None:
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, _raw_with_change_percent(number))

    assert exc_info.value.code == code
    _assert_sanitized_traceback(exc_info.value, number)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_standard_json_constants_remain_rejected(constant: str) -> None:
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, _raw_with_change_percent(constant))

    assert exc_info.value.code == "invalid_json"
    _assert_sanitized_traceback(exc_info.value, constant)


def test_duplicate_json_keys_remain_rejected() -> None:
    request = DataRequest.from_mapping(_request_payload())
    raw = _MINIMAL_RAW_BYTES[:-1] + b',"request_id":"secret-duplicate-id"}'

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, raw)

    assert exc_info.value.code == "invalid_json"
    _assert_sanitized_traceback(exc_info.value, "secret-duplicate-id")


@pytest.mark.parametrize(
    ("raw", "code", "message"),
    [
        (
            b"not-json",
            "invalid_json",
            "Data bundle payload is not valid JSON.",
        ),
        (b"[]", "json_root_not_object", "Data bundle payload must be a JSON object."),
    ],
)
def test_invalid_json_uses_stable_sanitized_decode_errors(
    raw: bytes,
    code: str,
    message: str,
) -> None:
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, raw)

    _assert_decode_error(exc_info.value, code, message)
    _assert_sanitized_traceback(exc_info.value, "not-json")


def test_malformed_utf8_is_rejected_without_decoder_details() -> None:
    request = DataRequest.from_mapping(_request_payload())
    raw = b'{"datasets":"\xff"}'

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, raw)

    _assert_decode_error(exc_info.value, "invalid_utf8", "Data bundle payload is not valid UTF-8.")
    _assert_sanitized_traceback(exc_info.value, "datasets", "\\xff")


def test_wrong_request_and_raw_types_are_rejected_before_decoding() -> None:
    request = DataRequest.from_mapping(_request_payload())
    cases = ((object(), b"{}"), (request, bytearray(b"{}")), (request, "{}"))

    for invalid_request, invalid_raw in cases:
        with pytest.raises(DataBundleDecodeError) as exc_info:
            decode_and_validate_data_bundle(invalid_request, invalid_raw)

        _assert_decode_error(
            exc_info.value,
            "invalid_argument_types",
            "Data bundle request must be a DataRequest and raw payload must be bytes.",
        )
        assert exc_info.value.__cause__ is None


def test_forbidden_sensitive_key_at_depth_is_rejected_without_copying_value() -> None:
    payload = json.loads(_MINIMAL_RAW_BYTES)
    payload["datasets"][0]["records"][0]["api_key"] = "top-secret-value"
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleDecodeError) as exc_info:
        decode_and_validate_data_bundle(request, _raw(payload))

    _assert_decode_error(
        exc_info.value,
        "forbidden_sensitive_key",
        "Data bundle payload contains a forbidden sensitive key.",
    )
    _assert_sanitized_traceback(exc_info.value, "top-secret-value", "api_key")


def test_request_identity_mismatch_uses_sanitized_validation_error() -> None:
    payload = _bundle_payload(_request_payload())
    payload["request_id"] = "different-secret-request"
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleValidationError) as exc_info:
        decode_and_validate_data_bundle(request, _raw(payload))

    assert exc_info.value.code == "request_identity_mismatch"
    assert exc_info.value.message == "Data bundle request identity does not match the request."
    _assert_sanitized_traceback(
        exc_info.value,
        "different-secret-request",
        "codec-minimal-001",
    )


def test_stale_delivery_uses_sanitized_validation_error() -> None:
    request_payload = _request_payload()
    request_payload["max_delivery_lag_days"] = 0
    payload = _bundle_payload(request_payload, generated_at="2026-09-03T04:00:00+00:00")
    request = DataRequest.from_mapping(request_payload)

    with pytest.raises(DataBundleValidationError) as exc_info:
        decode_and_validate_data_bundle(request, _raw(payload))

    assert exc_info.value.code == "stale_delivery"
    assert exc_info.value.message == "Data bundle delivery is stale."
    _assert_sanitized_traceback(exc_info.value, "2026-09-03", "2026-09-02")


def test_acquisition_error_uses_sanitized_validation_error() -> None:
    payload = _bundle_payload(_request_payload())
    payload["errors"] = [
        {"code": "UPSTREAM_FAILED", "body": "private database connection string"}
    ]
    request = DataRequest.from_mapping(_request_payload())

    with pytest.raises(DataBundleValidationError) as exc_info:
        decode_and_validate_data_bundle(request, _raw(payload))

    assert exc_info.value.code == "acquisition_errors"
    assert exc_info.value.message == "Data bundle reports acquisition errors."
    _assert_sanitized_traceback(
        exc_info.value,
        "private database",
        "UPSTREAM_FAILED",
    )


def test_connector_fallback_validation_failure_uses_sanitized_validation_error() -> None:
    request_payload = _request_payload()
    request_payload["datasets"][0]["allowed_connectors"] = [
        "tdx-connector",
        "westock-mcp",
    ]
    payload = _bundle_payload(request_payload)
    payload["datasets"][0]["attempts"] = [
        _attempt("westock-mcp", tool="get_sector_ranking_fallback")
    ]
    request = DataRequest.from_mapping(request_payload)

    with pytest.raises(DataBundleValidationError) as exc_info:
        decode_and_validate_data_bundle(request, _raw(payload))

    assert exc_info.value.code == "connector_prefix_mismatch"
    assert exc_info.value.message == "Data bundle connector fallback sequence is invalid."
    _assert_sanitized_traceback(exc_info.value, "tdx-connector", "westock-mcp")


def test_lineage_is_deeply_immutable_and_omits_unsafe_payload_content() -> None:
    request_payload = _request_payload()
    request_payload["datasets"][0]["allowed_connectors"] = [
        "tdx-connector",
        "westock-mcp",
    ]
    payload = _bundle_payload(request_payload)
    dataset = payload["datasets"][0]
    dataset["attempts"] = [
        _attempt(status="failed"),
        _attempt("westock-mcp", tool="get_sector_ranking_fallback"),
    ]
    dataset["attempts"][0]["parameters"] = {
        "secretary_note": "private-secret-value",
        "page": 1,
    }
    dataset["records"][0]["private_note"] = "sensitive dataset content"
    dataset["dataset_extension"] = {
        "raw_path": "/private/workbuddy/data.json",
        "owner": "untrusted-producer",
    }
    payload["summary"] = {
        "source_path": "/another/private/path.json",
        "raw_records": "do not copy",
    }
    payload["warnings"] = ["warning body must not be copied"]
    input_mapping = json.loads(_raw(payload))
    original_input = copy.deepcopy(input_mapping)
    request = DataRequest.from_mapping(request_payload)

    result = decode_and_validate_data_bundle(request, _raw(payload))

    assert input_mapping == original_input
    assert result.lineage == {
        "request_id": "codec-minimal-001",
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": (
            {
                "dataset_key": "sector-ranking",
                "sample_count": 1,
                "fields": ("sector_code", "change_percent"),
                "pagination_complete": True,
                "attempts": (
                    {
                        "connector": "tdx-connector",
                        "tool": "get_sector_ranking",
                        "status": "failed",
                        "error_code": "UPSTREAM_TIMEOUT",
                    },
                    {
                        "connector": "westock-mcp",
                        "tool": "get_sector_ranking_fallback",
                        "status": "succeeded",
                        "error_code": None,
                    },
                ),
            },
        ),
    }
    assert type(result.lineage) is MappingProxyType
    dataset_lineage = result.lineage["datasets"][0]
    attempt_lineage = dataset_lineage["attempts"][0]
    assert type(dataset_lineage) is type(result.lineage)
    assert type(attempt_lineage) is type(result.lineage)
    with pytest.raises(TypeError):
        result.lineage["stage"] = "stock_screening"
    with pytest.raises(TypeError):
        dataset_lineage["sample_count"] = 0
    with pytest.raises(TypeError):
        attempt_lineage["error_code"] = "NO_DATA"
