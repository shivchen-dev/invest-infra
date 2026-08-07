"""PR-6 JiuwenSwarm adapter — Slice 1 tests.

These tests cover the Slice 1 deliverable: the
:mod:`invest_pipeline.adapters.jiuwenswarm` package boundary.

Coverage targets (the slice spec is explicit on each):

- :class:`JiuwenSwarmResearchRunner` satisfies
  :class:`invest_domain.research.runner.ResearchRunner`.
- The request mapper is deterministic and never leaks workspace path,
  credentials, or runtime lineage metadata
  (``pipeline_run_id`` / ``e2a_request_id`` / ``e2a_session_id`` /
  ``generated_at``) into the wire payload; factor values, source
  references, the case question, ``pack_id``, ``pack_hash``, and
  per-factor ``evidence_id`` *are* forwarded so the gateway can
  ground citations.
- The result mapper returns a :class:`ResearchRunnerDraft` that domain
  completion accepts.
- The schema validator rejects malformed payloads
  (``JiuwenSwarmMalformedResultError``).
- The transport's remote failure raises
  :class:`JiuwenSwarmRemoteFailureError`.
- The "accepted but locally timed out" classification surfaces
  :class:`JiuwenSwarmTimeoutUncertainError`.
- The transport is called exactly once per ``runner.run``.

The slice ships no real WebSocket / network transport; tests inject a
fake :class:`JiuwenSwarmGatewayTransport`.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

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
    ResearchRunner,
    ResearchRunnerDraft,
    SourceReference,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import ResearchRun
from invest_pipeline.adapters.jiuwenswarm import (
    JIUWENSWARM_SCHEMA_VERSION,
    JiuwenSwarmAcceptance,
    JiuwenSwarmCompletion,
    JiuwenSwarmGatewayRequest,
    JiuwenSwarmMalformedResultError,
    JiuwenSwarmRemoteFailureError,
    JiuwenSwarmResearchRunner,
    JiuwenSwarmTimeoutUncertainError,
    JiuwenSwarmTransportResult,
    build_draft,
    build_request,
    coerce_completion,
    to_json,
)

# ---------------------------------------------------------------------------
# Helpers — minimal valid EvidencePack built inline so the test does not
# depend on the domain test fixtures.
# ---------------------------------------------------------------------------

_INSTRUMENT_ID = InstrumentId(UUID("11111111-1114-4118-9111-111111111111"))
_PACK_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_AS_OF = date(2026, 3, 6)
_QUESTION = "评估该 ETF 当前市场状态与未来 20-60 个交易日主要风险"
_HORIZON = "20-60d"
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)


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


def _build_pack(
    *,
    case_id: UUID | None = None,
    pack_id: UUID | None = None,
    workspace_path: str | None = "/runtime/workspace/jiuwenswarm",
) -> EvidencePack:
    effective_case_id = case_id or UUID("22222222-2224-4228-9222-222222222222")
    effective_pack_id = pack_id or _PACK_ID
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
            case_id=effective_case_id,
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
        pack_id=effective_pack_id,
        pipeline_run_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        e2a_request_id="req-runtime-jws",
        e2a_session_id="sess-runtime-jws",
        generated_at=datetime(2026, 3, 6, 9, tzinfo=UTC),
        workspace_path=workspace_path,
    )


def _running_case_and_run(
    *,
    case_id: UUID | None = None,
    pack_id: UUID | None = None,
) -> tuple[ResearchCase, ResearchRun, EvidencePack]:
    pack = _build_pack(case_id=case_id, pack_id=pack_id)
    case_id_for_pack = pack.case.case_id
    if not isinstance(case_id_for_pack, UUID):
        raise ValueError("case_id must be a UUID")
    created = datetime(2026, 3, 6, 7, tzinfo=UTC)
    ready_at = created + timedelta(minutes=5)
    running_at = ready_at + timedelta(minutes=1)
    case = (
        ResearchCase(
            case_id=case_id_for_pack,
            instrument_id=pack.instrument.instrument_id,
            as_of_date=pack.case.as_of_date,
            question=pack.case.question,
            horizon=pack.case.horizon,
            status=ResearchCaseStatus.DRAFT,
            created_at=created,
            closed_at=None,
        )
        .transition(ResearchCaseStatus.READY, occurred_at=ready_at)
        .transition(ResearchCaseStatus.RUNNING, occurred_at=running_at)
    )
    run = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack.pack_id,
        runner_key="jiuwenswarm-runner-v1",
        playbook_key=_PLAYBOOK_KEY,
    ).start(occurred_at=running_at)
    return case, run, pack


_PLAYBOOK_KEY = "etf_medium_term_assessment"
_PLAYBOOK_VERSION = "v0.1.0"
_ADAPTER_VERSION = "jiuwenswarm-adapter-v1"
_STARTED_AT = datetime(2026, 3, 6, 7, 6, tzinfo=UTC)


def _playbook() -> ResearchPlaybook:
    return ResearchPlaybook(
        playbook_key=_PLAYBOOK_KEY,
        playbook_version=_PLAYBOOK_VERSION,
    )


def _completed_payload(
    *,
    evidence_ids: tuple[str, ...] | None = None,
    adapter_version: str = _ADAPTER_VERSION,
) -> dict[str, Any]:
    pack = _build_pack()
    ids = evidence_ids or tuple(
        item.evidence_id for item in pack.factors if item.evidence_id is not None
    )
    return {
        "schema_version": JIUWENSWARM_SCHEMA_VERSION,
        "playbook_key": _PLAYBOOK_KEY,
        "playbook_version": _PLAYBOOK_VERSION,
        "adapter_version": adapter_version,
        "model_key": "jiuwen-model-v1",
        "model_version": "jiuwen-model-v1",
        "conclusion": "Sample conclusion.",
        "risks": ["execution_risk", "data_staleness"],
        "evidence_ids": list(ids),
        "report_markdown": "# Report\n",
        "acceptance": JiuwenSwarmAcceptance.ACCEPTED.value,
    }


@dataclass
class FakeTransport:
    """In-memory test fake for :class:`JiuwenSwarmGatewayTransport`."""

    per_request_response: dict[int, JiuwenSwarmTransportResult] = field(
        default_factory=dict
    )
    raise_from_call: Exception | None = None
    return_uncertain_timeout: bool = False
    return_remote_failure: bool = False
    calls: list[JiuwenSwarmGatewayRequest] = field(default_factory=list)
    last_result: JiuwenSwarmTransportResult | None = None

    def submit(
        self, request: JiuwenSwarmGatewayRequest
    ) -> JiuwenSwarmTransportResult:
        self.calls.append(request)
        if self.raise_from_call is not None:
            raise self.raise_from_call
        if self.return_uncertain_timeout:
            self.last_result = JiuwenSwarmTransportResult(
                request_id=request.request_id,
                session_id="session-uncertain",
                acceptance=JiuwenSwarmAcceptance.UNCERTAIN_TIMEOUT,
                raw_payload=None,
            )
            return self.last_result
        if self.return_remote_failure:
            self.last_result = JiuwenSwarmTransportResult(
                request_id=request.request_id,
                session_id="session-failed",
                acceptance=JiuwenSwarmAcceptance.REJECTED,
                raw_payload={"reason": "upstream_error"},
            )
            return self.last_result
        if id(request) in self.per_request_response:
            self.last_result = self.per_request_response[id(request)]
            return self.last_result
        self.last_result = JiuwenSwarmTransportResult(
            request_id=request.request_id,
            session_id="session-default",
            acceptance=JiuwenSwarmAcceptance.ACCEPTED,
            raw_payload=_completed_payload(),
        )
        return self.last_result


class RunnerProtocolSatisfactionTest(unittest.TestCase):
    """The adapter must satisfy the domain :class:`ResearchRunner` port."""

    def test_runner_satisfies_protocol(self) -> None:
        runner = JiuwenSwarmResearchRunner(
            transport=FakeTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        self.assertIsInstance(runner, ResearchRunner)
        self.assertEqual(runner.runner_key, "jiuwenswarm-runner-v1")
        self.assertEqual(runner.adapter_version, _ADAPTER_VERSION)


class RequestMappingTest(unittest.TestCase):
    """The deterministic request mapper and its metadata discipline."""

    def test_request_carries_case_run_pack_and_playbook_versions(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        self.assertEqual(request.schema_version, JIUWENSWARM_SCHEMA_VERSION)
        self.assertEqual(request.case_id, case.case_id)
        self.assertEqual(request.run_id, run.run_id)
        self.assertEqual(request.evidence_pack_id, pack.pack_id)
        self.assertEqual(request.playbook_key, _PLAYBOOK_KEY)
        self.assertEqual(request.playbook_version, _PLAYBOOK_VERSION)
        self.assertEqual(request.adapter_version, _ADAPTER_VERSION)
        self.assertEqual(request.evidence_ids, tuple(
            item.evidence_id for item in pack.factors if item.evidence_id is not None
        ))
        # Case business facts are pinned on the request so the gateway
        # can reconcile without depending on lifecycle state.
        self.assertEqual(
            request.case_instrument_id,
            case.instrument_id.value,
        )
        self.assertEqual(request.case_as_of_date, case.as_of_date.isoformat())
        self.assertEqual(request.case_question, case.question)
        self.assertEqual(request.case_horizon, case.horizon)

    def test_request_is_deterministic_under_same_inputs(self) -> None:
        case, run, pack = _running_case_and_run()
        first = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        second = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(first.to_json(), second.to_json())

    def test_request_payload_carries_projection_question_source_refs_factors(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        payload = request.payload
        self.assertEqual(payload["compatibility_mode"], "evidence_only")
        self.assertEqual(payload["context"], {"status": "not_bound"})
        self.assertEqual(payload["case"]["question"], _QUESTION)
        self.assertEqual(
            payload["playbook"],
            {"key": _PLAYBOOK_KEY, "version": _PLAYBOOK_VERSION},
        )
        # ``pack_content_projection`` exposes the deterministic
        # content-only projection (factor values, source_refs, schema
        # version, etc.) so the gateway can ground every output in
        # evidence; the mapper then layers ``pack_id`` /
        # ``pack_hash`` and per-factor ``evidence_id`` on top so the
        # gateway can echo citations back as a whitelist.
        self.assertEqual(payload["evidence_pack"]["schema_version"], SCHEMA_VERSION)
        factor_values = {
            item["factor_key"]: item["value"]
            for item in payload["evidence_pack"]["factors"]
        }
        self.assertIn("return_20d", factor_values)
        self.assertGreater(len(factor_values), 0)
        source_refs = payload["evidence_pack"]["source_refs"]
        self.assertGreater(len(source_refs), 0)
        self.assertEqual(
            {item["source_kind"] for item in source_refs},
            {"daily_bar", "instrument"},
        )

    def test_request_payload_omits_secrets_and_adapter_runtime_metadata(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        # JSON-encode so we can scan every nested value, not only the
        # top-level keys, for forbidden tokens.
        serialized = request.to_json()
        for forbidden in (
            "api_key",
            "apikey",
            "secret",
            "password",
            "token",
            "credentials",
        ):
            self.assertNotIn(forbidden, serialized)
        # Adapter-level runtime metadata (the runner's clock, the live
        # session state, the local workspace path the gateway has no
        # need for) must not appear in the wire payload. The
        # evidence_pack projection in this slice is built from
        # ``pack_content_projection`` plus explicit citation keys; it
        # does *not* forward ``workspace_path`` /
        # ``pipeline_run_id`` / ``e2a_request_id`` /
        # ``e2a_session_id`` / ``generated_at`` because those belong
        # to the ingestion pipeline and would force the domain
        # completion gate to reject the completion.
        for forbidden in ("clock", "session_state", "local_state"):
            self.assertNotIn(forbidden, serialized)

    def test_request_payload_exposes_pack_id_pack_hash_and_factor_evidence_ids(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        projection = request.payload["evidence_pack"]
        # ``pack_id`` and ``pack_hash`` are added on top of the
        # ``pack_content_projection`` so the gateway can reconcile the
        # completion against the originating pack.
        self.assertEqual(projection["pack_id"], str(pack.pack_id))
        self.assertEqual(projection["pack_hash"], pack.pack_hash)
        # Per-factor ``evidence_id`` values are required for citation
        # round-tripping; the mapper must copy every non-null
        # ``evidence_id`` from the FactorObservation list.
        factor_ids = {
            item["factor_key"]: item["evidence_id"] for item in projection["factors"]
        }
        whitelist_ids = {
            item.factor_key: item.evidence_id
            for item in pack.factors
            if item.evidence_id is not None
        }
        self.assertGreater(len(factor_ids), 0)
        self.assertEqual(factor_ids, whitelist_ids)
        # Every factor evidence_id must be a non-blank string.
        self.assertTrue(all(value for value in factor_ids.values()))

    def test_request_payload_omits_ingestion_lineage_fields(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        serialized = request.to_json()
        # Ingestion-pipeline lineage fields stored on the
        # ``EvidencePack`` (workspace path, pipeline run, e2a
        # request/session, generated_at) MUST NOT appear anywhere in
        # the gateway request — they belong to storage / audit, not
        # to the agent's research context.
        for forbidden in (
            "workspace_path",
            "pipeline_run_id",
            "e2a_request_id",
            "e2a_session_id",
            "generated_at",
        ):
            self.assertNotIn(forbidden, serialized)
        # Belt-and-braces: walk the JSON-encoded payload mapping so a
        # future projection addition (or a nested encoder bug) cannot
        # leak those exact key names by accident.
        self.assertNotIn("workspace_path", request.payload["evidence_pack"])
        self.assertNotIn("pipeline_run_id", request.payload["evidence_pack"])
        self.assertNotIn("e2a_request_id", request.payload["evidence_pack"])
        self.assertNotIn("e2a_session_id", request.payload["evidence_pack"])
        self.assertNotIn("generated_at", request.payload["evidence_pack"])

    def test_request_payload_is_frozen_and_immutable(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        self.assertIsInstance(request.payload, MappingProxyType)
        self.assertIsInstance(request.payload["evidence_pack"], MappingProxyType)
        self.assertIsInstance(request.payload["case"], MappingProxyType)
        self.assertIsInstance(request.payload["playbook"], MappingProxyType)
        with self.assertRaises(TypeError):
            request.payload["compatibility_mode"] = "tampered"  # type: ignore[index]
        with self.assertRaises(TypeError):
            request.payload["evidence_pack"]["schema_version"] = "tampered"  # type: ignore[index]

    def test_request_to_json_is_deterministic(self) -> None:
        case, run, pack = _running_case_and_run()
        request = build_request(
            case=case, run=run, evidence_pack=pack, playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
        )
        first = request.to_json()
        second = request.to_json()
        self.assertEqual(first, second)
        # UUID and tuple values survive the canonical encoder.
        self.assertIn(str(case.case_id), first)
        self.assertIn(str(case.instrument_id.value), first)

    def test_request_rejects_misaligned_evidence_pack(self) -> None:
        case, run, pack = _running_case_and_run()
        mismatched = replace(run, evidence_pack_id=uuid4())
        with self.assertRaises(ValueError):
            build_request(
                case=case, run=mismatched, evidence_pack=pack,
                playbook=_playbook(), adapter_version=_ADAPTER_VERSION,
            )

    def test_request_rejects_misaligned_run_case_id(self) -> None:
        case, run, pack = _running_case_and_run()
        mismatched = replace(run, case_id=uuid4())
        with self.assertRaises(ValueError):
            build_request(
                case=case, run=mismatched, evidence_pack=pack,
                playbook=_playbook(), adapter_version=_ADAPTER_VERSION,
            )

    def test_request_rejects_misaligned_case_instrument(self) -> None:
        case, run, pack = _running_case_and_run()
        mismatched = replace(case, instrument_id=InstrumentId(uuid4()))
        with self.assertRaises(ValueError):
            build_request(
                case=mismatched, run=run, evidence_pack=pack,
                playbook=_playbook(), adapter_version=_ADAPTER_VERSION,
            )

    def test_request_rejects_misaligned_case_question(self) -> None:
        case, run, pack = _running_case_and_run()
        mismatched = replace(case, question="完全不同的研究问题描述")
        with self.assertRaises(ValueError):
            build_request(
                case=mismatched, run=run, evidence_pack=pack,
                playbook=_playbook(), adapter_version=_ADAPTER_VERSION,
            )

    def test_request_rejects_non_running_run(self) -> None:
        case, run, pack = _running_case_and_run()
        queued = ResearchRun.create(
            case_id=run.case_id,
            evidence_pack_id=run.evidence_pack_id,
            runner_key=run.runner_key,
            playbook_key=run.playbook_key,
        )
        with self.assertRaises(ValueError):
            build_request(
                case=case, run=queued, evidence_pack=pack,
                playbook=_playbook(), adapter_version=_ADAPTER_VERSION,
            )


class CompletionMappingTest(unittest.TestCase):
    """The validated completion → draft mapper contract."""

    def test_completion_is_built_from_valid_payload(self) -> None:
        completion = coerce_completion(_completed_payload())
        self.assertIsInstance(completion, JiuwenSwarmCompletion)
        self.assertEqual(completion.acceptance, JiuwenSwarmAcceptance.ACCEPTED)
        self.assertEqual(completion.playbook_key, _PLAYBOOK_KEY)
        self.assertEqual(completion.playbook_version, _PLAYBOOK_VERSION)

    def test_invalid_schema_raises_malformed_result(self) -> None:
        bad = _completed_payload()
        bad["schema_version"] = "999.0.0"
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            coerce_completion(bad)

    def test_missing_evidence_ids_raises_malformed_result(self) -> None:
        bad = _completed_payload()
        bad["evidence_ids"] = []
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            coerce_completion(bad)

    def test_malformed_acceptance_enum_raises_malformed_result(self) -> None:
        bad = _completed_payload()
        bad["acceptance"] = "totally-unknown"
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            coerce_completion(bad)

    def test_wrong_field_types_raise_malformed_result(self) -> None:
        bad = _completed_payload()
        bad["evidence_ids"] = "not-a-list"
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            coerce_completion(bad)

    def test_draft_carries_evidence_ids_and_versions(self) -> None:
        pack = _build_pack()
        completion = coerce_completion(_completed_payload())
        draft = build_draft(
            completion=completion,
            playbook=_playbook(),
            adapter_version=_ADAPTER_VERSION,
            now=_STARTED_AT,
        )
        self.assertIsInstance(draft, ResearchRunnerDraft)
        self.assertEqual(draft.adapter_version, _ADAPTER_VERSION)
        self.assertEqual(draft.playbook_version, _PLAYBOOK_VERSION)
        self.assertEqual(
            draft.evidence_ids,
            tuple(
                sorted(
                    item.evidence_id for item in pack.factors
                    if item.evidence_id is not None
                )
            ),
        )


class RunnerRunTest(unittest.TestCase):
    """End-to-end :meth:`JiuwenSwarmResearchRunner.run` behaviour."""

    def test_run_returns_draft_for_accepted_completion(self) -> None:
        case, run, pack = _running_case_and_run()
        transport = FakeTransport()
        runner = JiuwenSwarmResearchRunner(
            transport=transport, adapter_version=_ADAPTER_VERSION,
        )
        draft = runner.run(
            case=case, run=run, evidence_pack=pack,
            playbook=_playbook(), started_at=_STARTED_AT,
        )
        self.assertIsInstance(draft, ResearchRunnerDraft)
        self.assertEqual(draft.adapter_version, _ADAPTER_VERSION)
        self.assertEqual(
            draft.evidence_ids,
            tuple(
                sorted(
                    item.evidence_id for item in pack.factors
                    if item.evidence_id is not None
                )
            ),
        )
        self.assertEqual(draft.model_key, "jiuwen-model-v1")
        self.assertEqual(draft.model_version, "jiuwen-model-v1")

    def test_run_calls_transport_exactly_once(self) -> None:
        case, run, pack = _running_case_and_run()
        transport = FakeTransport()
        runner = JiuwenSwarmResearchRunner(
            transport=transport, adapter_version=_ADAPTER_VERSION,
        )
        runner.run(
            case=case, run=run, evidence_pack=pack,
            playbook=_playbook(), started_at=_STARTED_AT,
        )
        self.assertEqual(len(transport.calls), 1)

    def test_run_raises_remote_failure_on_rejected_acceptance(self) -> None:
        case, run, pack = _running_case_and_run()
        transport = FakeTransport(return_remote_failure=True)
        runner = JiuwenSwarmResearchRunner(
            transport=transport, adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmRemoteFailureError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_run_raises_uncertain_timeout_when_acceptance_uncertain(self) -> None:
        case, run, pack = _running_case_and_run()
        transport = FakeTransport(return_uncertain_timeout=True)
        runner = JiuwenSwarmResearchRunner(
            transport=transport, adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmTimeoutUncertainError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_run_raises_malformed_result_for_invalid_payload(self) -> None:
        case, run, pack = _running_case_and_run()
        bad_payload = _completed_payload()
        bad_payload["schema_version"] = "0.0.0"

        class BadPayloadTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                return JiuwenSwarmTransportResult(
                    request_id=request.request_id,
                    session_id="session-bad",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=bad_payload,
                )

        runner = JiuwenSwarmResearchRunner(
            transport=BadPayloadTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_run_raises_malformed_result_when_completion_cites_unknown_evidence(self) -> None:
        case, run, pack = _running_case_and_run()
        bogus_payload = _completed_payload(
            evidence_ids=("evi:bogus:unknown:000000000000",),
        )

        class BogusTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                return JiuwenSwarmTransportResult(
                    request_id=request.request_id,
                    session_id="session-bogus",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=bogus_payload,
                )

        runner = JiuwenSwarmResearchRunner(
            transport=BogusTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_run_raises_malformed_result_when_completion_adapter_version_mismatches(self) -> None:
        case, run, pack = _running_case_and_run()
        mismatched_payload = _completed_payload(adapter_version="jiuwenswarm-adapter-v2")

        class MismatchedAdapterTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                return JiuwenSwarmTransportResult(
                    request_id=request.request_id,
                    session_id="session-adapter-mismatch",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=mismatched_payload,
                )

        runner = JiuwenSwarmResearchRunner(
            transport=MismatchedAdapterTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmMalformedResultError) as ctx:
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )
        self.assertIn("adapter_version", str(ctx.exception))

    def test_run_raises_malformed_result_for_blank_session_id(self) -> None:
        case, run, pack = _running_case_and_run()

        class BlankSessionTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                return JiuwenSwarmTransportResult(
                    request_id=request.request_id,
                    session_id="   ",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=_completed_payload(),
                )

        runner = JiuwenSwarmResearchRunner(
            transport=BlankSessionTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_run_raises_malformed_result_for_mismatched_request_id(self) -> None:
        case, run, pack = _running_case_and_run()

        class MismatchedTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                return JiuwenSwarmTransportResult(
                    request_id="not-the-same-id",
                    session_id="session-mismatch",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=_completed_payload(),
                )

        runner = JiuwenSwarmResearchRunner(
            transport=MismatchedTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        with self.assertRaises(JiuwenSwarmMalformedResultError):
            runner.run(
                case=case, run=run, evidence_pack=pack,
                playbook=_playbook(), started_at=_STARTED_AT,
            )

    def test_transport_result_preserves_request_and_session_ids(self) -> None:
        case, run, pack = _running_case_and_run()
        captured: list[tuple[str, str]] = []

        class CapturingTransport(FakeTransport):
            def submit(self, request: JiuwenSwarmGatewayRequest) -> JiuwenSwarmTransportResult:
                self.calls.append(request)
                result = JiuwenSwarmTransportResult(
                    request_id=request.request_id,
                    session_id="sess-xyz",
                    acceptance=JiuwenSwarmAcceptance.ACCEPTED,
                    raw_payload=_completed_payload(),
                )
                captured.append((result.request_id, result.session_id))
                return result

        runner = JiuwenSwarmResearchRunner(
            transport=CapturingTransport(),
            adapter_version=_ADAPTER_VERSION,
        )
        runner.run(
            case=case, run=run, evidence_pack=pack,
            playbook=_playbook(), started_at=_STARTED_AT,
        )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][1], "sess-xyz")


class DeterministicJsonTest(unittest.TestCase):
    """The deterministic JSON helper covers all wire types."""

    def test_to_json_round_trip_for_uuid_mapping_tuple(self) -> None:
        data = {
            "uuid": uuid4(),
            "name": "payload",
            "items": ("a", "b", "c"),
            "nested": {"z": 1, "a": 2},
        }
        first = to_json(data)
        second = to_json(data)
        self.assertEqual(first, second)
        # UUID values are serialized in their lowercase hex form.
        self.assertIn(str(data["uuid"]), first)
        # Tuple values are preserved as JSON arrays.
        self.assertIn('["a","b","c"]', first)


class PublicApiShapeTest(unittest.TestCase):
    """The package's public symbols must be stable and importable."""

    def test_public_symbols_are_exported(self) -> None:
        from invest_pipeline.adapters import jiuwenswarm as mod

        for name in (
            "JIUWENSWARM_SCHEMA_VERSION",
            "JiuwenSwarmAcceptance",
            "JiuwenSwarmCompletion",
            "JiuwenSwarmGatewayRequest",
            "JiuwenSwarmGatewayTransport",
            "JiuwenSwarmMalformedResultError",
            "JiuwenSwarmRemoteFailureError",
            "JiuwenSwarmResearchRunner",
            "JiuwenSwarmSchemaError",
            "JiuwenSwarmTimeoutUncertainError",
            "JiuwenSwarmTransportResult",
            "build_draft",
            "build_request",
            "coerce_completion",
            "to_json",
        ):
            self.assertTrue(
                hasattr(mod, name),
                f"missing public symbol {name!r} on jiuwenswarm",
            )


if __name__ == "__main__":
    unittest.main()