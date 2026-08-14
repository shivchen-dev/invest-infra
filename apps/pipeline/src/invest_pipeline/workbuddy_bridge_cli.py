"""Manual WorkBuddy shared-directory import command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from invest_storage import build_engine, session_factory
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork

from invest_pipeline.config import Settings, get_settings
from invest_pipeline.integrations import SharedDirectoryWorkBuddyGateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m invest_pipeline.workbuddy_bridge_cli")
    parser.add_argument("--bridge-root", type=Path)
    parser.add_argument("--source-dir", type=Path)
    return parser


def resolve_paths(settings: Settings, args: argparse.Namespace) -> tuple[Path, Path]:
    bridge_root = (args.bridge_root or settings.workbuddy_bridge_root).resolve()
    source_dir = (
        args.source_dir or settings.workbuddy_source_dir or bridge_root / "选股报告"
    ).resolve()
    return bridge_root, source_dir


def _summary(outcomes: tuple[Any, ...]) -> dict[str, list[dict[str, Any]]]:
    return {
        "imports": [
            {
                "file": outcome.package,
                "status": "success" if outcome.error is None else "failed",
                "observation_count": len(outcome.result.observations) if outcome.result else 0,
            }
            for outcome in outcomes
        ]
    }


def run_import(
    bridge_root: Path,
    source_dir: Path,
    *,
    engine_builder: Callable[[str], Any] = build_engine,
    session_factory_builder: Callable[[Any], Any] = session_factory,
    gateway_factory: Callable[..., Any] = SharedDirectoryWorkBuddyGateway,
    uow_factory: Callable[[Any], Any] = SqlAlchemyUnitOfWork,
    settings: Settings | None = None,
) -> int:
    configured = settings or get_settings()
    engine = engine_builder(configured.database_url)
    try:
        sessions = session_factory_builder(engine)
        gateway = gateway_factory(bridge_root, source_dir)
        with uow_factory(sessions) as uow:
            outcomes = gateway.process_once(uow=uow)
        print(json.dumps(_summary(outcomes), ensure_ascii=False, separators=(",", ":")))
        return 0
    finally:
        dispose = getattr(engine, "dispose", None)
        if dispose is not None:
            dispose()


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        settings = get_settings()
        bridge_root, source_dir = resolve_paths(settings, args)
        return run_import(bridge_root, source_dir, settings=settings)
    except Exception:
        print("error: WorkBuddy import failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
