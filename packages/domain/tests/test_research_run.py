from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from invest_domain import ResearchResult, ResearchRun, ResearchRunStatus
from invest_domain.research import EvidencePack
from test_research_evidence import _pack

_CASE_ID = UUID("11111111-2222-4333-8444-555555555555")
_RUNNER = "runner-v1"
_PLAYBOOK = "playbook-v1"
_BASE = datetime(2026, 3, 6, 10, tzinfo=UTC)
_STARTED = _BASE + timedelta(minutes=1)
_SUCCEEDED_AT = _BASE + timedelta(minutes=2)
_FAILED_AT = _BASE + timedelta(minutes=3)


def _run(pack: EvidencePack | None = None) -> ResearchRun:
    selected = pack or _pack()
    return ResearchRun.create(
        case_id=_CASE_ID,
        evidence_pack_id=selected.pack_id,
        runner_key=_RUNNER,
        playbook_key=_PLAYBOOK,
    )


def _succeeded(pack: EvidencePack) -> ResearchRun:
    return _run(pack).start(occurred_at=_STARTED).succeed(occurred_at=_SUCCEEDED_AT)


def _failed(pack: EvidencePack) -> ResearchRun:
    return _run(pack).start(occurred_at=_STARTED).fail(
        error_summary=" provider timeout ", occurred_at=_FAILED_AT
    )


def _result(pack: EvidencePack, run: ResearchRun | None = None) -> ResearchResult:
    selected_run = run or _succeeded(pack)
    return ResearchResult.create(
        run=selected_run,
        evidence_pack=pack,
        conclusion="Positive with bounded downside",
        risks=(" valuation ", "liquidity", "valuation"),
        evidence_ids=(pack.factors[1].evidence_id, pack.factors[0].evidence_id),
        report_markdown="Evidence-backed report",
        model_key="model-key-v1",
        model_version="model-v1",
        playbook_version="playbook-v1",
        adapter_version="adapter-v1",
    )


def test_create_is_queued_attempt_one_with_no_execution_state() -> None:
    run = _run()
    assert isinstance(run.run_id, UUID)
    assert run.case_id == _CASE_ID
    assert run.evidence_pack_id == _pack().pack_id
    assert run.runner_key == _RUNNER
    assert run.playbook_key == _PLAYBOOK
    assert run.status is ResearchRunStatus.QUEUED
    assert run.attempt == 1
    assert run.started_at is None
    assert run.finished_at is None
    assert run.error_summary is None


def test_lifecycle_start_then_succeed_is_immutable() -> None:
    run = _run()
    started = run.start(occurred_at=_STARTED)
    succeeded = started.succeed(occurred_at=_SUCCEEDED_AT)
    assert run.status is ResearchRunStatus.QUEUED
    assert started.status is ResearchRunStatus.RUNNING
    assert started.started_at == _STARTED
    assert started.finished_at is None
    assert started.error_summary is None
    assert succeeded.status is ResearchRunStatus.SUCCEEDED
    assert succeeded.started_at == _STARTED
    assert succeeded.finished_at == _SUCCEEDED_AT
    assert succeeded.error_summary is None
    with pytest.raises(FrozenInstanceError):
        started.attempt = 4


def test_failure_and_retry_increment_attempt_and_clear_execution_state() -> None:
    failed = _failed(_pack())
    retried = failed.retry()
    assert failed.error_summary == "provider timeout"
    assert failed.finished_at == _FAILED_AT
    assert retried.status is ResearchRunStatus.QUEUED
    assert retried.attempt == 2
    assert retried.started_at is None
    assert retried.finished_at is None
    assert retried.error_summary is None
    assert retried.runner_key == _RUNNER
    assert retried.playbook_key == _PLAYBOOK


def test_cancel_queued_or_running_but_succeeded_and_cancelled_are_terminal() -> None:
    queued = _run()
    cancelled = queued.cancel(occurred_at=_STARTED)
    assert cancelled.status is ResearchRunStatus.CANCELLED
    assert cancelled.finished_at == _STARTED

    running = _run().start(occurred_at=_STARTED)
    cancelled_running = running.cancel(occurred_at=_SUCCEEDED_AT)
    assert cancelled_running.status is ResearchRunStatus.CANCELLED
    assert cancelled_running.finished_at == _SUCCEEDED_AT

    with pytest.raises(ValueError, match="illegal"):
        cancelled.start(occurred_at=_SUCCEEDED_AT)
    with pytest.raises(ValueError, match="failed"):
        cancelled_running.retry()


