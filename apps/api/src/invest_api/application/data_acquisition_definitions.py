"""Verified reader for the two deployment-owned acquisition definitions."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

_SCHEMA_VERSION = "data-acquisition-definition/1.0"
_OUTPUT_CONTRACT = "workbuddy-data-bundle/1.0"


@dataclass(frozen=True, slots=True)
class _CatalogEntry:
    relative_path: str
    artifact_hash: str
    definition_version: str


_CATALOG = {
    "sector-strength-ranking": _CatalogEntry(
        relative_path="sector-strength-ranking/1.0.0.json",
        artifact_hash="4c3cc562b2711f5108ec6b1c225ef374e5eeb2b7d37730cf56cbbbd8bcd8143d",
        definition_version="1.0.0",
    ),
    "tdx-native-tools-stock-screening": _CatalogEntry(
        relative_path="tdx-native-tools-stock-screening/1.0.0.json",
        artifact_hash="6fd0a78e97cc65cbedaae0376b2daacb28f8210ee53b27f136aaae418402cd2c",
        definition_version="1.0.0",
    ),
}


class DataAcquisitionDefinitionNotFoundError(LookupError):
    def __init__(self, definition_key: str) -> None:
        self.definition_key = definition_key
        super().__init__("data acquisition definition not found")


class DataAcquisitionDefinitionArtifactReadError(RuntimeError):
    """The catalogued artifact could not be read."""


class DataAcquisitionDefinitionArtifactHashMismatchError(RuntimeError):
    """The artifact bytes do not match the reviewed catalog hash."""


class DataAcquisitionDefinitionArtifactDecodeError(RuntimeError):
    """The artifact is not a UTF-8 encoded JSON object."""


class DataAcquisitionDefinitionArtifactIdentityError(RuntimeError):
    """The artifact identity does not agree with its catalog entry."""


@dataclass(frozen=True, slots=True)
class DataAcquisitionDefinitionView:
    schema_version: str
    definition_key: str
    definition_version: str
    active: bool
    artifact_hash: str
    allowed_connectors: tuple[str, ...]
    data_request_template: Mapping[str, Any]
    output_contract: str


class _FrozenMapping(Mapping[str, Any]):
    __slots__ = ("_value",)

    def __init__(self, value: dict[str, Any]) -> None:
        object.__setattr__(
            self,
            "_value",
            MappingProxyType({key: _freeze(item) for key, item in value.items()}),
        )

    def __setattr__(self, name: str, value: Any) -> None:
        del name, value
        raise AttributeError("frozen mapping is immutable")

    def __getitem__(self, key: str) -> Any:
        return self._value[key]

    def __iter__(self):
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return {key: _thaw(item, memo) for key, item in self._value.items()}


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenMapping(value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any, memo: dict[int, Any]) -> Any:
    if isinstance(value, _FrozenMapping):
        return value.__deepcopy__(memo)
    if isinstance(value, tuple):
        return [_thaw(item, memo) for item in value]
    return copy.deepcopy(value, memo)


def _resolve_catalog_path(reader_root: Path, relative_path: str) -> Path:
    if type(relative_path) is not str or "\\" in relative_path:
        raise DataAcquisitionDefinitionArtifactIdentityError(
            "data acquisition definition identity mismatch"
        )

    posix_path = PurePosixPath(relative_path)
    if (
        not relative_path
        or posix_path.is_absolute()
        or PureWindowsPath(relative_path).is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        or posix_path.as_posix() != relative_path
    ):
        raise DataAcquisitionDefinitionArtifactIdentityError(
            "data acquisition definition identity mismatch"
        )

    try:
        resolved_root = reader_root.resolve()
        artifact_path = (resolved_root / relative_path).resolve()
    except (OSError, RuntimeError):
        raise DataAcquisitionDefinitionArtifactIdentityError(
            "data acquisition definition identity mismatch"
        ) from None
    if not artifact_path.is_relative_to(resolved_root):
        raise DataAcquisitionDefinitionArtifactIdentityError(
            "data acquisition definition identity mismatch"
        )
    return artifact_path


def _has_valid_authority(
    artifact: dict[str, Any],
    template: dict[str, Any],
    definition_key: str,
    definition_version: str,
) -> bool:
    strategy_ref = artifact.get("strategy_ref")
    outer_connectors = artifact.get("allowed_connectors")
    datasets = template.get("datasets")
    if (
        type(artifact.get("stage")) is not str
        or type(template.get("stage")) is not str
        or not artifact["stage"]
        or artifact["stage"] != template["stage"]
        or type(strategy_ref) is not dict
        or set(strategy_ref) != {
            "strategy_key",
            "strategy_version",
            "strategy_artifact_hash",
        }
        or any(type(value) is not str or not value for value in strategy_ref.values())
        or any(
            type(template.get(field)) is not str
            or not template[field]
            or template[field] != strategy_ref[field]
            for field in strategy_ref
        )
        or type(outer_connectors) is not list
        or not outer_connectors
        or any(
            type(connector) is not str or not connector
            for connector in outer_connectors
        )
        or len(outer_connectors) != len(set(outer_connectors))
        or type(datasets) is not list
        or not datasets
        or type(artifact.get("output_contract")) is not str
        or type(template.get("output_contract")) is not str
        or artifact["output_contract"] != _OUTPUT_CONTRACT
        or template["output_contract"] != artifact["output_contract"]
    ):
        return False

    dataset_connector_union: set[str] = set()
    for dataset in datasets:
        if type(dataset) is not dict:
            return False
        dataset_connectors = dataset.get("allowed_connectors")
        if (
            type(dataset_connectors) is not list
            or not dataset_connectors
            or any(
                type(connector) is not str or not connector
                for connector in dataset_connectors
            )
            or len(dataset_connectors) != len(set(dataset_connectors))
        ):
            return False
        dataset_connector_union.update(dataset_connectors)

    return (
        set(outer_connectors) == dataset_connector_union
        and artifact.get("schema_version") == _SCHEMA_VERSION
        and artifact.get("definition_key") == definition_key
        and artifact.get("definition_version") == definition_version
        and template.get("definition_key") == definition_key
        and template.get("definition_version") == definition_version
    )


class DataAcquisitionDefinitionQueryService:
    def __init__(self, *, reader_root: Path | None = None) -> None:
        default_root = (
            Path(__file__).resolve().parents[5]
            / "config"
            / "data-acquisition-definitions"
        )
        self._reader_root = reader_root or default_root

    def get_active(self, definition_key: str) -> DataAcquisitionDefinitionView:
        entry = _CATALOG.get(definition_key)
        if entry is None:
            raise DataAcquisitionDefinitionNotFoundError(definition_key)

        artifact_path = _resolve_catalog_path(self._reader_root, entry.relative_path)
        try:
            raw_bytes = artifact_path.read_bytes()
        except FileNotFoundError:
            raise DataAcquisitionDefinitionNotFoundError(definition_key) from None
        except OSError:
            raise DataAcquisitionDefinitionArtifactReadError(
                "data acquisition definition is unavailable"
            ) from None

        if hashlib.sha256(raw_bytes).hexdigest() != entry.artifact_hash:
            raise DataAcquisitionDefinitionArtifactHashMismatchError(
                "data acquisition definition hash mismatch"
            )

        try:
            artifact = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise DataAcquisitionDefinitionArtifactDecodeError(
                "data acquisition definition is not a UTF-8 JSON object"
            ) from None
        if not isinstance(artifact, dict):
            raise DataAcquisitionDefinitionArtifactDecodeError(
                "data acquisition definition is not a UTF-8 JSON object"
            )

        template = artifact.get("data_request_template")
        if (
            type(template) is not dict
            or not _has_valid_authority(
                artifact, template, definition_key, entry.definition_version
            )
        ):
            raise DataAcquisitionDefinitionArtifactIdentityError(
                "data acquisition definition identity mismatch"
            )

        return DataAcquisitionDefinitionView(
            schema_version=_SCHEMA_VERSION,
            definition_key=definition_key,
            definition_version=entry.definition_version,
            active=True,
            artifact_hash=entry.artifact_hash,
            allowed_connectors=tuple(artifact["allowed_connectors"]),
            data_request_template=_freeze(template),
            output_contract=_OUTPUT_CONTRACT,
        )


__all__ = [
    "DataAcquisitionDefinitionArtifactDecodeError",
    "DataAcquisitionDefinitionArtifactHashMismatchError",
    "DataAcquisitionDefinitionArtifactIdentityError",
    "DataAcquisitionDefinitionArtifactReadError",
    "DataAcquisitionDefinitionNotFoundError",
    "DataAcquisitionDefinitionQueryService",
    "DataAcquisitionDefinitionView",
]
