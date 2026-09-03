"""Immutable contracts for WorkBuddy data acquisition payloads."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

DATA_REQUEST_SCHEMA_VERSION = "workbuddy-data-request/1.0"
DATA_BUNDLE_SCHEMA_VERSION = "workbuddy-data-bundle/1.0"
APPROVED_DATA_CONNECTORS = frozenset(
    {"tdx-connector", "westock-mcp", "mx-ds-mcp"}
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_STAGES = frozenset({"sector_selection", "stock_screening"})
_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "definition_key",
        "definition_version",
        "strategy_key",
        "strategy_version",
        "strategy_artifact_hash",
        "stage",
        "as_of",
        "max_delivery_lag_days",
        "datasets",
        "output_contract",
    }
)
_REQUEST_DATASET_FIELDS = frozenset(
    {"dataset_key", "required_fields", "allowed_connectors"}
)
_BUNDLE_FIELDS = frozenset(
    {"schema_version", "request_id", "producer", "generated_at", "datasets", "warnings", "errors"}
)
_BUNDLE_DATASET_FIELDS = frozenset(
    {
        "dataset_key",
        "connector",
        "tool",
        "parameters",
        "as_of",
        "pagination",
        "sample_count",
        "fields",
        "units",
        "records",
    }
)
_SENSITIVE_KEY_TOKENS = frozenset(
    {"secret", "token", "password", "authorization", "credential", "credentials"}
)
_SENSITIVE_KEY_PAIRS = frozenset(
    {("api", "key"), ("access", "token"), ("refresh", "token"), ("private", "key")}
)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{name} keys must be strings")
    return value


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], name: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} fields are invalid")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")
    return value.strip()


def _safe_id(value: Any, name: str) -> str:
    result = _text(value, name)
    if _SAFE_ID.fullmatch(result) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return result


def _request_id(value: Any) -> str:
    result = _text(value, "request_id")
    if _REQUEST_ID.fullmatch(result) is None:
        raise ValueError("request_id is not a safe artifact identity")
    return result


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 string")
    return value


def _date(value: Any, name: str) -> date:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO date string")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid ISO date") from exc
    if result.isoformat() != value:
        raise ValueError(f"{name} must be a valid ISO date")
    return result


def _delivery_lag_days(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 7:
        raise ValueError("max_delivery_lag_days must be an integer from 0 through 7")
    return value


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of strings")
    result = tuple(_text(item, f"{name} item") for item in value)
    if not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _safe_id_tuple(value: Any, name: str) -> tuple[str, ...]:
    items = _string_tuple(value, name)
    return tuple(_safe_id(item, f"{name} item") for item in items)


def _freeze_json(value: Any, name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{name} object keys must be strings")
            frozen[key] = _freeze_json(item, name)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item, name) for item in value)
    raise TypeError(f"{name} must contain only JSON-compatible values")


def _aware_datetime(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid ISO datetime") from exc
    else:
        raise TypeError(f"{name} must be a datetime or ISO datetime string")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result


def _json_sequence(value: Any, name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence")
    return tuple(_freeze_json(item, name) for item in value)


def _is_sensitive_key(key: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    tokens = tuple(part for part in re.split(r"[^A-Za-z0-9]+", separated.lower()) if part)
    if any(token in _SENSITIVE_KEY_TOKENS for token in tokens):
        return True
    if "apikey" in tokens or "accesstoken" in tokens or "refreshtoken" in tokens:
        return True
    return any(pair in zip(tokens, tokens[1:], strict=False) for pair in _SENSITIVE_KEY_PAIRS)


def _has_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_sensitive_key(str(key)) or _has_sensitive_key(item):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_has_sensitive_key(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class _DataRequestDataset:
    dataset_key: str
    required_fields: tuple[str, ...]
    allowed_connectors: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> _DataRequestDataset:
        data = _mapping(payload, "DataRequest dataset")
        _require_exact_fields(data, _REQUEST_DATASET_FIELDS, "DataRequest dataset")
        allowed_connectors = _safe_id_tuple(
            data.get("allowed_connectors"), "allowed_connectors"
        )
        if not set(allowed_connectors).issubset(APPROVED_DATA_CONNECTORS):
            raise ValueError("allowed_connectors contains an unapproved connector")
        return cls(
            dataset_key=_safe_id(data.get("dataset_key"), "dataset_key"),
            required_fields=_string_tuple(data.get("required_fields"), "required_fields"),
            allowed_connectors=allowed_connectors,
        )


@dataclass(frozen=True, slots=True)
class DataRequest:
    schema_version: str
    request_id: str
    definition_key: str
    definition_version: str
    strategy_key: str
    strategy_version: str
    strategy_artifact_hash: str
    stage: str
    as_of: date
    max_delivery_lag_days: int
    datasets: tuple[_DataRequestDataset, ...]
    output_contract: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DataRequest:
        data = _mapping(payload, "DataRequest")
        _require_exact_fields(data, _REQUEST_FIELDS, "DataRequest")
        schema_version = data.get("schema_version")
        if schema_version != DATA_REQUEST_SCHEMA_VERSION:
            raise ValueError("DataRequest.schema_version is unsupported")
        output_contract = data.get("output_contract")
        if output_contract != DATA_BUNDLE_SCHEMA_VERSION:
            raise ValueError("DataRequest.output_contract is unsupported")
        stage = data.get("stage")
        if stage not in _STAGES:
            raise ValueError("DataRequest.stage is unsupported")
        raw_datasets = data.get("datasets")
        if not isinstance(raw_datasets, Sequence) or isinstance(
            raw_datasets, (str, bytes, bytearray)
        ):
            raise TypeError("DataRequest.datasets must be a sequence")
        datasets = tuple(_DataRequestDataset.from_mapping(item) for item in raw_datasets)
        if not datasets:
            raise ValueError("DataRequest.datasets must not be empty")
        dataset_keys = tuple(item.dataset_key for item in datasets)
        if len(set(dataset_keys)) != len(dataset_keys):
            raise ValueError("DataRequest.datasets contains duplicate dataset_key")
        return cls(
            schema_version=schema_version,
            request_id=_request_id(data.get("request_id")),
            definition_key=_safe_id(data.get("definition_key"), "definition_key"),
            definition_version=_safe_id(
                data.get("definition_version"), "definition_version"
            ),
            strategy_key=_safe_id(data.get("strategy_key"), "strategy_key"),
            strategy_version=_safe_id(data.get("strategy_version"), "strategy_version"),
            strategy_artifact_hash=_sha256(
                data.get("strategy_artifact_hash"), "strategy_artifact_hash"
            ),
            stage=stage,
            as_of=_date(data.get("as_of"), "as_of"),
            max_delivery_lag_days=_delivery_lag_days(
                data.get("max_delivery_lag_days")
            ),
            datasets=datasets,
            output_contract=output_contract,
        )


@dataclass(frozen=True, slots=True)
class _DataBundlePagination:
    complete: bool
    extensions: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> _DataBundlePagination:
        data = _mapping(payload, "DataBundle pagination")
        if "complete" not in data:
            raise ValueError("DataBundle pagination fields are invalid")
        if not isinstance(data["complete"], bool):
            raise TypeError("DataBundle pagination.complete must be a boolean")
        extensions = {
            key: _freeze_json(value, "DataBundle pagination extensions")
            for key, value in data.items()
            if key != "complete"
        }
        return cls(
            complete=data["complete"],
            extensions=MappingProxyType(extensions),
        )


@dataclass(frozen=True, slots=True)
class _DataBundleDataset:
    dataset_key: str
    connector: str
    tool: str
    parameters: Mapping[str, Any]
    as_of: date
    pagination: _DataBundlePagination
    sample_count: int
    fields: tuple[str, ...]
    units: Mapping[str, Any]
    records: tuple[Mapping[str, Any], ...]
    extensions: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> _DataBundleDataset:
        data = _mapping(payload, "DataBundle dataset")
        missing = _BUNDLE_DATASET_FIELDS.difference(data)
        if missing:
            raise ValueError("DataBundle dataset fields are invalid")
        parameters = _mapping(data["parameters"], "DataBundle dataset parameters")
        units = _mapping(data["units"], "DataBundle dataset units")
        raw_records = data["records"]
        if not isinstance(raw_records, Sequence) or isinstance(
            raw_records, (str, bytes, bytearray)
        ):
            raise TypeError("DataBundle dataset records must be a sequence")
        records: list[Mapping[str, Any]] = []
        for item in raw_records:
            frozen = _freeze_json(_mapping(item, "DataBundle dataset record"), "records")
            records.append(frozen)
        sample_count = data["sample_count"]
        if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 0:
            raise ValueError("DataBundle dataset sample_count must be a non-negative integer")
        extensions = {
            key: _freeze_json(value, "DataBundle dataset extensions")
            for key, value in data.items()
            if key not in _BUNDLE_DATASET_FIELDS
        }
        frozen_parameters = _freeze_json(parameters, "DataBundle dataset parameters")
        frozen_units = _freeze_json(units, "DataBundle dataset units")
        connector = _safe_id(data["connector"], "connector")
        if connector not in APPROVED_DATA_CONNECTORS:
            raise ValueError("connector is not approved")
        return cls(
            dataset_key=_safe_id(data["dataset_key"], "dataset_key"),
            connector=connector,
            tool=_safe_id(data["tool"], "tool"),
            parameters=frozen_parameters,
            as_of=_date(data["as_of"], "as_of"),
            pagination=_DataBundlePagination.from_mapping(data["pagination"]),
            sample_count=sample_count,
            fields=_string_tuple(data["fields"], "fields"),
            units=frozen_units,
            records=tuple(records),
            extensions=MappingProxyType(extensions),
        )


@dataclass(frozen=True, slots=True)
class DataBundle:
    schema_version: str
    request_id: str
    producer: str
    generated_at: datetime
    datasets: tuple[_DataBundleDataset, ...]
    warnings: tuple[Any, ...]
    errors: tuple[Any, ...]
    extensions: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DataBundle:
        data = _mapping(payload, "DataBundle")
        if _has_sensitive_key(data):
            raise ValueError("DataBundle contains a forbidden credential key")
        if _BUNDLE_FIELDS.difference(data):
            raise ValueError("DataBundle fields are invalid")
        if data["schema_version"] != DATA_BUNDLE_SCHEMA_VERSION:
            raise ValueError("DataBundle.schema_version is unsupported")
        if data["producer"] != "workbuddy":
            raise ValueError("DataBundle.producer is unsupported")
        raw_datasets = data["datasets"]
        if not isinstance(raw_datasets, Sequence) or isinstance(
            raw_datasets, (str, bytes, bytearray)
        ):
            raise TypeError("DataBundle.datasets must be a sequence")
        datasets = tuple(_DataBundleDataset.from_mapping(item) for item in raw_datasets)
        if not datasets:
            raise ValueError("DataBundle.datasets must not be empty")
        extensions = {
            key: _freeze_json(value, "DataBundle extensions")
            for key, value in data.items()
            if key not in _BUNDLE_FIELDS
        }
        return cls(
            schema_version=data["schema_version"],
            request_id=_request_id(data["request_id"]),
            producer=data["producer"],
            generated_at=_aware_datetime(data["generated_at"], "generated_at"),
            datasets=datasets,
            warnings=_json_sequence(data["warnings"], "warnings"),
            errors=_json_sequence(data["errors"], "errors"),
            extensions=MappingProxyType(extensions),
        )


def validate_data_bundle_for_evaluation(
    request: DataRequest, bundle: DataBundle
) -> None:
    """Fail closed unless ``bundle`` is safe input for ``request``'s evaluator."""

    if not isinstance(request, DataRequest) or not isinstance(bundle, DataBundle):
        raise TypeError("evaluation validation requires parsed contracts")
    if request.request_id != bundle.request_id:
        raise ValueError("DataBundle request identity does not match DataRequest")
    if bundle.errors:
        raise ValueError("DataBundle reports acquisition errors")
    delivery_date = bundle.generated_at.astimezone(UTC).date()
    if delivery_date < request.as_of:
        raise ValueError("DataBundle generated_at precedes DataRequest as_of")
    if (delivery_date - request.as_of).days > request.max_delivery_lag_days:
        raise ValueError("DataBundle delivery exceeds max_delivery_lag_days")

    bundle_keys = tuple(dataset.dataset_key for dataset in bundle.datasets)
    if len(set(bundle_keys)) != len(bundle_keys):
        raise ValueError("DataBundle contains a duplicate dataset_key")
    requested_by_key = {dataset.dataset_key: dataset for dataset in request.datasets}
    bundle_by_key = {dataset.dataset_key: dataset for dataset in bundle.datasets}
    if requested_by_key.keys() - bundle_by_key.keys():
        raise ValueError("DataBundle is missing a requested dataset")
    if bundle_by_key.keys() - requested_by_key.keys():
        raise ValueError("DataBundle contains an unrequested dataset")

    for dataset_key, requested in requested_by_key.items():
        delivered = bundle_by_key[dataset_key]
        if delivered.connector not in requested.allowed_connectors:
            raise ValueError("DataBundle dataset connector is not allowed")
        if delivered.as_of != request.as_of:
            raise ValueError("DataBundle dataset as_of does not match DataRequest")
        if not delivered.pagination.complete:
            raise ValueError("DataBundle dataset pagination is incomplete")
        if not set(requested.required_fields).issubset(delivered.fields):
            raise ValueError("DataBundle dataset is missing a required field")
        for record in delivered.records:
            if not set(requested.required_fields).issubset(record):
                raise ValueError("DataBundle record is missing a required field")
        if delivered.sample_count != len(delivered.records):
            raise ValueError("DataBundle dataset sample_count does not match records")


__all__ = [
    "APPROVED_DATA_CONNECTORS",
    "DataBundle",
    "DataRequest",
    "validate_data_bundle_for_evaluation",
]
