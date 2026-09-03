"""Public contract tests for the bounded static definition reader (Slice 1B)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from invest_api.application import data_acquisition_definitions as definitions
from invest_api.application.data_acquisition_definitions import (
    DataAcquisitionDefinitionArtifactDecodeError,
    DataAcquisitionDefinitionArtifactHashMismatchError,
    DataAcquisitionDefinitionArtifactIdentityError,
    DataAcquisitionDefinitionArtifactReadError,
    DataAcquisitionDefinitionNotFoundError,
    DataAcquisitionDefinitionQueryService,
    DataAcquisitionDefinitionView,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "config" / "data-acquisition-definitions"
APPROVED = {
    "sector-strength-ranking": (
        "sector-strength-ranking/1.0.0.json",
        "4c3cc562b2711f5108ec6b1c225ef374e5eeb2b7d37730cf56cbbbd8bcd8143d",
    ),
    "tdx-native-tools-stock-screening": (
        "tdx-native-tools-stock-screening/1.0.0.json",
        "6fd0a78e97cc65cbedaae0376b2daacb28f8210ee53b27f136aaae418402cd2c",
    ),
}


def _install_artifact(root: Path, relative_path: str) -> bytes:
    source_bytes = (SOURCE_ROOT / relative_path).read_bytes()
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source_bytes)
    return source_bytes


@pytest.mark.parametrize("definition_key", tuple(APPROVED))
def test_get_active_returns_verified_immutable_public_view(
    tmp_path: Path, definition_key: str
) -> None:
    relative_path, reviewed_hash = APPROVED[definition_key]
    source_bytes = _install_artifact(tmp_path, relative_path)

    view = DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
        definition_key
    )

    artifact = json.loads(source_bytes)
    assert isinstance(view, DataAcquisitionDefinitionView)
    assert set(DataAcquisitionDefinitionView.__dataclass_fields__) == {
        "schema_version",
        "definition_key",
        "definition_version",
        "active",
        "artifact_hash",
        "allowed_connectors",
        "data_request_template",
        "output_contract",
    }
    assert dataclasses.asdict(view) == {
        "schema_version": "data-acquisition-definition/1.0",
        "definition_key": definition_key,
        "definition_version": "1.0.0",
        "active": True,
        "artifact_hash": reviewed_hash,
        "allowed_connectors": tuple(artifact["allowed_connectors"]),
        "data_request_template": artifact["data_request_template"],
        "output_contract": "workbuddy-data-bundle/1.0",
    }
    with pytest.raises(FrozenInstanceError):
        view.active = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        view.data_request_template["definition_key"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        view.data_request_template["datasets"][0]["dataset_key"] = "changed"  # type: ignore[index]
    outer_mapping = view.data_request_template
    outer_storage = outer_mapping._value  # type: ignore[attr-defined]
    nested_mapping = outer_storage["datasets"][0]
    with pytest.raises(TypeError):
        outer_storage["definition_key"] = "changed"
    with pytest.raises(TypeError):
        nested_mapping._value["dataset_key"] = "changed"
    with pytest.raises(AttributeError):
        outer_mapping._value = {}  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        nested_mapping._value = {}


@pytest.mark.parametrize(
    "definition_key",
    ("unknown", "../sector-strength-ranking", "/etc/passwd", "sector/../../secret"),
)
def test_unknown_or_traversal_like_key_fails_before_filesystem_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, definition_key: str
) -> None:
    def unexpected_read(_path: Path) -> bytes:
        raise AssertionError("filesystem read must not be attempted")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    service = DataAcquisitionDefinitionQueryService(reader_root=tmp_path)

    with pytest.raises(DataAcquisitionDefinitionNotFoundError) as exc_info:
        service.get_active(definition_key)

    assert str(exc_info.value) == "data acquisition definition not found"
    assert exc_info.value.definition_key == definition_key


def test_missing_catalog_artifact_is_sanitized_not_found(tmp_path: Path) -> None:
    service = DataAcquisitionDefinitionQueryService(reader_root=tmp_path)

    with pytest.raises(DataAcquisitionDefinitionNotFoundError) as exc_info:
        service.get_active("sector-strength-ranking")

    assert str(exc_info.value) == "data acquisition definition not found"
    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.parametrize(
    "relative_path",
    (
        "",
        "/absolute/1.0.0.json",
        "sector-strength-ranking//1.0.0.json",
        "sector-strength-ranking/./1.0.0.json",
        "sector-strength-ranking/../1.0.0.json",
        "../outside.json",
        "sector-strength-ranking\\1.0.0.json",
    ),
    ids=(
        "empty",
        "absolute",
        "repeated-separator",
        "dot-component",
        "dot-dot-component",
        "outside-root",
        "backslash",
    ),
)
def test_invalid_catalog_path_fails_identity_before_reading_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    monkeypatch.setitem(
        definitions._CATALOG,
        "sector-strength-ranking",
        definitions._CatalogEntry(
            relative_path=relative_path,
            artifact_hash="0" * 64,
            definition_version="1.0.0",
        ),
    )

    def unexpected_read(_path: Path) -> bytes:
        raise AssertionError("artifact bytes must not be read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)

    with pytest.raises(DataAcquisitionDefinitionArtifactIdentityError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            "sector-strength-ranking"
        )

    assert str(exc_info.value) == "data acquisition definition identity mismatch"
    assert str(tmp_path) not in str(exc_info.value)


def test_catalog_symlink_escape_fails_identity_before_reading_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path.parent / "outside-artifacts"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    monkeypatch.setitem(
        definitions._CATALOG,
        "sector-strength-ranking",
        definitions._CatalogEntry(
            relative_path="escape/1.0.0.json",
            artifact_hash="0" * 64,
            definition_version="1.0.0",
        ),
    )

    def unexpected_read(_path: Path) -> bytes:
        raise AssertionError("artifact bytes must not be read")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)

    with pytest.raises(DataAcquisitionDefinitionArtifactIdentityError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            "sector-strength-ranking"
        )

    assert str(exc_info.value) == "data acquisition definition identity mismatch"
    assert str(tmp_path) not in str(exc_info.value)


def test_unavailable_artifact_is_sanitized_read_error(tmp_path: Path) -> None:
    root_that_is_not_a_directory = tmp_path / "artifact-root"
    root_that_is_not_a_directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(DataAcquisitionDefinitionArtifactReadError) as exc_info:
        DataAcquisitionDefinitionQueryService(
            reader_root=root_that_is_not_a_directory
        ).get_active("sector-strength-ranking")

    assert str(exc_info.value) == "data acquisition definition is unavailable"
    assert str(tmp_path) not in str(exc_info.value)
    assert "Not a directory" not in str(exc_info.value)


def test_byte_tampering_fails_hash_check(tmp_path: Path) -> None:
    relative_path, _ = APPROVED["sector-strength-ranking"]
    _install_artifact(tmp_path, relative_path)
    (tmp_path / relative_path).write_bytes(b'{}')

    with pytest.raises(DataAcquisitionDefinitionArtifactHashMismatchError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            "sector-strength-ranking"
        )

    assert str(exc_info.value) == "data acquisition definition hash mismatch"
    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_bytes",
    (b"\xff", b"{not-json", b"[]", b'"text"', b"null"),
    ids=("invalid-utf8", "invalid-json", "array", "string", "null"),
)
def test_invalid_utf8_json_or_non_object_raises_decode_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_bytes: bytes
) -> None:
    relative_path, _ = APPROVED["sector-strength-ranking"]
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True)
    destination.write_bytes(bad_bytes)
    entry = definitions._CatalogEntry(
        relative_path=relative_path,
        artifact_hash=hashlib.sha256(bad_bytes).hexdigest(),
        definition_version="1.0.0",
    )
    monkeypatch.setitem(definitions._CATALOG, "sector-strength-ranking", entry)

    with pytest.raises(DataAcquisitionDefinitionArtifactDecodeError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            "sector-strength-ranking"
        )

    assert str(exc_info.value) == "data acquisition definition is not a UTF-8 JSON object"
    assert str(tmp_path) not in str(exc_info.value)
    assert repr(bad_bytes) not in str(exc_info.value)


@pytest.mark.parametrize(
    ("mutation", "case_id"),
    (
        ({"schema_version": "data-acquisition-definition/2.0"}, "schema"),
        ({"definition_key": "other-definition"}, "definition-key"),
        ({"definition_version": "9.9.9"}, "definition-version"),
        ({"template_definition_key": "other-definition"}, "template-key"),
        ({"template_definition_version": "9.9.9"}, "template-version"),
    ),
)
def test_catalog_and_artifact_identity_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, str],
    case_id: str,
) -> None:
    del case_id
    relative_path, _ = APPROVED["sector-strength-ranking"]
    artifact: dict[str, Any] = json.loads((SOURCE_ROOT / relative_path).read_bytes())
    if "template_definition_key" in mutation:
        artifact["data_request_template"]["definition_key"] = mutation[
            "template_definition_key"
        ]
    elif "template_definition_version" in mutation:
        artifact["data_request_template"]["definition_version"] = mutation[
            "template_definition_version"
        ]
    else:
        artifact.update(mutation)
    altered_bytes = json.dumps(artifact).encode("utf-8")
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True)
    destination.write_bytes(altered_bytes)
    monkeypatch.setitem(
        definitions._CATALOG,
        "sector-strength-ranking",
        definitions._CatalogEntry(
            relative_path=relative_path,
            artifact_hash=hashlib.sha256(altered_bytes).hexdigest(),
            definition_version="1.0.0",
        ),
    )

    with pytest.raises(DataAcquisitionDefinitionArtifactIdentityError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            "sector-strength-ranking"
        )

    assert str(exc_info.value) == "data acquisition definition identity mismatch"
    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.parametrize(
    "case_id",
    (
        "outer-stage-shape",
        "template-stage-shape",
        "stage-empty",
        "stage-mismatch",
        "strategy-ref-shape",
        "strategy-ref-missing-field",
        "strategy-ref-extra-field",
        "strategy-ref-field-shape",
        "strategy-field-empty",
        "template-strategy-field-shape",
        "strategy-key-mismatch",
        "strategy-version-mismatch",
        "strategy-hash-mismatch",
        "outer-connectors-shape",
        "outer-connector-scalar-shape",
        "connector-empty",
        "outer-connectors-empty",
        "outer-connectors-duplicate",
        "datasets-shape",
        "dataset-shape",
        "dataset-connectors-shape",
        "dataset-connector-scalar-shape",
        "dataset-connectors-empty",
        "dataset-connectors-duplicate",
        "outer-connectors-missing-dataset-union-member",
        "outer-connectors-extra-union-member",
        "outer-output-contract-shape",
        "template-output-contract-shape",
        "outer-output-contract-mismatch",
        "template-output-contract-mismatch",
    ),
)
def test_artifact_authority_contradictions_and_malformed_shapes_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    definition_key = "sector-strength-ranking"
    relative_path, _ = APPROVED[definition_key]
    artifact: dict[str, Any] = json.loads((SOURCE_ROOT / relative_path).read_bytes())
    template = artifact["data_request_template"]
    first_dataset = template["datasets"][0]

    if case_id == "outer-stage-shape":
        artifact["stage"] = [artifact["stage"]]
    elif case_id == "template-stage-shape":
        template["stage"] = [template["stage"]]
    elif case_id == "stage-empty":
        artifact["stage"] = template["stage"] = ""
    elif case_id == "stage-mismatch":
        template["stage"] = "stock_screening"
    elif case_id == "strategy-ref-shape":
        artifact["strategy_ref"] = []
    elif case_id == "strategy-ref-missing-field":
        del artifact["strategy_ref"]["strategy_artifact_hash"]
    elif case_id == "strategy-ref-extra-field":
        artifact["strategy_ref"]["extra"] = "ambiguous"
    elif case_id == "strategy-ref-field-shape":
        artifact["strategy_ref"]["strategy_version"] = ["2.0.0"]
    elif case_id == "strategy-field-empty":
        artifact["strategy_ref"]["strategy_version"] = ""
        template["strategy_version"] = ""
    elif case_id == "template-strategy-field-shape":
        template["strategy_version"] = ["2.0.0"]
    elif case_id == "strategy-key-mismatch":
        template["strategy_key"] = "other-strategy"
    elif case_id == "strategy-version-mismatch":
        template["strategy_version"] = "9.9.9"
    elif case_id == "strategy-hash-mismatch":
        template["strategy_artifact_hash"] = "0" * 64
    elif case_id == "outer-connectors-shape":
        artifact["allowed_connectors"] = {}
    elif case_id == "outer-connector-scalar-shape":
        artifact["allowed_connectors"][0] = 1
    elif case_id == "connector-empty":
        connector = artifact["allowed_connectors"][0]
        artifact["allowed_connectors"][0] = ""
        for dataset in template["datasets"]:
            dataset["allowed_connectors"] = [
                "" if value == connector else value
                for value in dataset["allowed_connectors"]
            ]
    elif case_id == "outer-connectors-empty":
        artifact["allowed_connectors"] = []
    elif case_id == "outer-connectors-duplicate":
        artifact["allowed_connectors"].append(artifact["allowed_connectors"][0])
    elif case_id == "datasets-shape":
        template["datasets"] = {}
    elif case_id == "dataset-shape":
        template["datasets"][0] = []
    elif case_id == "dataset-connectors-shape":
        first_dataset["allowed_connectors"] = {}
    elif case_id == "dataset-connector-scalar-shape":
        first_dataset["allowed_connectors"][0] = 1
    elif case_id == "dataset-connectors-empty":
        first_dataset["allowed_connectors"] = []
    elif case_id == "dataset-connectors-duplicate":
        first_dataset["allowed_connectors"].append(
            first_dataset["allowed_connectors"][0]
        )
    elif case_id == "outer-connectors-missing-dataset-union-member":
        artifact["allowed_connectors"] = [artifact["allowed_connectors"][0]]
    elif case_id == "outer-connectors-extra-union-member":
        artifact["allowed_connectors"].append("undeclared-connector")
    elif case_id == "outer-output-contract-shape":
        artifact["output_contract"] = [artifact["output_contract"]]
    elif case_id == "template-output-contract-shape":
        template["output_contract"] = [template["output_contract"]]
    elif case_id == "outer-output-contract-mismatch":
        artifact["output_contract"] = "other-contract/1.0"
    elif case_id == "template-output-contract-mismatch":
        template["output_contract"] = "other-contract/1.0"
    else:  # pragma: no cover - keeps the mutation table exhaustive
        raise AssertionError(f"unhandled mutation: {case_id}")

    altered_bytes = json.dumps(artifact).encode("utf-8")
    destination = tmp_path / relative_path
    destination.parent.mkdir(parents=True)
    destination.write_bytes(altered_bytes)
    monkeypatch.setitem(
        definitions._CATALOG,
        definition_key,
        definitions._CatalogEntry(
            relative_path=relative_path,
            artifact_hash=hashlib.sha256(altered_bytes).hexdigest(),
            definition_version="1.0.0",
        ),
    )

    with pytest.raises(DataAcquisitionDefinitionArtifactIdentityError) as exc_info:
        DataAcquisitionDefinitionQueryService(reader_root=tmp_path).get_active(
            definition_key
        )

    assert str(exc_info.value) == "data acquisition definition identity mismatch"
    assert str(tmp_path) not in str(exc_info.value)


def test_catalog_is_exactly_the_two_reviewed_artifacts() -> None:
    assert {
        key: (entry.relative_path, entry.artifact_hash)
        for key, entry in definitions._CATALOG.items()
    } == APPROVED
