"""PR-6 JiuwenSwarm adapter — Slice 2 tests.

These tests cover the Slice 2 deliverable:

- :class:`JiuwenSwarmCliSettings` — the seven explicit config fields
  (no ``extra_argv``, no speculative design).
- :func:`build_prompt_text` — the prompt embeds ``request.to_json()``
  verbatim and forbids filesystem/workspace access, external data,
  unsupported facts (with explicit ``"unknown"`` fallback),
  unprovided indicators/levels, and buy/sell/position advice.
- :class:`JiuwenSwarmCliGatewayTransport` — the real subprocess
  transport pins the exact helper CLI argv, ``shell=False``, plain-text
  atomic task file, per-request artifact directory, fixed
  ``artifact_dir/result.md`` read, summary JSON parse with
  ``request_id`` equality and non-blank ``session_id``, and the full
  status / error mapping the Slice 2 spec requires.

The subprocess tests inject a deterministic ``FakeSubprocessRunner``
that pins every kwarg the production code passes and returns a
canned :class:`subprocess.CompletedProcess`. No real helper binary is
launched.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from invest_domain.instruments import InstrumentId
from invest_domain.market_data import (
    Adjust,
    BarSource,
    Currency,
    DailyBar,
    TradingStatus,
)
from invest_domain.research import (
    SCHEMA_VERSION,
    CandidateContext,
    CaseContext,
    DataQuality,
    EvidencePack,
    FreshnessStatus,
    InstrumentSnapshot,
    MarketSnapshot,
    QualityStatus,
    ResearchPlaybook,
    SourceReference,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun
from invest_pipeline.adapters.jiuwenswarm import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmAcceptance,
    JiuwenSwarmCliGatewayTransport,
    JiuwenSwarmCliSettings,
    JiuwenSwarmGatewayRequest,
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmTransportError,
    build_prompt_text,
    build_request,
    default_python_executable,
)
from invest_pipeline.adapters.jiuwenswarm.codec import (
    JiuwenSwarmCompletion,
    coerce_completion,
)
from invest_pipeline.adapters.jiuwenswarm.runner import JiuwenSwarmResearchRunner

# ---------------------------------------------------------------------------
# Test fixtures — same minimal pack as the Slice 1 tests.
# ---------------------------------------------------------------------------

_INSTRUMENT_ID = InstrumentId(UUID("11111111-1114-4118-9111-111111111111"))
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_CASE_ID = UUID("22222222-2224-4228-9222-222222222222")
_RUN_ID = UUID("33333333-3334-4338-9333-333333333333")
_AS_OF = date(2026, 3, 6)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
_HORIZON = "20-60d"
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)

_PLAYBOOK_KEY = "etf_medium_term_assessment"
_PLAYBOOK_VERSION = "v0.1.0"
_ADAPTER_VERSION = "jiuwenswarm-adapter-v1"


def _bars(count: int) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    out: list[DailyBar] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = Decimal(100 + index)
        out.append(
            DailyBar.build(
                instrument_id=_INSTRUMENT_ID,
                trade_date=trade_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                prev_close=None if index == 0 else Decimal(99 + index),
                volume=Decimal(1000 + index),
                amount=Decimal(1_000_000 + index * 1000),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=_SOURCE,
                revision=1,
                currency=Currency.CNY,
            )
        )
    return tuple(out)


def _build_pack() -> EvidencePack:
    selected = _bars(65)
    calculation = calculate_market_state_factors(
        selected,
        as_of_date=selected[-1].trade_date,
        instrument_id=_INSTRUMENT_ID,
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=_INSTRUMENT_ID,
            as_of_date=_AS_OF,
            question=_QUESTION,
            horizon=_HORIZON,
            case_id=_CASE_ID,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=_INSTRUMENT_ID,
            symbol="510300",
            name="沪深300ETF",
            exchange="SSE",
        ),
        candidate_context=CandidateContext(
            included=True,
            rank=1,
            total_score=Decimal("0.5"),
            exclusion_codes=(),
        ),
        market_snapshot=MarketSnapshot(
            latest_trade_date=_AS_OF,
            latest_close=Decimal("164"),
            currency="CNY",
            observed_trading_days=65,
            valid_price_days=65,
            suspended_days=0,
        ),
        factors=tuple(reversed(calculation.factors)),
        data_quality=DataQuality(
            freshness_status=FreshnessStatus.FRESH,
            quality_status=QualityStatus.COMPLETE,
            target_trading_days=65,
            observed_trading_days=65,
            valid_price_days=65,
        ),
        source_refs=(
            SourceReference(
                source_kind="daily_bar",
                source_ref="core.daily_bars:2026-03-06",
                observed_date=_AS_OF,
                revision=1,
            ),
            SourceReference(
                source_kind="instrument",
                source_ref="core.instruments:510300",
                observed_date=_AS_OF,
            ),
        ),
        schema_version=SCHEMA_VERSION,
        pack_id=_PACK_ID,
        pipeline_run_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        e2a_request_id="req-runtime-jws",
        e2a_session_id="sess-runtime-jws",
        generated_at=datetime(2026, 3, 6, 9, tzinfo=UTC),
        workspace_path="/runtime/workspace/jiuwenswarm",
    )


def _running_request() -> JiuwenSwarmGatewayRequest:
    pack = _build_pack()
    case = ResearchCase(
        case_id=_CASE_ID,
        instrument_id=pack.instrument.instrument_id,
        as_of_date=pack.case.as_of_date,
        question=pack.case.question,
        horizon=pack.case.horizon,
        status=ResearchCaseStatus.RUNNING,
        created_at=datetime(2026, 3, 6, 7, tzinfo=UTC),
        closed_at=None,
    )
    run = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack.pack_id,
        runner_key="jiuwenswarm-runner-v1",
        playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=datetime(2026, 3, 6, 7, 6, tzinfo=UTC))
    playbook = ResearchPlaybook(
        playbook_key=_PLAYBOOK_KEY,
        playbook_version=_PLAYBOOK_VERSION,
    )
    return build_request(
        case=case,
        run=run,
        evidence_pack=pack,
        playbook=playbook,
        adapter_version=_ADAPTER_VERSION,
    )


def _completed_payload(*, evidence_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
    pack = _build_pack()
    ids = evidence_ids or tuple(
        item.evidence_id for item in pack.factors if item.evidence_id is not None
    )
    return {
        "schema_version": JIUWENSWARM_SCHEMA_VERSION,
        "playbook_key": _PLAYBOOK_KEY,
        "playbook_version": _PLAYBOOK_VERSION,
        "adapter_version": _ADAPTER_VERSION,
        "model_key": "jiuwen-model-v1",
        "model_version": "jiuwen-model-v1",
        "conclusion": "Sample conclusion.",
        "risks": ["execution_risk", "data_staleness"],
        "evidence_ids": list(ids),
        "report_markdown": "# Report\n",
        "acceptance": JiuwenSwarmAcceptance.ACCEPTED.value,
    }


def _make_settings(
    tmp_path: Path,
    *,
    helper_path: Path | None = None,
    workspace: str = "jws-prod",
    mode: str = "evidence_only",
    timeout_seconds: float = 60.0,
    idle_timeout_seconds: float = 20.0,
    artifact_root: Path | None = None,
    python_executable: str | None = None,
) -> JiuwenSwarmCliSettings:
    helper = helper_path or (tmp_path / "helper.py")
    if not helper.exists():
        helper.write_text("# stub\n", encoding="utf-8")
    root = artifact_root or (tmp_path / "artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return JiuwenSwarmCliSettings(
        helper_path=helper,
        workspace=workspace,
        artifact_root=root,
        python_executable=python_executable or default_python_executable(),
        mode=mode,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Fake subprocess runner — pins every kwarg the transport passes.
# ---------------------------------------------------------------------------


@dataclass
class FakeSubprocessRunner:
    """In-memory fake for :func:`subprocess.run`.

    The fake pins the exact kwargs the production transport passes and
    returns a canned :class:`subprocess.CompletedProcess`. Tests that
    need to assert on argv / kwargs read ``calls`` directly.
    """

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    side_effect: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append({"args": args, "kwargs": dict(kwargs)})
        if self.side_effect is not None:
            raise self.side_effect
        return subprocess.CompletedProcess(
            args=list(args[0]) if args else [],
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


@dataclass
class _SummaryRunner:
    """Fake that serializes a dict summary on stdout."""

    summary: dict[str, Any]
    returncode: int = 0
    stderr: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append({"args": args, "kwargs": dict(kwargs)})
        return subprocess.CompletedProcess(
            args=list(args[0]) if args else [],
            returncode=self.returncode,
            stdout=json.dumps(self.summary),
            stderr=self.stderr,
        )


@dataclass
class _EchoingSummaryRunner:
    """Fake whose summary ``request_id`` mirrors the transport's argv.

    The transport echoes ``--request-id`` from the request onto the
    helper invocation; this fake mirrors that flag back into the
    stdout summary so the transport's identity-pair validator passes
    even when the test constructs a fresh request inside the runner.
    """

    base_summary: dict[str, Any]
    returncode: int = 0
    stderr: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append({"args": args, "kwargs": dict(kwargs)})
        argv = list(args[0]) if args else []
        request_id = ""
        for index, token in enumerate(argv):
            if token == "--request-id" and index + 1 < len(argv):
                request_id = argv[index + 1]
                break
        summary = dict(self.base_summary)
        summary["request_id"] = request_id
        return subprocess.CompletedProcess(
            args=argv,
            returncode=self.returncode,
            stdout=json.dumps(summary),
            stderr=self.stderr,
        )


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class JiuwenSwarmCliSettingsTest(unittest.TestCase):
    """The seven explicit fields with validation."""

    def test_default_construction(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
        self.assertTrue(settings.helper_path.is_absolute())
        self.assertEqual(settings.workspace, "jws-prod")
        self.assertTrue(settings.artifact_root.is_absolute())
        self.assertEqual(settings.python_executable, default_python_executable())
        self.assertEqual(settings.mode, "evidence_only")
        self.assertEqual(settings.timeout_seconds, 60.0)
        self.assertEqual(settings.idle_timeout_seconds, 20.0)

    def test_redacted_dict_omits_secrets(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
        redacted = settings.redacted_dict()
        for key in (
            "helper_path",
            "workspace",
            "artifact_root",
            "python_executable",
            "mode",
            "timeout_seconds",
            "idle_timeout_seconds",
        ):
            self.assertIn(key, redacted)

    def test_relative_paths_rejected(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(ValueError):
                JiuwenSwarmCliSettings(
                    helper_path=Path("helper.py"),
                    workspace="jws",
                    artifact_root=tmp / "artifacts",
                    python_executable="python",
                    mode="evidence_only",
                )
            with self.assertRaises(ValueError):
                JiuwenSwarmCliSettings(
                    helper_path=(tmp / "helper.py").resolve(),
                    workspace="jws",
                    artifact_root=Path("artifacts"),
                    python_executable="python",
                    mode="evidence_only",
                )

    def test_blank_strings_rejected(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(ValueError):
                JiuwenSwarmCliSettings(
                    helper_path=tmp / "h.py",
                    workspace="",
                    artifact_root=tmp / "artifacts",
                    python_executable="python",
                    mode="evidence_only",
                )
            with self.assertRaises(ValueError):
                JiuwenSwarmCliSettings(
                    helper_path=tmp / "h.py",
                    workspace="jws",
                    artifact_root=tmp / "artifacts",
                    python_executable="",
                    mode="evidence_only",
                )
            with self.assertRaises(ValueError):
                JiuwenSwarmCliSettings(
                    helper_path=tmp / "h.py",
                    workspace="jws",
                    artifact_root=tmp / "artifacts",
                    python_executable="python",
                    mode="",
                )

    def test_timeout_bounds(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(ValueError):
                _make_settings(tmp, timeout_seconds=0.0)
            with self.assertRaises(ValueError):
                _make_settings(tmp, timeout_seconds=3600.0 + 1.0)
            with self.assertRaises(ValueError):
                _make_settings(tmp, idle_timeout_seconds=0.0)


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class JiuwenSwarmPromptTest(unittest.TestCase):
    """The deterministic prompt text forbids every Slice 2 boundary."""

    def test_prompt_embeds_request_to_json_verbatim(self) -> None:
        request = _running_request()
        text = build_prompt_text(request)
        self.assertIn(request.to_json(), text)
        self.assertIn("REQUEST_JSON:", text)

    def test_prompt_is_deterministic(self) -> None:
        request = _running_request()
        self.assertEqual(build_prompt_text(request), build_prompt_text(request))

    def test_prompt_forbids_filesystem_and_external_data(self) -> None:
        text = build_prompt_text(_running_request())
        lowered = text.lower()
        self.assertIn("filesystem", lowered)
        self.assertIn("workspace", lowered)
        self.assertIn("external", lowered)

    def test_prompt_forbids_unsupported_facts_and_requires_unknown(self) -> None:
        text = build_prompt_text(_running_request())
        self.assertIn("unknown", text)
        self.assertIn("Do NOT invent", text)

    def test_prompt_forbids_unprovided_indicators_and_levels(self) -> None:
        text = build_prompt_text(_running_request())
        self.assertIn("indicators", text)
        self.assertIn("levels", text)

    def test_prompt_forbids_buy_sell_position_advice(self) -> None:
        text = build_prompt_text(_running_request())
        lowered = text.lower()
        for forbidden in ("buy/sell", "position sizing", "entry/exit"):
            self.assertIn(forbidden, lowered)

    def test_prompt_requires_evidence_id_whitelist(self) -> None:
        text = build_prompt_text(_running_request())
        self.assertIn("evidence_ids", text)
        self.assertIn("MUST cite one of the", text)

    def test_prompt_rejects_non_request_input(self) -> None:
        with self.assertRaises(TypeError):
            build_prompt_text("not a request")


# ---------------------------------------------------------------------------
# Subprocess transport tests
# ---------------------------------------------------------------------------


class JiuwenSwarmCliTransportArgvTest(unittest.TestCase):
    """The transport pins the exact helper CLI argv and kwargs."""

    def test_argv_pins_exact_helper_contract(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            request = _running_request()
            fake = _SummaryRunner(
                summary={
                    "status": "timed_out",
                    "session_id": "sess-1",
                    "request_id": request.request_id,
                },
            )
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "fixed-session-key",
            )
            transport.submit(request)

        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        argv = call["args"][0]
        expected = [
            settings.python_executable,
            str(settings.helper_path),
            "run",
            "--transport", "gateway",
            "--task-file", str(settings.artifact_root.resolve() / request.request_id / "task.txt"),
            "--mode", settings.mode,
            "--session-key", "fixed-session-key",
            "--workspace", settings.workspace,
            "--request-id", request.request_id,
            "--output-dir", str(settings.artifact_root.resolve() / request.request_id),
            "--timeout", "60",
            "--idle-timeout", "20",
        ]
        self.assertEqual(argv, expected)

    def test_subprocess_kwargs_are_pinned(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            request = _running_request()
            fake = _SummaryRunner(
                summary={
                    "status": "timed_out",
                    "session_id": "sess-1",
                    "request_id": request.request_id,
                },
            )
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "fixed-session-key",
            )
            transport.submit(request)

        kwargs = fake.calls[0]["kwargs"]
        self.assertEqual(kwargs["shell"], False)
        self.assertEqual(kwargs["capture_output"], True)
        self.assertEqual(kwargs["text"], True)
        self.assertEqual(kwargs["check"], False)
        self.assertEqual(kwargs["timeout"], 60.0 + 30.0)

    def test_task_file_is_plain_prompt_text(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            request = _running_request()
            fake = _SummaryRunner(
                summary={
                    "status": "timed_out",
                    "session_id": "sess-1",
                    "request_id": request.request_id,
                },
            )
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "s",
            )
            transport.submit(request)
            task_path = settings.artifact_root.resolve() / request.request_id / "task.txt"
            self.assertTrue(task_path.is_file())
            text = task_path.read_text(encoding="utf-8")
            self.assertEqual(text, build_prompt_text(request))
            # Plain text, not a JSON wrapper.
            self.assertFalse(text.lstrip().startswith("{"))


# ---------------------------------------------------------------------------
# Status / error mapping
# ---------------------------------------------------------------------------


class JiuwenSwarmCliTransportStatusMappingTest(unittest.TestCase):
    """Status / error mapping for every branch in the Slice 2 spec."""

    def _submit_with_summary(
        self,
        tmp: Path,
        summary: dict[str, Any],
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> JiuwenSwarmCliGatewayTransport:
        settings = _make_settings(tmp)
        if summary:
            fake: Any = _SummaryRunner(
                summary=summary, returncode=returncode, stderr=stderr
            )
        else:
            fake = FakeSubprocessRunner(
                returncode=returncode,
                stdout="",
                stderr=stderr,
            )
        return JiuwenSwarmCliGatewayTransport(
            settings=settings,
            runner=fake,
            session_key_factory=lambda: "sess-fixed",
        )

    def test_succeeded_maps_to_accepted_with_result_payload(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            payload = _completed_payload()
            (tmp / "artifacts").mkdir(parents=True, exist_ok=True)
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-ok",
                    "request_id": request.request_id,
                },
            )
            result_path = (
                tmp / "artifacts" / request.request_id / "result.md"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            result = transport.submit(request)

        self.assertEqual(result.acceptance, JiuwenSwarmAcceptance.ACCEPTED)
        self.assertEqual(result.session_id, "sess-ok")
        self.assertEqual(result.request_id, request.request_id)
        self.assertIsInstance(result.raw_payload, Mapping)
        self.assertEqual(
            json.loads(json.dumps(dict(result.raw_payload))),
            payload,
        )

    def test_succeeded_completion_is_coerceable(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            payload = _completed_payload()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-ok",
                    "request_id": request.request_id,
                },
            )
            result_path = (
                tmp / "artifacts" / request.request_id / "result.md"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            result = transport.submit(request)

        completion = coerce_completion(result.raw_payload)
        self.assertIsInstance(completion, JiuwenSwarmCompletion)
        self.assertEqual(completion.acceptance, JiuwenSwarmAcceptance.ACCEPTED)

    def test_timed_out_maps_to_uncertain_timeout(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "timed_out",
                    "session_id": "sess-timeout",
                    "request_id": request.request_id,
                },
            )
            result = transport.submit(request)

        self.assertEqual(result.acceptance, JiuwenSwarmAcceptance.UNCERTAIN_TIMEOUT)
        self.assertEqual(result.session_id, "sess-timeout")
        self.assertEqual(result.request_id, request.request_id)
        self.assertIsNone(result.raw_payload)

    def test_needs_input_maps_to_rejected(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "needs_input",
                    "session_id": "sess-input",
                    "request_id": request.request_id,
                },
            )
            result = transport.submit(request)

        self.assertEqual(result.acceptance, JiuwenSwarmAcceptance.REJECTED)
        self.assertEqual(result.session_id, "sess-input")
        self.assertIsNone(result.raw_payload)

    def test_failed_status_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "failed",
                    "session_id": "sess-failed",
                    "request_id": request.request_id,
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_process_error_status_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "process_error",
                    "session_id": "sess-process",
                    "request_id": request.request_id,
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_unknown_status_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "totally-bogus",
                    "session_id": "sess-x",
                    "request_id": request.request_id,
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_non_zero_return_code_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp, {}, returncode=2, stderr="boom"
            )
            with self.assertRaises(JiuwenSwarmTransportError) as ctx:
                transport.submit(request)
        message = str(ctx.exception)
        self.assertIn("returncode=2", message)
        self.assertIn("'boom'", message)

    def test_timed_out_with_nonzero_returncode_maps_to_uncertain_timeout(
        self,
    ) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "timed_out",
                    "session_id": "sess-timeout-rc2",
                    "request_id": request.request_id,
                },
                returncode=2,
                stderr="helper watchdog fired",
            )
            result = transport.submit(request)

        self.assertEqual(
            result.acceptance, JiuwenSwarmAcceptance.UNCERTAIN_TIMEOUT
        )
        self.assertEqual(result.session_id, "sess-timeout-rc2")
        self.assertEqual(result.request_id, request.request_id)
        self.assertIsNone(result.raw_payload)

    def test_failed_with_nonzero_returncode_raises_transport_error(
        self,
    ) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "failed",
                    "session_id": "sess-failed-rc2",
                    "request_id": request.request_id,
                },
                returncode=2,
                stderr="helper exploded",
            )
            with self.assertRaises(JiuwenSwarmTransportError) as ctx:
                transport.submit(request)
        message = str(ctx.exception)
        self.assertIn("'failed'", message)
        self.assertIn("sess-failed-rc2", message)
        self.assertIn("returncode=2", message)

    def test_succeeded_with_nonzero_returncode_raises_transport_error(
        self,
    ) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-contradict",
                    "request_id": request.request_id,
                },
                returncode=3,
                stderr="contradictory trace",
            )
            with self.assertRaises(JiuwenSwarmTransportError) as ctx:
                transport.submit(request)
        message = str(ctx.exception)
        self.assertIn("'succeeded'", message)
        self.assertIn("contradictory", message)
        self.assertIn("returncode 3", message)

    def test_subprocess_timeout_expired_raises_transport_error(
        self,
    ) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            request = _running_request()
            fake = FakeSubprocessRunner(
                side_effect=subprocess.TimeoutExpired(
                    cmd=["helper"], timeout=90.0
                )
            )
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "s",
            )
            with self.assertRaises(JiuwenSwarmTransportError) as ctx:
                transport.submit(request)
        message = str(ctx.exception).lower()
        self.assertIn("timeout", message)
        self.assertIn("uncertain", message)
        self.assertNotIn("session_id=", message)
        self.assertNotIn("sess-", message)

    def test_missing_result_md_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-ok",
                    "request_id": request.request_id,
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_malformed_result_json_raises_malformed_result_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-ok",
                    "request_id": request.request_id,
                },
            )
            result_path = (
                tmp / "artifacts" / request.request_id / "result.md"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text("not json at all", encoding="utf-8")
            with self.assertRaises(JiuwenSwarmMalformedResultError):
                transport.submit(request)

    def test_non_object_result_json_raises_malformed_result_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "succeeded",
                    "session_id": "sess-ok",
                    "request_id": request.request_id,
                },
            )
            result_path = (
                tmp / "artifacts" / request.request_id / "result.md"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(JiuwenSwarmMalformedResultError):
                transport.submit(request)

    def test_summary_request_id_mismatch_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "timed_out",
                    "session_id": "sess",
                    "request_id": "not-the-same-id",
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_blank_session_id_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            transport = self._submit_with_summary(
                tmp,
                {
                    "status": "timed_out",
                    "session_id": "",
                    "request_id": request.request_id,
                },
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_invalid_summary_json_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            settings = _make_settings(tmp)
            fake = FakeSubprocessRunner(stdout="not json at all")
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "s",
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_non_object_summary_raises_transport_error(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            settings = _make_settings(tmp)
            fake = FakeSubprocessRunner(stdout="[1, 2, 3]")
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "s",
            )
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)


# ---------------------------------------------------------------------------
# Path traversal, artifact preservation, runner integration
# ---------------------------------------------------------------------------


class JiuwenSwarmCliTransportSafetyTest(unittest.TestCase):
    """Path traversal, artifact preservation, and runner integration."""

    def test_artifact_dir_rejects_separator_in_request_id(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=FakeSubprocessRunner(),
                session_key_factory=lambda: "s",
            )
            request = _running_request()
            object.__setattr__(request, "request_id", "abc/../escape")
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_artifact_dir_rejects_traversal_prefix(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=FakeSubprocessRunner(),
                session_key_factory=lambda: "s",
            )
            request = _running_request()
            object.__setattr__(request, "request_id", "..")
            with self.assertRaises(JiuwenSwarmTransportError):
                transport.submit(request)

    def test_artifacts_preserved_after_run(self) -> None:
        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            request = _running_request()
            settings = _make_settings(tmp)
            payload = _completed_payload()
            result_path = (
                tmp / "artifacts" / request.request_id / "result.md"
            )
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            fake = _SummaryRunner(
                summary={
                    "status": "succeeded",
                    "session_id": "sess",
                    "request_id": request.request_id,
                }
            )
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "s",
            )
            transport.submit(request)
            task_path = settings.artifact_root / request.request_id / "task.txt"
            self.assertTrue(task_path.is_file())
            self.assertTrue(result_path.is_file())

    def test_runner_wires_transport_into_research_runner(self) -> None:
        captured_request_id: dict[str, str] = {}
        settings_holder: dict[str, JiuwenSwarmCliSettings] = {}
        payload = _completed_payload()

        class WriteBeforeSummaryRunner:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
                argv = list(args[0]) if args else []
                self.calls.append({"args": args, "kwargs": dict(kwargs)})
                request_id = ""
                for index, token in enumerate(argv):
                    if token == "--request-id" and index + 1 < len(argv):
                        request_id = argv[index + 1]
                        break
                captured_request_id["value"] = request_id
                settings = settings_holder["value"]
                result_path = (
                    settings.artifact_root.resolve() / request_id / "result.md"
                )
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text(json.dumps(payload), encoding="utf-8")
                summary = {
                    "status": "succeeded",
                    "session_id": "sess-integ",
                    "request_id": request_id,
                }
                return subprocess.CompletedProcess(
                    args=argv, returncode=0, stdout=json.dumps(summary), stderr=""
                )

        with __import__("tempfile").TemporaryDirectory() as td:
            tmp = Path(td)
            settings = _make_settings(tmp)
            settings_holder["value"] = settings
            fake = WriteBeforeSummaryRunner()
            transport = JiuwenSwarmCliGatewayTransport(
                settings=settings,
                runner=fake,
                session_key_factory=lambda: "sess-integ",
            )
            runner = JiuwenSwarmResearchRunner(
                transport=transport, adapter_version=_ADAPTER_VERSION
            )
            case = ResearchCase(
                case_id=_CASE_ID,
                instrument_id=InstrumentId(_INSTRUMENT_ID.value),
                as_of_date=_AS_OF,
                question=_QUESTION,
                horizon=_HORIZON,
                status=ResearchCaseStatus.RUNNING,
                created_at=datetime(2026, 3, 6, 7, tzinfo=UTC),
                closed_at=None,
            )
            run = ResearchRun.create(
                case_id=case.case_id,
                evidence_pack_id=_PACK_ID,
                runner_key="jiuwenswarm-runner-v1",
                playbook_key=_PLAYBOOK_KEY,
            ).start(occurred_at=datetime(2026, 3, 6, 7, 6, tzinfo=UTC))
            draft = runner.run(
                case=case,
                run=run,
                evidence_pack=_build_pack(),
                playbook=ResearchPlaybook(
                    playbook_key=_PLAYBOOK_KEY,
                    playbook_version=_PLAYBOOK_VERSION,
                ),
                started_at=datetime(2026, 3, 6, 7, 6, tzinfo=UTC),
            )
        self.assertEqual(draft.adapter_version, _ADAPTER_VERSION)


if __name__ == "__main__":
    unittest.main()