def test_illegal_transitions_fail_closed() -> None:
    run = _run()
    with pytest.raises(ValueError, match="illegal"):
        run.succeed(occurred_at=_STARTED)
    with pytest.raises(ValueError, match="illegal"):
        run.fail(error_summary="boom", occurred_at=_STARTED)
    with pytest.raises(ValueError, match="failed"):
        run.retry()
    succeeded = _succeeded(_pack())
    with pytest.raises(ValueError, match="failed"):
        succeeded.retry()
    with pytest.raises(ValueError, match="error"):
        _run().start(occurred_at=_STARTED).fail(
            error_summary=" ", occurred_at=_SUCCEEDED_AT
        )


def test_invalid_and_naive_timestamps_are_rejected() -> None:
    run = _run()
    with pytest.raises(ValueError, match="timezone-aware"):
        run.start(occurred_at=_BASE.replace(tzinfo=None))
    started = run.start(occurred_at=_STARTED)
    with pytest.raises(ValueError, match="started_at"):
        started.succeed(occurred_at=_STARTED - timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        started.succeed(occurred_at=_BASE.replace(tzinfo=None))


def test_direct_construction_rejects_inconsistent_timestamps_and_error() -> None:
    run = _run()
    with pytest.raises(ValueError, match="queued"):
        replace(run, started_at=_BASE)
    with pytest.raises(ValueError, match="queued"):
        replace(run, error_summary="boom")
    started = run.start(occurred_at=_STARTED)
    with pytest.raises(ValueError, match="running"):
        replace(started, finished_at=_SUCCEEDED_AT)
    with pytest.raises(ValueError, match="running"):
        replace(started, error_summary="boom")


def test_invalid_inputs_and_positive_attempt_are_enforced() -> None:
    pack = _pack()
    with pytest.raises(ValueError, match="non-blank"):
        ResearchRun.create(
            case_id=_CASE_ID,
            evidence_pack_id=pack.pack_id,
            runner_key=" ",
            playbook_key=_PLAYBOOK,
        )
    with pytest.raises(ValueError, match="non-blank"):
        ResearchRun.create(
            case_id=_CASE_ID,
            evidence_pack_id=pack.pack_id,
            runner_key=_RUNNER,
            playbook_key=" ",
        )
    with pytest.raises(TypeError, match="case_id"):
        ResearchRun.create(
            case_id="not-a-uuid",
            evidence_pack_id=pack.pack_id,
            runner_key=_RUNNER,
            playbook_key=_PLAYBOOK,
        )


def test_result_validates_evidence_and_normalizes_collections() -> None:
    pack = _pack()
    succeeded_run = _succeeded(pack)
    result = _result(pack, succeeded_run)
    assert isinstance(result.result_id, UUID)
    assert result.run_id == succeeded_run.run_id
    assert result.evidence_pack_id == pack.pack_id
    assert result.risks == ("liquidity", "valuation")
    assert result.evidence_ids == tuple(
        sorted({pack.factors[0].evidence_id, pack.factors[1].evidence_id})
    )
    assert pack.factors == tuple(sorted(pack.factors, key=lambda item: item.factor_key))


def test_result_requires_succeeded_run_matching_non_null_pack_id() -> None:
    pack = _pack()
    with pytest.raises(ValueError, match="succeeded"):
        _result(pack, _run(pack))
    other_pack = replace(pack, pack_id=UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"))
    with pytest.raises(ValueError, match="matching"):
        _result(other_pack, _succeeded(pack))
    no_id = replace(pack, pack_id=None)
    with pytest.raises(ValueError, match="pack_id"):
        _result(no_id, _succeeded(pack))


def test_result_requires_nonblank_text_and_valid_nonempty_citations() -> None:
    pack = _pack()
    kwargs = dict(
        run=_succeeded(pack),
        evidence_pack=pack,
        conclusion="conclusion",
        risks=(),
        evidence_ids=(pack.factors[0].evidence_id,),
        report_markdown="report",
        model_key="model-key",
        model_version="model",
        playbook_version="playbook",
        adapter_version="adapter",
    )
    for field in (
        "conclusion",
        "report_markdown",
        "model_key",
        "model_version",
        "playbook_version",
        "adapter_version",
    ):
        with pytest.raises(ValueError, match=field):
            ResearchResult.create(**(kwargs | {field: " "}))
    with pytest.raises(ValueError, match="at least one"):
        ResearchResult.create(**(kwargs | {"evidence_ids": ()}))
    with pytest.raises(ValueError, match="factor observations"):
        ResearchResult.create(**(kwargs | {"evidence_ids": ("evidence:missing",)}))
    with pytest.raises(ValueError, match="non-blank"):
        ResearchResult.create(**(kwargs | {"risks": (" ",)}))
    with pytest.raises(ValueError, match="non-blank"):
        ResearchResult.create(**(kwargs | {"evidence_ids": ("",)}))


def test_models_are_frozen_and_publicly_importable() -> None:
    run = _run()
    with pytest.raises(FrozenInstanceError):
        run.attempt = 4
    result = _result(_pack())
    with pytest.raises(FrozenInstanceError):
        result.report_markdown = "changed"
    from invest_domain.research import ResearchResult as NestedResult
    from invest_domain.research import ResearchRun as NestedRun

    assert NestedRun is ResearchRun
    assert NestedResult is ResearchResult


def test_non_datetime_timestamps_raise_type_error() -> None:
    run = _run()
    with pytest.raises(TypeError, match="datetime"):
        run.start(occurred_at="not-a-datetime")
    started = run.start(occurred_at=_STARTED)
    with pytest.raises(TypeError, match="datetime"):
        started.succeed(occurred_at="still-not-a-datetime")
    with pytest.raises(TypeError, match="datetime"):
        started.fail(error_summary="boom", occurred_at=12345)


def test_bool_attempt_is_rejected() -> None:
    pack = _pack()
    run = _run(pack)
    with pytest.raises(TypeError, match="attempt"):
        replace(run, attempt=True)
    with pytest.raises(TypeError, match="attempt"):
        replace(run, attempt=False)
    assert run.attempt == 1


def test_runner_and_playbook_keys_are_normalized_on_construct_and_create() -> None:
    pack = _pack()
    run = ResearchRun.create(
        case_id=_CASE_ID,
        evidence_pack_id=pack.pack_id,
        runner_key=" runner-v1 ",
        playbook_key=" playbook-v1 ",
    )
    assert run.runner_key == "runner-v1"
    assert run.playbook_key == "playbook-v1"
    started = run.start(occurred_at=_STARTED).succeed(occurred_at=_SUCCEEDED_AT)
    assert started.runner_key == "runner-v1"
    assert started.playbook_key == "playbook-v1"


def test_direct_research_result_construction_validates_invariants() -> None:
    pack = _pack()
    succeeded_run = _succeeded(pack)
    base_kwargs: dict[str, object] = dict(
        result_id=uuid4(),
        run_id=succeeded_run.run_id,
        evidence_pack_id=pack.pack_id,
        conclusion="conclusion",
        risks=(),
        evidence_ids=(pack.factors[0].evidence_id,),
        report_markdown="report",
        model_key="model-key",
        model_version="model",
        playbook_version="playbook",
        adapter_version="adapter",
        created_at=_SUCCEEDED_AT,
    )
    assert isinstance(ResearchResult(**base_kwargs), ResearchResult)

    for field in ("result_id", "run_id", "evidence_pack_id"):
        with pytest.raises(TypeError, match=field):
            ResearchResult(**(base_kwargs | {field: "not-a-uuid"}))

    for field in (
        "conclusion",
        "report_markdown",
        "model_key",
        "model_version",
        "playbook_version",
        "adapter_version",
    ):
        with pytest.raises(ValueError, match=f"ResearchResult.{field}"):
            ResearchResult(**(base_kwargs | {field: " "}))
        with pytest.raises(ValueError, match=f"ResearchResult.{field}"):
            ResearchResult(**(base_kwargs | {field: 0}))

    with pytest.raises(ValueError, match="risks"):
        ResearchResult(**(base_kwargs | {"risks": ["not", "a", "tuple"]}))
    with pytest.raises(ValueError, match="risks"):
        ResearchResult(**(base_kwargs | {"risks": (" ",)}))
    with pytest.raises(ValueError, match="risks"):
        ResearchResult(**(base_kwargs | {"risks": (0,)}))
    with pytest.raises(ValueError, match="evidence_ids"):
        ResearchResult(**(base_kwargs | {"evidence_ids": ["not", "a", "tuple"]}))
    with pytest.raises(ValueError, match="evidence_ids"):
        ResearchResult(**(base_kwargs | {"evidence_ids": (" ",)}))
    with pytest.raises(ValueError, match="evidence_ids"):
        ResearchResult(**(base_kwargs | {"evidence_ids": (0,)}))

    with pytest.raises(ValueError, match="at least one"):
        ResearchResult(**(base_kwargs | {"evidence_ids": ()}))

    with pytest.raises(TypeError, match="datetime"):
        ResearchResult(**(base_kwargs | {"created_at": "not-a-datetime"}))
    with pytest.raises(ValueError, match="timezone-aware"):
        ResearchResult(**(base_kwargs | {"created_at": _BASE.replace(tzinfo=None)}))

    valid = ResearchResult(**base_kwargs)
    with pytest.raises(TypeError, match="run_id"):
        replace(valid, run_id="not-a-uuid")
    with pytest.raises(ValueError, match="non-blank"):
        replace(valid, conclusion=" ")
    with pytest.raises(ValueError, match="evidence_ids"):
        replace(valid, evidence_ids=(" ",))
    with pytest.raises(ValueError, match="at least one"):
        replace(valid, evidence_ids=())
