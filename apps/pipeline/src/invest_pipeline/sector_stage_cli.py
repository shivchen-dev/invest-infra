"""Local deterministic runner for the sector-stage evaluator."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from invest_domain.strategy import DataBundle, DataRequest

from invest_pipeline.integrations.sector_evaluator import evaluate_sector_bundle

_INPUT_ERROR = {"error": "sector_stage_input_invalid", "status": "error"}
_EVALUATION_ERROR = {"error": "sector_stage_evaluation_failed", "status": "error"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invest_pipeline.sector_stage_cli",
        description="Evaluate one local sector-stage request and bundle.",
    )
    parser.add_argument("--request-json-file", type=Path, required=True)
    parser.add_argument("--bundle-json-file", type=Path, required=True)
    parser.add_argument("--strategy-json-file", type=Path)
    return parser


def _read_json_object(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError
        with os.fdopen(descriptor, encoding="utf-8", errors="strict") as stream:
            descriptor = -1
            value = json.load(stream)
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise ValueError
    return value


def _write_json(stream: TextIO, value: Mapping[str, object]) -> None:
    stream.write(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def run(
    request_json_file: Path,
    bundle_json_file: Path,
    strategy_json_file: Path | None = None,
    *,
    file_reader: Callable[[Path], dict[str, Any]] = _read_json_object,
    evaluator: Callable[..., dict[str, object]] = evaluate_sector_bundle,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    try:
        request = DataRequest.from_mapping(file_reader(request_json_file))
        bundle = DataBundle.from_mapping(file_reader(bundle_json_file))
        strategy = file_reader(strategy_json_file) if strategy_json_file is not None else None
    except Exception:  # noqa: BLE001
        _write_json(errors, _INPUT_ERROR)
        return 1

    try:
        result = evaluator(request, bundle, strategy_artifact=strategy)
        _write_json(output, result)
    except Exception:  # noqa: BLE001
        _write_json(errors, _EVALUATION_ERROR)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(
        args.request_json_file,
        args.bundle_json_file,
        args.strategy_json_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
