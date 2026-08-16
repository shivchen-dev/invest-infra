"""Manual one-shot ingestion for WorkBuddy research-stage deliveries."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from invest_pipeline.config import get_settings
from invest_pipeline.integrations.workbuddy_research_artifacts import (
    ResearchArtifactImport,
    ingest_research_artifact,
)
from invest_pipeline.integrations.workbuddy_stage_worker import (
    StagePackageOutcome,
    StagePackageWorker,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invest_pipeline.workbuddy_research_ingest_cli",
        description="Process WorkBuddy research deliveries once (no scheduler).",
    )
    parser.add_argument(
        "--archive-root",
        required=True,
        type=Path,
        help="immutable destination root for validated research artifacts",
    )
    parser.add_argument(
        "--bridge-root",
        type=Path,
        help="shared bridge root (defaults to pipeline settings)",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="resume safe packages already left in processing/",
    )
    return parser


def _public_outcome(outcome: StagePackageOutcome) -> dict[str, str]:
    return {
        "stage": "research",
        "status": outcome.status,
        "task_id": outcome.task_id,
    }


def run_import(
    bridge_root: Path,
    archive_root: Path,
    *,
    recover: bool = False,
    worker_factory: Callable[[Path, str], Any] = StagePackageWorker,
    ingestor: Callable[..., ResearchArtifactImport] = ingest_research_artifact,
) -> int:
    """Run one manual scan and return nonzero for any hard worker failure."""
    worker = worker_factory(bridge_root, "research")

    def handle(stage: str, package: Path) -> None:
        if stage != "research":
            raise ValueError("unexpected stage")
        imported = ingestor(package, archive_root, expected_task_id=package.name)
        if imported.archive_dir is None or imported.task_id != package.name:
            raise ValueError("research artifact ingestion failed")

    outcomes = worker.recover_once(handle) if recover else worker.process_once(handle)
    for outcome in outcomes:
        print(
            json.dumps(
                _public_outcome(outcome),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return 0 if all(outcome.status == "success" for outcome in outcomes) else 1


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        bridge_root = args.bridge_root or get_settings().workbuddy_bridge_root
        return run_import(
            bridge_root.resolve(), args.archive_root.resolve(), recover=args.recover
        )
    except Exception:
        print(
            json.dumps(
                {"error": "workbuddy_research_import_failed", "status": "error"},
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
