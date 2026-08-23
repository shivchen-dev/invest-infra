"""C6 single-run strategy archive CLI.

Thin wrapper around :class:`StrategyCombinedArchive` that performs **one**
``process_once()`` (or ``recover_once()`` when ``--recover`` is supplied) and
emits the resulting outcomes as redacted JSON lines on stdout.

Invocation::

    python -m invest_pipeline.strategy_archive_cli --bridge-root PATH
    python -m invest_pipeline.strategy_archive_cli --bridge-root PATH --recover

The CLI never inspects or moves bridge files itself. All filesystem work is
delegated to the archive worker; this module only parses arguments, runs a
single ``process_once``/``recover_once`` call, and emits a deterministic JSON
line per outcome. ``bridge_root`` is never echoed back on stdout or stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Never, TextIO

from invest_pipeline.integrations.workbuddy_strategy_archive import (
    StrategyCombinedArchive,
    StrategyPackageOutcome,
)

_ZERO_EXIT_STATUSES = frozenset({"success", "validated", "already_archived"})


class _SilentErrorArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._error_written = False

    def error(self, message: str) -> Never:
        if not self._error_written:
            self._error_written = True
            sys.stderr.write(f"error: {message}\n")
        raise SystemExit(2)


def build_parser() -> _SilentErrorArgumentParser:
    parser = _SilentErrorArgumentParser(
        prog="invest_pipeline.strategy_archive_cli",
        description=(
            "Run a single StrategyCombinedArchive pass and emit one JSON object per outcome."
        ),
    )
    parser.add_argument(
        "--bridge-root",
        type=Path,
        required=True,
        help="Bridge root directory that hosts the strategy stage tree.",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Resume processing/<task_id> residue instead of claiming new pairs.",
    )
    return parser


def _outcome_to_dict(outcome: StrategyPackageOutcome) -> dict[str, object]:
    return {
        "task_id": outcome.task_id,
        "status": outcome.status,
        "error": outcome.error,
    }


def _select_exit_code(outcomes: tuple[StrategyPackageOutcome, ...]) -> int:
    if not outcomes:
        return 0
    if all(outcome.status in _ZERO_EXIT_STATUSES for outcome in outcomes):
        return 0
    return 1


def _emit(
    outcomes: tuple[StrategyPackageOutcome, ...],
    stdout: TextIO,
) -> None:
    for outcome in outcomes:
        stdout.write(json.dumps(_outcome_to_dict(outcome), ensure_ascii=False))
        stdout.write("\n")


def run(
    *,
    bridge_root: str | Path,
    recover: bool = False,
    archive_factory: Any = StrategyCombinedArchive,
    stdout: TextIO | None = None,
) -> int:
    worker = archive_factory(bridge_root)
    outcomes = worker.recover_once() if recover else worker.process_once()
    _emit(outcomes, stdout or sys.stdout)
    return _select_exit_code(outcomes)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return run(
            bridge_root=args.bridge_root,
            recover=args.recover,
        )
    except Exception:  # noqa: BLE001
        sys.stderr.write("error: strategy archive run failed\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
