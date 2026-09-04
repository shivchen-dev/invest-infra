"""Deterministically materialize one sector DataRequest from a local definition."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from invest_domain.strategy import DataRequest

_DEFINITION_UNAVAILABLE = "data_request_definition_unavailable"
_DEFINITION_INVALID = "data_request_definition_invalid"
_INPUT_INVALID = "data_request_input_invalid"
_MATERIALIZATION_FAILED = "data_request_materialization_failed"
_VALIDATION_REQUEST_ID = "validation_request"
_VALIDATION_AS_OF = "2000-01-01"


class _MaterializationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without performing any I/O."""
    parser = argparse.ArgumentParser(
        prog="python -m invest_pipeline.data_request_cli",
        description="Materialize a sector DataRequest from a local definition JSON.",
    )
    parser.add_argument("--definition-json-file", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--as-of", required=True)
    return parser


def _read_definition(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise _MaterializationError(_DEFINITION_UNAVAILABLE)
        raw = path.read_bytes()
    except _MaterializationError:
        raise
    except OSError:
        raise _MaterializationError(_DEFINITION_UNAVAILABLE) from None

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _MaterializationError(_DEFINITION_INVALID) from None
    if type(value) is not dict:
        raise _MaterializationError(_DEFINITION_INVALID)
    return value


def _validated_template(definition: dict[str, Any]) -> dict[str, Any]:
    template = definition.get("data_request_template")
    if type(template) is not dict:
        raise _MaterializationError(_DEFINITION_INVALID)

    validation_payload = copy.deepcopy(template)
    validation_payload["request_id"] = _VALIDATION_REQUEST_ID
    validation_payload["as_of"] = _VALIDATION_AS_OF
    try:
        request = DataRequest.from_mapping(validation_payload)
    except (TypeError, ValueError):
        raise _MaterializationError(_DEFINITION_INVALID) from None
    if request.stage != "sector_selection":
        raise _MaterializationError(_DEFINITION_INVALID)
    return copy.deepcopy(template)


def materialize_request(definition_json_file: Path, request_id: str, as_of: str) -> dict[str, Any]:
    """Return a validated request with only its two dynamic fields replaced."""
    payload = _validated_template(_read_definition(Path(definition_json_file)))
    payload["request_id"] = request_id
    payload["as_of"] = as_of
    try:
        DataRequest.from_mapping(payload)
    except (TypeError, ValueError):
        raise _MaterializationError(_INPUT_INVALID) from None
    return payload


def _json_line(payload: dict[str, Any]) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def run(
    definition_json_file: Path,
    request_id: str,
    as_of: str,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Materialize one request and emit exactly one JSON line."""
    try:
        payload = materialize_request(definition_json_file, request_id, as_of)
    except Exception as exc:  # noqa: BLE001 - CLI boundary must sanitize failures
        code = getattr(exc, "code", _MATERIALIZATION_FAILED)
        (stderr or sys.stderr).write(_json_line({"error": code, "status": "error"}))
        return 1
    (stdout or sys.stdout).write(_json_line(payload))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the testable runner."""
    args = build_parser().parse_args(argv)
    return run(args.definition_json_file, args.request_id, args.as_of)


if __name__ == "__main__":
    raise SystemExit(main())
