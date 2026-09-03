from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from invest_domain import canonical_json
from invest_domain.strategy import DataBundle, DataRequest, validate_data_bundle_for_evaluation

_INVALID_ARGUMENT_TYPES_CODE = "invalid_argument_types"
_INVALID_ARGUMENT_TYPES_MESSAGE = (
    "Data bundle request must be a DataRequest and raw payload must be bytes."
)
_INVALID_UTF8_CODE = "invalid_utf8"
_INVALID_UTF8_MESSAGE = "Data bundle payload is not valid UTF-8."
_INVALID_JSON_CODE = "invalid_json"
_INVALID_JSON_MESSAGE = "Data bundle payload is not valid JSON."
_JSON_OBJECT_CODE = "json_root_not_object"
_JSON_OBJECT_MESSAGE = "Data bundle payload must be a JSON object."
_FORBIDDEN_SENSITIVE_KEY_CODE = "forbidden_sensitive_key"
_FORBIDDEN_SENSITIVE_KEY_MESSAGE = "Data bundle payload contains a forbidden sensitive key."
_INVALID_BUNDLE_CODE = "invalid_data_bundle"
_INVALID_BUNDLE_MESSAGE = "Data bundle payload does not satisfy the data bundle contract."
_REQUEST_IDENTITY_CODE = "request_identity_mismatch"
_REQUEST_IDENTITY_MESSAGE = "Data bundle request identity does not match the request."
_STALE_DELIVERY_CODE = "stale_delivery"
_STALE_DELIVERY_MESSAGE = "Data bundle delivery is stale."
_ACQUISITION_ERRORS_CODE = "acquisition_errors"
_ACQUISITION_ERRORS_MESSAGE = "Data bundle reports acquisition errors."
_CONNECTOR_PREFIX_CODE = "connector_prefix_mismatch"
_CONNECTOR_PREFIX_MESSAGE = "Data bundle connector fallback sequence is invalid."
_VALIDATION_FAILED_CODE = "evaluation_validation_failed"
_VALIDATION_FAILED_MESSAGE = "Data bundle failed evaluation validation."
_UNEXPECTED_DECODE_CODE = "codec_decode_failure"
_UNEXPECTED_DECODE_MESSAGE = "Data bundle payload could not be decoded safely."


class _DataBundleCodecError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DataBundleDecodeError(_DataBundleCodecError):
    pass


