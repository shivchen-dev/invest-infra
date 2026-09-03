from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import traceback
from pathlib import Path

import pytest
from invest_domain.strategy import DataRequest
from invest_pipeline.integrations import workbuddy_data_bundle_archive as archive_module
from invest_pipeline.integrations.workbuddy_data_bundle_archive import (
    DataBundleArchiveConflictError,
    DataBundleArchiveIntegrityError,
    DataBundleArchiveIOError,
    DataBundleArchivePathError,
    archive_data_bundle,
)
from invest_pipeline.integrations.workbuddy_data_bundle_codec import DataBundleDecodeError


def _request_payload() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "archive-001",
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
        "request_id": "archive-001",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "attempts": [
                    {
                        "connector": "tdx-connector",
                        "tool": "get_sector_ranking",
                        "parameters": {"page": 1},
                        "status": "succeeded",
                        "error_code": None,
                    }
                ],
                "as_of": "2026-09-02",
                "pagination": {"complete": True},
                "sample_count": 1,
                "fields": ["sector_code", "change_percent"],
                "units": {"change_percent": "percent"},
                "records": [{"sector_code": "BK1036", "change_percent": 2.5}],
            }
        ],
        "warnings": [],
        "errors": [],
    }


def _raw(payload: dict, *, indent: int | None = None) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=indent).encode()


def _request() -> DataRequest:
    return DataRequest.from_mapping(_request_payload())


def _assert_public_error_is_sanitized(exc: Exception, *secrets: str) -> None:
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    exposed = repr(vars(exc)) + formatted
    assert exc.__cause__ is None
    assert exc.__context__ is None
    for secret in secrets:
        assert secret not in exposed


def test_first_archive_preserves_exact_bytes_and_writes_literal_manifest(tmp_path: Path) -> None:
    request = _request()
    raw = _raw(_bundle_payload(), indent=2)
    original_request = copy.deepcopy(request)

    outcome = archive_data_bundle(request, raw, tmp_path)

    final = tmp_path / "runs" / "archive-001"
    assert outcome.run_directory == final
    assert outcome.manifest_path == final / "manifest.json"
    assert outcome.archive_uri == "archive://runs/archive-001"
    assert outcome.idempotent is False
    assert outcome.archived_raw_sha256 == hashlib.sha256(raw).hexdigest()
    assert outcome.archived_size_bytes == len(raw)
    assert (final / "data-bundle.json").read_bytes() == raw
    assert request == original_request
    assert json.loads(outcome.manifest_path.read_bytes()) == {
        "schema_version": "data-bundle-archive-manifest/1.0",
        "request_id": "archive-001",
        "definition_key": "sector-market-data",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": "a" * 64,
        "stage": "sector_selection",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T04:00:00+00:00",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_sha256": outcome.validated_bundle.canonical_sha256,
        "byte_size": len(raw),
        "data_path": "data-bundle.json",
    }
    assert outcome.manifest_path.read_bytes().endswith(b"\n")


def test_equivalent_json_is_idempotent_and_preserves_first_bytes(tmp_path: Path) -> None:
    payload = _bundle_payload()
    first_raw = _raw(payload)
    first = archive_data_bundle(_request(), first_raw, tmp_path)
    equivalent_raw = _raw({key: payload[key] for key in reversed(payload)}, indent=2)

    second = archive_data_bundle(_request(), equivalent_raw, tmp_path)

    assert first.validated_bundle.canonical_sha256 == second.validated_bundle.canonical_sha256
    assert equivalent_raw != first_raw
    assert second.idempotent is True
    assert second.archived_raw_sha256 == hashlib.sha256(first_raw).hexdigest()
    assert second.archived_size_bytes == len(first_raw)
    assert (second.run_directory / "data-bundle.json").read_bytes() == first_raw


def test_idempotent_retry_returns_projection_from_retained_signed_zero_bytes(
    tmp_path: Path,
) -> None:
    first_payload = _bundle_payload()
    first_payload["datasets"][0]["records"][0]["change_percent"] = 0.0
    first_raw = _raw(first_payload)
    first = archive_data_bundle(_request(), first_raw, tmp_path)
    retry_payload = _bundle_payload()
    retry_payload["datasets"][0]["records"][0]["change_percent"] = -0.0

    retry = archive_data_bundle(_request(), _raw(retry_payload), tmp_path)

    retained_value = retry.validated_bundle.bundle.datasets[0].records[0]["change_percent"]
    assert retry.idempotent is True
    assert retry.validated_bundle.canonical_sha256 == first.validated_bundle.canonical_sha256
    assert math.copysign(1.0, retained_value) == 1.0
    assert retry.archived_raw_sha256 == hashlib.sha256(first_raw).hexdigest()
    assert retry.archived_size_bytes == len(first_raw)


