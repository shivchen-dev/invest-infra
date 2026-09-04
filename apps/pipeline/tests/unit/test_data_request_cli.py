from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from invest_domain.strategy import DataRequest
from invest_pipeline.data_request_cli import materialize_request, run


def _definition() -> dict[str, object]:
    return {
        "data_request_template": {
            "schema_version": "workbuddy-data-request/1.0",
            "definition_key": "sector-strength-ranking",
            "definition_version": "1.0.0",
            "strategy_key": "sector-strength-ranking",
            "strategy_version": "2.0.0",
            "strategy_artifact_hash": "a" * 64,
            "stage": "sector_selection",
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
    }


def _write_definition(path: Path, definition: object | None = None) -> Path:
    path.write_text(json.dumps(_definition() if definition is None else definition))
    return path


def test_valid_sector_request_is_deterministic_and_compact(tmp_path: Path) -> None:
    definition_path = _write_definition(tmp_path / "definition.json")
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        run(
            definition_path,
            "req_20260904_sector_01",
            "2026-09-03",
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = materialize_request(definition_path, "req_20260904_sector_01", "2026-09-03")
    DataRequest.from_mapping(payload)
    assert (
        stdout.getvalue()
        == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    assert stderr.getvalue() == ""


def test_symlink_definition_is_rejected(tmp_path: Path) -> None:
    target = _write_definition(tmp_path / "target.json")
    link = tmp_path / "definition.json"
    link.symlink_to(target)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert run(link, "request_1", "2026-09-03", stdout=stdout, stderr=stderr) == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "data_request_definition_unavailable",
        "status": "error",
    }


@pytest.mark.parametrize("content", ["{broken", "[]"])
def test_malformed_definition_is_rejected(tmp_path: Path, content: str) -> None:
    definition_path = tmp_path / "definition.json"
    definition_path.write_text(content)
    stderr = io.StringIO()

    assert run(definition_path, "request_1", "2026-09-03", stderr=stderr) == 1
    assert json.loads(stderr.getvalue()) == {
        "error": "data_request_definition_invalid",
        "status": "error",
    }


@pytest.mark.parametrize(
    ("request_id", "as_of"),
    [("../unsafe", "2026-09-03"), ("request_1", "2026-02-30")],
)
def test_unsafe_request_id_or_date_is_rejected(tmp_path: Path, request_id: str, as_of: str) -> None:
    definition_path = _write_definition(tmp_path / "definition.json")
    stderr = io.StringIO()

    assert run(definition_path, request_id, as_of, stderr=stderr) == 1
    assert json.loads(stderr.getvalue()) == {
        "error": "data_request_input_invalid",
        "status": "error",
    }


def test_errors_are_stable_and_sanitized(tmp_path: Path) -> None:
    secret = "secret-template-detail"
    definition = _definition()
    definition["data_request_template"]["unexpected"] = secret  # type: ignore[index]
    definition_path = _write_definition(tmp_path / secret, definition)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert run(definition_path, "request_1", "2026-09-03", stdout=stdout, stderr=stderr) == 1
    assert stderr.getvalue() == ('{"error":"data_request_definition_invalid","status":"error"}\n')
    assert secret not in stderr.getvalue()
    assert stdout.getvalue() == ""