class DataBundleValidationError(_DataBundleCodecError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedDataBundle:
    bundle: DataBundle
    raw_sha256: str
    canonical_bytes: bytes
    canonical_sha256: str
    lineage: Mapping[str, Any]


class _DuplicateJsonKey(ValueError):
    pass


class _InvalidJsonConstant(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise _InvalidJsonConstant(value)


def _to_domain_input(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        projected = float(value)
        if not math.isfinite(projected) or (value != 0 and projected == 0):
            raise ValueError
        return projected
    if isinstance(value, list):
        return [_to_domain_input(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _to_domain_input(item)
            for key, item in value.items()
        }
    raise TypeError


def _freeze_lineage(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_lineage(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_lineage(item) for item in value)
    return value


def _build_lineage(request: DataRequest, bundle: DataBundle) -> Mapping[str, Any]:
    datasets = tuple(
        {
            "dataset_key": dataset.dataset_key,
            "sample_count": dataset.sample_count,
            "fields": dataset.fields,
            "pagination_complete": dataset.pagination.complete,
            "attempts": tuple(
                {
                    "connector": attempt.connector,
                    "tool": attempt.tool,
                    "status": attempt.status,
                    "error_code": attempt.error_code,
                }
                for attempt in dataset.attempts
            ),
        }
        for dataset in bundle.datasets
    )
    return _freeze_lineage(
        {
            "request_id": request.request_id,
            "definition_key": request.definition_key,
            "definition_version": request.definition_version,
            "strategy_key": request.strategy_key,
            "strategy_version": request.strategy_version,
            "strategy_artifact_hash": request.strategy_artifact_hash,
            "stage": request.stage,
            "producer": bundle.producer,
            "generated_at": bundle.generated_at.isoformat(),
            "datasets": datasets,
        }
    )


def _parse_bundle(raw_bytes: bytes) -> tuple[DataBundle, bytes, str]:
    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass
    else:
        try:
            payload = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
                parse_float=Decimal,
                parse_constant=_reject_json_constant,
            )
        except (
            json.JSONDecodeError,
            _DuplicateJsonKey,
            _InvalidJsonConstant,
            RecursionError,
        ):
            pass
        else:
            if not isinstance(payload, dict):
                raise DataBundleDecodeError(_JSON_OBJECT_CODE, _JSON_OBJECT_MESSAGE)
            try:
                domain_payload = _to_domain_input(payload)
                bundle = DataBundle.from_mapping(domain_payload)
                canonical = canonical_json(payload).encode("utf-8")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                code = (
                    _FORBIDDEN_SENSITIVE_KEY_CODE
                    if exc.args == ("DataBundle contains a forbidden credential key",)
                    else _INVALID_BUNDLE_CODE
                )
                message = (
                    _FORBIDDEN_SENSITIVE_KEY_MESSAGE
                    if code == _FORBIDDEN_SENSITIVE_KEY_CODE
                    else _INVALID_BUNDLE_MESSAGE
                )
            else:
                return bundle, canonical, hashlib.sha256(canonical).hexdigest()
            raise DataBundleDecodeError(code, message) from None
        raise DataBundleDecodeError(_INVALID_JSON_CODE, _INVALID_JSON_MESSAGE) from None
    raise DataBundleDecodeError(_INVALID_UTF8_CODE, _INVALID_UTF8_MESSAGE) from None


def _validation_code(exc: Exception) -> str:
    if exc.args == ("DataBundle request identity does not match DataRequest",):
        return _REQUEST_IDENTITY_CODE
    if exc.args in {
        ("DataBundle generated_at precedes DataRequest as_of",),
        ("DataBundle delivery exceeds max_delivery_lag_days",),
    }:
        return _STALE_DELIVERY_CODE
    if exc.args == ("DataBundle reports acquisition errors",):
        return _ACQUISITION_ERRORS_CODE
    if exc.args == (
        "DataBundle attempt connectors must match the allowed connector prefix",
    ):
        return _CONNECTOR_PREFIX_CODE
    return _VALIDATION_FAILED_CODE


def _validation_message(code: str) -> str:
    return {
        _REQUEST_IDENTITY_CODE: _REQUEST_IDENTITY_MESSAGE,
        _STALE_DELIVERY_CODE: _STALE_DELIVERY_MESSAGE,
        _ACQUISITION_ERRORS_CODE: _ACQUISITION_ERRORS_MESSAGE,
        _CONNECTOR_PREFIX_CODE: _CONNECTOR_PREFIX_MESSAGE,
    }.get(code, _VALIDATION_FAILED_MESSAGE)


def decode_and_validate_data_bundle(
    request: DataRequest,
    raw_bytes: bytes,
) -> ValidatedDataBundle:
    if not isinstance(request, DataRequest) or not isinstance(raw_bytes, bytes):
        raise DataBundleDecodeError(
            _INVALID_ARGUMENT_TYPES_CODE,
            _INVALID_ARGUMENT_TYPES_MESSAGE,
        )
    try:
        bundle, canonical_bytes, canonical_sha256 = _parse_bundle(raw_bytes)
    except DataBundleDecodeError:
        raise
    except Exception:
        pass
    else:
        try:
            validate_data_bundle_for_evaluation(request, bundle)
        except (TypeError, ValueError) as exc:
            code = _validation_code(exc)
        else:
            return ValidatedDataBundle(
                bundle=bundle,
                raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                canonical_bytes=canonical_bytes,
                canonical_sha256=canonical_sha256,
                lineage=_build_lineage(request, bundle),
            )
        raise DataBundleValidationError(code, _validation_message(code)) from None
    raise DataBundleDecodeError(
        _UNEXPECTED_DECODE_CODE,
        _UNEXPECTED_DECODE_MESSAGE,
    ) from None


__all__ = [
    "DataBundleDecodeError",
    "DataBundleValidationError",
    "ValidatedDataBundle",
    "decode_and_validate_data_bundle",
]
