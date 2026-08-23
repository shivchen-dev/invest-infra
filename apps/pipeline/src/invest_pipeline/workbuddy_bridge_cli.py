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
    parser.add_argument("--recover", action="store_true")
    return parser


def resolve_paths(settings: Settings, args: argparse.Namespace) -> tuple[Path, Path]:
    bridge_root = (args.bridge_root or settings.workbuddy_bridge_root).resolve()
    source_dir = (
        args.source_dir or settings.workbuddy_source_dir or bridge_root / "candidate" / "results"
    ).resolve()
    return bridge_root, source_dir


def _build_instrument_resolver(uow: Any) -> Callable[[str], str | None]:
    cache: dict[str, str | None] = {}
    repository = getattr(uow, "instruments", None)
    suffix_to_exchange = {"SH": "SSE", "SZ": "SZSE"}

    def resolve(symbol: str) -> str | None:
        normalized = symbol.strip()
        if normalized in cache:
            return cache[normalized]
        if repository is None:
            cache[normalized] = None
            return None

        bare = normalized
        suffix = None
        if "." in normalized:
            head, _, tail = normalized.partition(".")
            if len(tail) == 2 and tail.isalpha():
                bare = head
                suffix = tail.upper()

        if len(bare) != 6 or not bare.isdigit():
            cache[normalized] = None
            return None
        prefix = bare[0]
        exchange = "SSE" if prefix in {"5", "6"} else "SZSE" if prefix in {"1", "2"} else None
        if exchange is None:
            cache[normalized] = None
            return None
        if suffix is not None and suffix_to_exchange.get(suffix) != exchange:
            cache[normalized] = None
            return None

        instrument = repository.get_by_business_key(
            exchange=exchange,
            symbol=bare,
        )
        resolved = (
            instrument.symbol
            if instrument is not None and getattr(instrument, "is_active", True)
            else None
        )
        cache[normalized] = resolved
        return resolved

    return resolve


def _summary(outcomes: tuple[Any, ...]) -> dict[str, list[dict[str, Any]]]:
    summary: list[dict[str, Any]] = []
    for outcome in outcomes:
        result = getattr(outcome, "result", None)
        findings = getattr(outcome, "findings", None) or []
        summary.append(
            {
                "file": outcome.package,
                "status": "success" if outcome.error is None else "failed",
                "observation_count": len(result.observations) if result else 0,
                "archive_uri": getattr(outcome, "archive_uri", None),
                "accepted_count": getattr(outcome, "accepted_count", None),
                "rejected_count": getattr(outcome, "rejected_count", None),
                "needs_symbol_resolution_count": getattr(
                    outcome, "needs_symbol_resolution_count", None
                ),
                "findings": [dict(item) for item in findings],
                "archive_idempotent": getattr(outcome, "archive_idempotent", None),
                "import_idempotent": getattr(outcome, "import_idempotent", None),
                "conflict": getattr(outcome, "conflict", None),
            }
        )
    return {"imports": summary}


def run_import(
    bridge_root: Path,
    source_dir: Path,
    *,
    engine_builder: Callable[[str], Any] = build_engine,
    session_factory_builder: Callable[[Any], Any] = session_factory,
    gateway_factory: Callable[..., Any] = SharedDirectoryWorkBuddyGateway,
    uow_factory: Callable[[Any], Any] = SqlAlchemyUnitOfWork,
    settings: Settings | None = None,
    recover: bool = False,
) -> int:
    configured = settings or get_settings()
    engine = engine_builder(configured.database_url)
    try:
        sessions = session_factory_builder(engine)
        gateway = gateway_factory(bridge_root, source_dir)
        with uow_factory(sessions) as uow:
            resolver = _build_instrument_resolver(uow)
            process = gateway.recover_once if recover else gateway.process_once
            outcomes = process(uow=uow, resolver=resolver)
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
