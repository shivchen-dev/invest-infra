"""CLI surface for :mod:`invest_pipeline.workbuddy_reports`.

M0 first slice implements only the ``validate`` subcommand.  M1 first
atomic slice extends the CLI with the ``import`` subcommand (contract
section 9); ``import`` builds the immutable governance archive under
``<root>/runs/<trade_date>/<workflow_run_id>/`` from a triplet in
``--source-dir``.  M2 second atomic slice adds the
accepted-only ``latest-accepted.json`` pointer update: ``import`` writes
the pointer atomically when the final verdict is ``accepted`` and skips
it for ``partial`` / ``rejected`` runs (contract section 8).  Pointer
updates are serialized across processes with ``fcntl.flock`` and never
let an older ``(trade_date, finished_at, workflow_run_id)`` key overwrite
a newer on-disk pointer.

Diagnostic logging is written to stderr; the contract requires the
stdout payload to be a single JSON object.  Exit codes follow section 9:

* ``0`` — ``accepted`` (``validate`` and ``import``); or idempotent
  re-import with matching archive hash set.
* ``2`` — ``partial``.
* ``3`` — ``rejected`` (validation-level rejection).
* ``4`` — input / argument / unsupported-version error.
* ``5`` — archive conflict or I/O failure (``import`` only).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from invest_pipeline.workbuddy_reports import (
    archive_run,
    discover_triplet,
    validate_triplet,
)

_EXIT_ACCEPTED = 0
_EXIT_PARTIAL = 2
_EXIT_REJECTED = 3
_EXIT_INPUT_ERROR = 4
_EXIT_IO_ERROR = 5


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invest_pipeline.workbuddy_reports",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser(
        "validate",
        help="Validate a WorkBuddy governance triplet in --source-dir.",
    )
    validate.add_argument(
        "--source-dir",
        required=True,
        help=(
            "Directory holding the governance triplet. Canonical names are "
            "sector_result*.json, 板块强度排行榜*.md, and sector_quality*.json; "
            "legacy result*.json, report*.md, and quality_report*.json prefixes "
            "are also accepted."
        ),
    )
    import_cmd = sub.add_parser(
        "import",
        help=(
            "Build the immutable governance archive under --root for the "
            "triplet in --source-dir."
        ),
    )
    import_cmd.add_argument(
        "--source-dir",
        required=True,
        help="Directory holding the governance triplet (same rules as validate).",
    )
    import_cmd.add_argument(
        "--root",
        required=True,
        help=(
            "Governance root. Archive layout is "
            "<root>/runs/<trade_date>/<workflow_run_id>/."
        ),
    )
    return parser


def _verdict_payload(
    *,
    status: str,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "governance_status": status,
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _run_validate(source_dir: str) -> int:
    triple = discover_triplet(source_dir)
    if triple is None:
        payload = _verdict_payload(
            status="input_error",
            errors=[
                f"could not locate sector_result*.json + 板块强度排行榜*.md + "
                f"sector_quality*.json (or legacy result*.json + report*.md + "
                f"quality_report*.json) inside {source_dir!r}"
            ],
        )
        _emit(payload)
        return _EXIT_INPUT_ERROR

    result_path, report_path, quality_path = triple
    verdict = validate_triplet(
        result_path=result_path,
        report_path=report_path,
        quality_path=quality_path,
    )
    _emit(verdict.to_dict())
    return verdict.exit_code


def _run_import(source_dir: str, root: str) -> int:
    outcome = archive_run(source_dir=source_dir, governance_root=root)
    _emit(outcome.to_dict())
    return outcome.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate":
        return _run_validate(args.source_dir)
    if args.command == "import":
        return _run_import(args.source_dir, args.root)
    parser.error(f"unknown command {args.command!r}")
    return _EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())