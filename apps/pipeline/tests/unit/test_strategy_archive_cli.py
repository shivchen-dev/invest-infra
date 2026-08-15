"""Focused unit tests for the C6 single-run strategy archive CLI.

Covers:
* ``--help`` and ``--bridge-root`` parser surface.
* Empty bridge tree exits ``0`` with no stdout output.
* Single successful ``process_once`` exits ``0`` with one JSON line.
* ``--recover`` resumes a processing residue and exits ``0`` on success.
* Mixed success + hard failure exits non-zero with both outcomes emitted.
* Archive-conflict outcome exits non-zero.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest import mock

from invest_pipeline import strategy_archive_cli as cli
from invest_pipeline.integrations.workbuddy_strategy_archive import (
    StrategyPackageOutcome,
)


def _outcome(task_id: str, status: str, error: str | None = None) -> StrategyPackageOutcome:
    return StrategyPackageOutcome(task_id=task_id, status=status, error=error)


def _stub_worker(outcomes: tuple[StrategyPackageOutcome, ...]) -> mock.Mock:
    """Return a stub archive worker whose ``process_once`` and ``recover_once``
    produce the given outcomes (only the method that is actually called is
    exercised; the other is left unmocked)."""
    worker = mock.Mock()
    worker.process_once.return_value = outcomes
    worker.recover_once.return_value = outcomes
    return worker


class HelpTest(unittest.TestCase):
    def test_help_exits_zero_and_lists_bridge_root(self) -> None:
        stdout = io.StringIO()
        with mock.patch("sys.stdout", stdout), self.assertRaises(SystemExit) as ctx:
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("--bridge-root", stdout.getvalue())


class EmptyTest(unittest.TestCase):
    def test_empty_outcomes_emit_nothing_and_exit_zero(self) -> None:
        worker = _stub_worker(())
        stdout = io.StringIO()
        rc = cli.run(
            bridge_root=Path("/tmp/strategy_cli_empty"),
            recover=False,
            archive_factory=lambda _root: worker,
            stdout=stdout,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")
        worker.process_once.assert_called_once_with()
        worker.recover_once.assert_not_called()


class SuccessTest(unittest.TestCase):
    def test_process_once_success_emits_json_line_and_exits_zero(self) -> None:
        worker = _stub_worker((_outcome("task-001", "success", None),))
        stdout = io.StringIO()
        rc = cli.run(
            bridge_root=Path("/tmp/strategy_cli_success"),
            recover=False,
            archive_factory=lambda _root: worker,
            stdout=stdout,
        )
        self.assertEqual(rc, 0)
        lines = [line for line in stdout.getvalue().split("\n") if line]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload, {"task_id": "task-001", "status": "success", "error": None})
        self.assertNotIn("/tmp/strategy_cli_success", lines[0])
        worker.process_once.assert_called_once_with()


class RecoverTest(unittest.TestCase):
    def test_recover_success_emits_json_line_and_exits_zero(self) -> None:
        worker = _stub_worker((_outcome("task-001", "success", None),))
        stdout = io.StringIO()
        rc = cli.run(
            bridge_root=Path("/tmp/strategy_cli_recover"),
            recover=True,
            archive_factory=lambda _root: worker,
            stdout=stdout,
        )
        self.assertEqual(rc, 0)
        lines = [line for line in stdout.getvalue().split("\n") if line]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["task_id"], "task-001")
        self.assertIsNone(payload["error"])
        worker.recover_once.assert_called_once_with()
        worker.process_once.assert_not_called()


class MixedFailureTest(unittest.TestCase):
    def test_success_plus_conflict_exits_nonzero_and_emits_both(self) -> None:
        bridge = Path("/tmp/strategy_cli_mixed")
        worker = _stub_worker(
            (
                _outcome("task-good", "success", None),
                _outcome("task-bad", "archive_conflict", "archive does not match sources"),
            )
        )
        stdout = io.StringIO()
        rc = cli.run(
            bridge_root=bridge,
            recover=False,
            archive_factory=lambda _root: worker,
            stdout=stdout,
        )
        self.assertEqual(rc, 1)
        lines = [line for line in stdout.getvalue().split("\n") if line]
        self.assertEqual(len(lines), 2)
        statuses = sorted(json.loads(line)["status"] for line in lines)
        self.assertEqual(statuses, ["archive_conflict", "success"])
        for line in lines:
            self.assertNotIn(str(bridge), line)


class ConflictExitTest(unittest.TestCase):
    def test_archive_conflict_exits_nonzero(self) -> None:
        bridge = Path("/tmp/strategy_cli_conflict")
        worker = _stub_worker(
            (_outcome("task-001", "archive_conflict", "archive does not match sources"),)
        )
        stdout = io.StringIO()
        rc = cli.run(
            bridge_root=bridge,
            recover=False,
            archive_factory=lambda _root: worker,
            stdout=stdout,
        )
        self.assertEqual(rc, 1)
        lines = [line for line in stdout.getvalue().split("\n") if line]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "archive_conflict")
        self.assertEqual(payload["task_id"], "task-001")
        self.assertEqual(payload["error"], "archive does not match sources")
        self.assertNotIn(str(bridge), lines[0])


if __name__ == "__main__":
    unittest.main()
