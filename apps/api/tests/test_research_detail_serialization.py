"""HTTP-seam behavior tests for the PR-7 read-only Research API.

Constructs real domain objects (``ResearchCase``, ``EvidencePack``,
``ResearchRun``, ``ResearchResult``) and exercises the real
``ResearchQueryService`` against simple stub repositories so the
``EvidencePackResponse.from_domain`` / ``ResearchRunResponse.from_domain``
/ ``ResearchResultResponse.from_domain`` schema converters run on the
canonical shapes. The JSON returned by ``TestClient`` is asserted
field-by-field against the documented public contract:

- ``factor.unit`` is present for every factor and self-described.
- ``workspace_path``, ``e2a_request_id`` and ``e2a_session_id`` are
  absent at every JSON depth.
- Domain ``None`` values are serialized as JSON ``null``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from invest_api.application.research import (
    ResearchCaseReader,
    ResearchEvidenceReader,
    ResearchQueryService,
    ResearchResultReader,
    ResearchRunReader,
)
from invest_api.dependencies import get_research_query_service
from invest_api.main import app
from invest_domain.instruments import InstrumentId
from invest_domain.market_data import Adjust, BarSource, DailyBar, TradingStatus
from invest_domain.research import (
    CaseContext,
    EvidencePack,
    InstrumentSnapshot,
    SourceReference,
    calculate_market_state_factors,
)
from invest_domain.research.research_case import ResearchCase, ResearchCaseStatus
from invest_domain.research.research_run import (
    ResearchResult,
    ResearchRun,
    ResearchRunStatus,
)

_INSTRUMENT_ID = UUID("12345678-1234-5678-9234-567812345678")
_SOURCE = BarSource(
    provider_key="fixture_dev",
    source_batch_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
    observed_at=datetime(2026, 3, 6, 8, tzinfo=UTC),
)
_QUESTION = "Assess medium-term risks for 510300"
_AS_OF = date(2026, 3, 6)
_INTERNAL_LEAKS = ("workspace_path", "e2a_request_id", "e2a_session_id")
_FACTOR_UNITS = frozenset({"ratio", "annualized_ratio", "CNY"})


def _bars(count: int) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    return tuple(
        DailyBar.build(
            instrument_id=InstrumentId(_INSTRUMENT_ID),
            trade_date=start + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            prev_close=None if index == 0 else Decimal(99 + index),
            volume=Decimal(1000 + index),
            amount=Decimal(1_000_000 + index * 1000),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=_SOURCE,
            revision=1,
        )
        for index in range(count)
    )


def _build_pack(*, case_id: UUID, pack_id: UUID) -> EvidencePack:
    calc = calculate_market_state_factors(
        _bars(65),
        as_of_date=_AS_OF,
        instrument_id=InstrumentId(_INSTRUMENT_ID),
    )
    return EvidencePack(
        case=CaseContext(
            instrument_id=InstrumentId(_INSTRUMENT_ID),
            as_of_date=_AS_OF,
            question=_QUESTION,
            case_id=case_id,
        ),
        instrument=InstrumentSnapshot(
            instrument_id=InstrumentId(_INSTRUMENT_ID),
            symbol="510300",
            name="HS300 ETF",
            exchange="SSE",
        ),
        candidate_context=None,
        market_snapshot=calc.market_snapshot,
        factors=calc.factors,
        data_quality=calc.data_quality,
        missing_fields=calc.missing_fields,
        warnings=calc.warnings,
        source_refs=(
            SourceReference(
                source_kind="daily_bar",
                source_ref="core.daily_bars:2026-03-06",
                observed_date=_AS_OF,
                revision=1,
            ),
        ),
        pack_id=pack_id,
        generated_at=datetime(2026, 3, 6, 9, tzinfo=UTC),
    )


def _build_case() -> ResearchCase:
    return ResearchCase(
        case_id=uuid4(),
        instrument_id=InstrumentId(_INSTRUMENT_ID),
        as_of_date=_AS_OF,
        question=_QUESTION,
        horizon="20-60d",
        status=ResearchCaseStatus.DRAFT,
        created_at=datetime(2026, 3, 6, 9, tzinfo=UTC),
    )


def _build_run(case: ResearchCase, pack_id: UUID) -> ResearchRun:
    queued = ResearchRun.create(
        case_id=case.case_id,
        evidence_pack_id=pack_id,
        runner_key="jiuwenswarm",
        playbook_key="etf_medium_term_assessment",
    )
    return queued.start(
        occurred_at=datetime(2026, 3, 6, 10, tzinfo=UTC),
    ).succeed(occurred_at=datetime(2026, 3, 6, 10, 5, tzinfo=UTC))


def _build_result(run: ResearchRun, pack: EvidencePack) -> ResearchResult:
    return ResearchResult.create(
        run=run,
        evidence_pack=pack,
        conclusion="Positive with bounded downside",
        risks=("valuation", "liquidity"),
        evidence_ids=(pack.factors[0].evidence_id, pack.factors[1].evidence_id),
        report_markdown="# Report\n\nEvidence-backed.",
        model_key="model-key-v1",
        model_version="model-v1",
        playbook_version="playbook-v1",
        adapter_version="adapter-v1",
    )


@dataclass(frozen=True)
class _CaseStub(ResearchCaseReader):
    cases: dict[UUID, ResearchCase]

    def get(self, case_id: UUID) -> ResearchCase | None:
        return self.cases.get(case_id)

    def list_recent(self, *, limit: int, offset: int) -> list[ResearchCase]:
        return []

    def count_all(self) -> int:
        return len(self.cases)


@dataclass(frozen=True)
class _EvidenceStub(ResearchEvidenceReader):
    packs_by_case: dict[UUID, list[EvidencePack]]

    def list_by_case(self, case_id: UUID) -> list[EvidencePack]:
        return self.packs_by_case.get(case_id, [])


@dataclass(frozen=True)
class _RunStub(ResearchRunReader):
    runs: dict[UUID, ResearchRun]

    def get(self, run_id: UUID) -> ResearchRun | None:
        return self.runs.get(run_id)

    def list_recent(self, *, limit: int, offset: int) -> list[ResearchRun]:
        return []

    def count_all(self) -> int:
        return len(self.runs)


@dataclass(frozen=True)
class _ResultStub(ResearchResultReader):
    results_by_run: dict[UUID, ResearchResult]

    def get_by_run_id(self, run_id: UUID) -> ResearchResult | None:
        return self.results_by_run.get(run_id)


@pytest.fixture()
def http_service():
    case = _build_case()
    pack = _build_pack(case_id=case.case_id, pack_id=uuid4())
    run = _build_run(case, pack.pack_id)
    result = _build_result(run, pack)

    service = ResearchQueryService(
        case_repository=_CaseStub(cases={case.case_id: case}),
        evidence_repository=_EvidenceStub(packs_by_case={case.case_id: [pack]}),
        run_repository=_RunStub(runs={run.run_id: run}),
        result_repository=_ResultStub(results_by_run={run.run_id: result}),
    )
    app.dependency_overrides[get_research_query_service] = lambda: service
    try:
        yield {"case": case, "pack": pack, "run": run, "result": result}
    finally:
        app.dependency_overrides.pop(get_research_query_service, None)


def _walk(payload, path=()):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield from _walk(value, (*path, key))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk(value, (*path, index))
    else:
        yield path, payload


def _assert_no_internal_leaks(payload) -> None:
    leaked = sorted(
        {key for path, _ in _walk(payload) for key in path if isinstance(key, str)}
        & set(_INTERNAL_LEAKS)
    )
    assert leaked == [], f"internal metadata leaked into JSON: {leaked}"


def test_case_detail_returns_exact_json(client: TestClient, http_service) -> None:
    case = http_service["case"]

    response = client.get(f"/api/v1/research-cases/{case.case_id}")

    assert response.status_code == 200
    assert response.json() == {
        "case_id": str(case.case_id),
        "instrument_id": str(_INSTRUMENT_ID),
        "as_of_date": _AS_OF.isoformat(),
        "question": _QUESTION,
        "horizon": "20-60d",
        "status": "draft",
        "created_at": "2026-03-06T09:00:00Z",
        "closed_at": None,
        "candidate_pool_run_id": None,
    }
    _assert_no_internal_leaks(response.json())


def test_evidence_detail_serializes_real_pack_with_all_factor_units(
    client: TestClient, http_service
) -> None:
    case = http_service["case"]
    pack = http_service["pack"]

    response = client.get(f"/api/v1/research-cases/{case.case_id}/evidence")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list) and len(payload) == 1
    body = payload[0]

    assert body["pack_id"] == str(pack.pack_id)
    assert body["schema_version"] == pack.schema_version
    assert body["factor_set_key"] == pack.factor_set.key
    assert body["factor_set_version"] == pack.factor_set.version
    assert body["pack_hash"] == pack.pack_hash
    assert body["case"] == {
        "case_id": str(case.case_id),
        "instrument_id": str(_INSTRUMENT_ID),
        "as_of_date": _AS_OF.isoformat(),
        "question": _QUESTION,
        "horizon": "20-60d",
    }
    assert body["instrument"] == {
        "instrument_id": str(_INSTRUMENT_ID),
        "symbol": "510300",
        "name": "HS300 ETF",
        "exchange": "SSE",
        "currency": "CNY",
    }

    factor_keys = {factor.factor_key for factor in pack.factors}
    factor_units = {factor.unit for factor in pack.factors}
    assert factor_units <= _FACTOR_UNITS, (
        f"unknown factor units: {factor_units - _FACTOR_UNITS}"
    )
    serialized_factors = body["factors"]
    assert serialized_factors, "factors array must not be empty"
    assert {item["factor_key"] for item in serialized_factors} == factor_keys
    for item in serialized_factors:
        assert isinstance(item["unit"], str) and item["unit"], (
            f"factor {item['factor_key']} missing explicit unit"
        )
        assert item["unit"] in _FACTOR_UNITS
        assert item["unit"] == next(
            factor.unit for factor in pack.factors if factor.factor_key == item["factor_key"]
        )

    _assert_no_internal_leaks(body)


def test_run_detail_returns_exact_json(client: TestClient, http_service) -> None:
    run = http_service["run"]

    response = client.get(f"/api/v1/research-runs/{run.run_id}")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(run.run_id),
        "case_id": str(run.case_id),
        "evidence_pack_id": str(run.evidence_pack_id),
        "runner_key": "jiuwenswarm",
        "playbook_key": "etf_medium_term_assessment",
        "status": ResearchRunStatus.SUCCEEDED.value,
        "attempt": 1,
        "started_at": "2026-03-06T10:00:00Z",
        "finished_at": "2026-03-06T10:05:00Z",
        "error_summary": None,
    }
    _assert_no_internal_leaks(response.json())


def test_result_detail_returns_exact_json(client: TestClient, http_service) -> None:
    run = http_service["run"]
    result = http_service["result"]

    response = client.get(f"/api/v1/research-runs/{run.run_id}/result")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "result_id": str(result.result_id),
        "run_id": str(run.run_id),
        "evidence_pack_id": str(run.evidence_pack_id),
        "conclusion": "Positive with bounded downside",
        "risks": ["liquidity", "valuation"],
        "evidence_ids": sorted((result.evidence_ids[0], result.evidence_ids[1])),
        "report_markdown": "# Report\n\nEvidence-backed.",
        "model_key": "model-key-v1",
        "model_version": "model-v1",
        "playbook_version": "playbook-v1",
        "adapter_version": "adapter-v1",
        "created_at": result.created_at.isoformat().replace("+00:00", "Z"),
    }
    _assert_no_internal_leaks(payload)
