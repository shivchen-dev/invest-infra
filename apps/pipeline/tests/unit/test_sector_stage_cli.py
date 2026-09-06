from __future__ import annotations

import io
import json
import os
from pathlib import Path

from invest_pipeline.sector_stage_cli import build_parser, run

HASH = "e05e2e191311fb3273a2f14748b7265c1cec47a37339f7a70a139a85a7bf68b2"
STRATEGY = {
    "strategy_id": "sector-strength-ranking",
    "version_candidate": "2.0.0",
    "rules": [{"id": rule} for rule in ("R-A1", "R-A3", "R-A4", "R-A5")],
}


def _request() -> dict:
    return {
        "schema_version": "workbuddy-data-request/1.0",
        "request_id": "req_sector_20260902",
        "definition_key": "sector-strength-ranking",
        "definition_version": "1.0.0",
        "strategy_key": "sector-strength-ranking",
        "strategy_version": "2.0.0",
        "strategy_artifact_hash": HASH,
        "stage": "sector_selection",
        "as_of": "2026-09-02",
        "max_delivery_lag_days": 2,
        "datasets": [
            {
                "dataset_key": "sector-ranking",
                "required_fields": ["group", "bd_code", "bd_name", "cje", "bd_zdf", "zgb"],
                "allowed_connectors": ["tdx-connector"],
            },
            {
                "dataset_key": "sector-constituents",
                "required_fields": ["group", "bd_code", "symbol", "name"],
                "allowed_connectors": ["tdx-connector"],
            },
        ],
        "output_contract": "workbuddy-data-bundle/1.0",
    }


def _dataset(key: str, fields: list[str], records: list[dict]) -> dict:
    return {
        "dataset_key": key,
        "attempts": [
            {
                "connector": "tdx-connector",
                "tool": "get_data",
                "parameters": {},
                "status": "succeeded",
                "error_code": None,
            }
        ],
        "as_of": "2026-09-02",
        "pagination": {"complete": True},
        "sample_count": len(records),
        "fields": fields,
        "units": {},
        "records": records,
    }


def _bundle() -> dict:
    rankings = [
        {
            "group": group,
            "bd_code": code,
            "bd_name": name,
            "cje": 10,
            "bd_zdf": 1,
            "zgb": "1/2",
        }
        for group, code, name in (
            ("industry", "I", "Industry"),
            ("concept", "C", "Concept"),
            ("area", "A", "Area"),
        )
    ]
    constituents = [
        {
            "group": row["group"],
            "bd_code": row["bd_code"],
            "symbol": f"S{row['bd_code']}",
            "name": row["bd_name"],
        }
        for row in rankings
    ]
    return {
        "schema_version": "workbuddy-data-bundle/1.0",
        "request_id": "req_sector_20260902",
        "producer": "workbuddy",
        "generated_at": "2026-09-03T00:00:00+00:00",
        "datasets": [
            _dataset(
                "sector-ranking",
                ["group", "bd_code", "bd_name", "cje", "bd_zdf", "zgb"],
                rankings,
            ),
            _dataset(
                "sector-constituents",
                ["group", "bd_code", "symbol", "name"],
                constituents,
            ),
        ],
        "warnings": [],
        "errors": [],
    }


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = tuple(tmp_path / name for name in ("request.json", "bundle.json", "strategy.json"))
    for path, value in zip(paths, (_request(), _bundle(), STRATEGY), strict=True):
        path.write_text(json.dumps(value), encoding="utf-8")
    return paths


def test_success_is_deterministic_and_output_is_exact_compact_sorted(tmp_path: Path) -> None:
    request, bundle, strategy = _files(tmp_path)
    outputs = [io.StringIO(), io.StringIO()]

    for output in outputs:
        errors = io.StringIO()
        assert run(request, bundle, strategy, stdout=output, stderr=errors) == 0
        assert errors.getvalue() == ""
    assert outputs[0].getvalue() == outputs[1].getvalue()
    assert json.loads(outputs[0].getvalue())["status"] == "SUCCEEDED"

    exact_output = io.StringIO()
    assert (
        run(
            request,
            bundle,
            strategy,
            evaluator=lambda *args, **kwargs: {"z": 1, "a": "板块"},
            stdout=exact_output,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert exact_output.getvalue() == '{"a":"板块","z":1}\n'


def test_invalid_inputs_are_rejected_with_exact_sanitized_error_and_no_stdout(
    tmp_path: Path,
) -> None:
    for invalid_input in (
        "malformed",
        "non_object",
        "invalid_utf8",
        "directory",
        "fifo",
        "symlink",
    ):
        case_path = tmp_path / invalid_input
        case_path.mkdir()
        request, bundle, strategy = _files(case_path)
        if invalid_input == "malformed":
            request.write_text("{", encoding="utf-8")
        elif invalid_input == "non_object":
            request.write_text("[]", encoding="utf-8")
        elif invalid_input == "invalid_utf8":
            request.write_bytes(b'{"invalid":"\xff"}')
        elif invalid_input == "directory":
            request = case_path
        elif invalid_input == "fifo":
            request = case_path / "request.fifo"
            os.mkfifo(request)
        else:
            link = case_path / "request-link.json"
            link.symlink_to(request)
            request = link
        stdout, stderr = io.StringIO(), io.StringIO()

        assert run(request, bundle, strategy, stdout=stdout, stderr=stderr) == 1
        assert stderr.getvalue() == '{"error":"sector_stage_input_invalid","status":"error"}\n'
        assert stdout.getvalue() == ""


def test_invalid_strategy_is_rejected_with_exact_sanitized_error_and_no_stdout(
    tmp_path: Path,
) -> None:
    for strategy_case in ("missing", "inconsistent"):
        case_path = tmp_path / strategy_case
        case_path.mkdir()
        request, bundle, strategy = _files(case_path)
        if strategy_case == "missing":
            strategy = None
        else:
            strategy.write_text(
                json.dumps({**STRATEGY, "version_candidate": "9.9.9"}),
                encoding="utf-8",
            )
        stdout, stderr = io.StringIO(), io.StringIO()

        assert run(request, bundle, strategy, stdout=stdout, stderr=stderr) == 1
        assert stderr.getvalue() == '{"error":"sector_stage_evaluation_failed","status":"error"}\n'
        assert stdout.getvalue() == ""


def test_parser_flags() -> None:
    args = build_parser().parse_args(
        [
            "--request-json-file",
            "request.json",
            "--bundle-json-file",
            "bundle.json",
            "--strategy-json-file",
            "strategy.json",
        ]
    )
    assert args.request_json_file == Path("request.json")
    assert args.bundle_json_file == Path("bundle.json")
    assert args.strategy_json_file == Path("strategy.json")
