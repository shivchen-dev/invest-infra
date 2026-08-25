"""CLI for consuming queued ResearchRun records.

Routes between the deterministic in-process Fake runner (default) and the
historical JiuwenSwarm compatibility runner. The Fake runner is wired via
:func:`invest_pipeline.fake_research_runtime.build_fake_research_worker`;
the JiuwenSwarm path is preserved verbatim so existing operational
recipes that still drive the retired external helper continue to work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO
from uuid import UUID

from invest_domain.research import ResearchPlaybook

from invest_pipeline.config import get_settings
from invest_pipeline.fake_research_runtime import build_fake_research_worker
from invest_pipeline.jiuwenswarm_runtime import build_jiuwenswarm_worker

_JIUWENSWARM_REQUIRED = ("helper_path", "workspace", "artifact_root")


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a valid UUID") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run queued ResearchRun records.")
    parser.add_argument(
        "--runner",
        choices=("fake", "jiuwenswarm"),
        default="fake",
        help="Runner adapter: fake (default, in-process) or jiuwenswarm (compatibility).",
    )
    parser.add_argument("--helper-path", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--playbook-key", default="etf_medium_term_assessment")
    parser.add_argument("--playbook-version", default="v0.1.0")
    parser.add_argument("--run-id", type=_uuid)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--mode", default="default")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--idle-timeout", type=float, default=120.0)
    return parser


def _summary(outcome) -> dict[str, object]:
    if outcome is None:
        return {"status": "empty", "run_id": None, "case_id": None, "replay": False}
    status = outcome.run.status
    return {
        "status": getattr(status, "value", status),
        "run_id": str(outcome.run.run_id),
        "case_id": str(outcome.case.case_id),
        "replay": bool(outcome.replay),
    }


def _enforce_jiuwenswarm_requirements(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    missing = [name for name in _JIUWENSWARM_REQUIRED if getattr(args, name) is None]
    if missing:
        flags = ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        parser.error(f"--runner jiuwenswarm requires: {flags}")


def _build_worker(
    args: argparse.Namespace,
) -> object:
    playbook = ResearchPlaybook(
        playbook_key=args.playbook_key,
        playbook_version=args.playbook_version,
    )
    database_url = get_settings().database_url
    if args.runner == "fake":
        return build_fake_research_worker(
            database_url=database_url,
            playbook=playbook,
        )
    return build_jiuwenswarm_worker(
        database_url=database_url,
        helper_path=args.helper_path,
        workspace=str(args.workspace),
        artifact_root=args.artifact_root,
        playbook=playbook,
        mode=args.mode,
        timeout_seconds=args.timeout,
        idle_timeout_seconds=args.idle_timeout,
    )


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    if args.runner == "jiuwenswarm":
        try:
            _enforce_jiuwenswarm_requirements(parser, args)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1

    try:
        worker = _build_worker(args)
        outcome = (
            worker.run_once(args.run_id)
            if args.run_id is not None
            else worker.run_next(limit=args.limit)
        )
        print(json.dumps(_summary(outcome), separators=(",", ":")), file=stdout)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())