def test_different_canonical_bundle_conflicts_without_mutation(tmp_path: Path) -> None:
    raw = _raw(_bundle_payload())
    outcome = archive_data_bundle(_request(), raw, tmp_path)
    before = {path.name: path.read_bytes() for path in outcome.run_directory.iterdir()}
    changed = _bundle_payload()
    changed["datasets"][0]["records"][0]["change_percent"] = 3.0

    with pytest.raises(DataBundleArchiveConflictError) as exc_info:
        archive_data_bundle(_request(), _raw(changed), tmp_path)

    assert exc_info.value.code == "archive_conflict"
    assert {path.name: path.read_bytes() for path in outcome.run_directory.iterdir()} == before


@pytest.mark.parametrize("damage", ["missing", "malformed", "tampered", "extra"])
def test_damaged_existing_archive_is_integrity_error(tmp_path: Path, damage: str) -> None:
    outcome = archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)
    if damage == "missing":
        outcome.manifest_path.unlink()
    elif damage == "malformed":
        outcome.manifest_path.write_bytes(b"not-json")
    elif damage == "tampered":
        (outcome.run_directory / "data-bundle.json").write_bytes(b"{}")
    else:
        (outcome.run_directory / "extra").write_bytes(b"")

    with pytest.raises(DataBundleArchiveIntegrityError) as exc_info:
        archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)

    assert exc_info.value.code == "archive_integrity_error"
    assert str(tmp_path) not in str(exc_info.value)
    assert "archive-001" not in str(exc_info.value)


def test_symlinked_existing_entry_is_integrity_error(tmp_path: Path) -> None:
    outcome = archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)
    outcome.manifest_path.unlink()
    outside = tmp_path / "outside"
    outside.write_text("{}")
    outcome.manifest_path.symlink_to(outside)

    with pytest.raises(DataBundleArchiveIntegrityError):
        archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)


def test_unsafe_root_conditions_are_sanitized(tmp_path: Path) -> None:
    raw = _raw(_bundle_payload())
    real = tmp_path / "real"
    real.mkdir()
    symlink = tmp_path / "linked"
    symlink.symlink_to(real, target_is_directory=True)
    regular = tmp_path / "file"
    regular.write_text("x")

    for root in (symlink, regular, tmp_path / "missing", tmp_path / ".." / tmp_path.name):
        with pytest.raises(DataBundleArchivePathError) as exc_info:
            archive_data_bundle(_request(), raw, root)
        assert exc_info.value.code == "unsafe_archive_path"
        assert str(root) not in str(exc_info.value)


def test_validation_failure_does_not_create_archive_layout(tmp_path: Path) -> None:
    with pytest.raises(DataBundleDecodeError):
        archive_data_bundle(_request(), b"not-json", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_symlinked_runs_parent_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DataBundleArchivePathError):
        archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)
    assert list(outside.iterdir()) == []


def test_publication_uses_temp_directory_and_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = os.replace
    calls: list[tuple[Path, Path]] = []

    def recording_replace(source: Path, destination: Path) -> None:
        calls.append((source, destination))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)
    outcome = archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)

    assert len(calls) == 1
    source, destination = calls[0]
    assert source.parent == tmp_path / "runs"
    assert source.name.startswith(".data-bundle-staging-")
    assert destination == outcome.run_directory
    assert {path.name for path in (tmp_path / "runs").iterdir()} == {"archive-001"}


def test_write_failure_cleans_staging_and_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "/untrusted/private/archive/location archive-001 BK1036"
    real_write_bytes = Path.write_bytes

    def failing_write(path: Path, data: bytes) -> int:
        if path.name == "manifest.json":
            raise OSError(secret)
        return real_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(DataBundleArchiveIOError) as exc_info:
        archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)

    assert exc_info.value.code == "archive_io_failure"
    assert list((tmp_path / "runs").iterdir()) == []
    _assert_public_error_is_sanitized(exc_info.value, secret, "failing_write")


def test_unexpected_internal_error_is_sanitized_at_public_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "/injected/unexpected/archive detail archive-001 BK1036"

    def injected_replace(*args) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(archive_module.os, "replace", injected_replace)
    with pytest.raises(DataBundleArchiveIOError) as exc_info:
        archive_data_bundle(_request(), _raw(_bundle_payload()), tmp_path)

    assert str(exc_info.value) == "Data bundle archive could not be published safely."
    _assert_public_error_is_sanitized(exc_info.value, secret, "injected_replace")
