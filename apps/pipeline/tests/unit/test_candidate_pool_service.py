"""Unit tests for :mod:`invest_pipeline.candidate_pool_service`.

The tests cover the full PR-3 slice 1 contract:

* YAML policy loader: happy path, validation failures, stable hash.
* Application service happy path: load policy → resolve snapshot → read
  bars → run calculator → persist run + items → transition to
  ``VALIDATED`` then ``PUBLISHED``.
* Failure modes: snapshot not found, ``trade_date`` not matching the
  snapshot's ``snapshot_date``, missing bars staying in the snapshot as
  ``no_data``, persisted item count mismatch with the calculator.
* Determinism: two identical invocations produce the same
  ``parameter_hash`` and the same ordered item sequence.
* Market-data fingerprint (six-part natural key): identical selected
  revisions stay idempotent; revised or previously-missing bars spawn
  a fresh immutable run instead of overwriting; an empty bar selection
  remains stable across reruns.

The slice is exercised through a hand-rolled ``_FakeUnitOfWork`` that
exposes the real repository classes wired against a
:class:`unittest.mock.MagicMock` session. No PostgreSQL container is
booted; the repository mocks intercept every persistence call so the
test can introspect the rows the service tries to insert and the
sequence of state-machine transitions.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
import yaml
from invest_domain.candidate_pool.calculator import DefaultMinimumCandidatePoolCalculator
from invest_domain.candidate_pool.fingerprint import compute_market_data_fingerprint
from invest_domain.candidate_pool.models import (
    CandidatePoolPolicy,
    CandidatePoolRun,
    CandidatePoolStatus,
    EligibilityCriteria,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.market_data.values import TradingStatus
from invest_pipeline.candidate_pool_service import (
    CandidatePoolPolicyError,
    CandidatePoolPublishResult,
    CandidatePoolSnapshotNotFoundError,
    calculate_and_publish_candidate_pool,
    load_candidate_pool_policy,
)
from invest_storage.models import (
    CandidatePoolItemRow,
    CandidatePoolRunRow,
    InputSnapshotRow,
)
from invest_storage.repositories import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
    SqlAlchemyDailyBarRepository,
    StoredDailyBar,
)

_TRADE_DATE = date(2026, 7, 31)
_SNAPSHOT_DATE = _TRADE_DATE
_BAR_BATCH_ID = UUID("00000000-0000-0000-0000-000000000099")


def _build_yaml_payload(
    *,
    algorithm_key: str = "minimum_v1",
    algorithm_version: str = "1",
    parameter_set_key: str = "personal_default_v1",
    min_volume: Any = 100000,
    min_amount: Any = 10000000,
    max_candidates: Any = 50,
) -> dict[str, Any]:
    return {
        "algorithm": {
            "key": algorithm_key,
            "version": algorithm_version,
            "parameter_set_key": parameter_set_key,
        },
        "eligibility": {
            "min_volume": min_volume,
            "min_amount": min_amount,
        },
        "selection": {
            "max_candidates": max_candidates,
        },
    }


def _write_yaml(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def _make_stored_bar(
    *,
    instrument_id: UUID,
    trade_date: date = _TRADE_DATE,
    close: Decimal = Decimal("10"),
    volume: Decimal = Decimal("1000000"),
    amount: Decimal = Decimal("10000000"),
    trading_status: TradingStatus = TradingStatus.NORMAL,
    revision: int = 1,
) -> StoredDailyBar:
    # Anchor low / prev_close strictly below ``min(open, close)`` so the
    # domain ``DailyBar`` invariants (low <= min(open, close, high) and
    # high >= max(open, close, low)) pass on rebuild regardless of the
    # supplied close value.
    open_value = close - Decimal("0.5") if close > Decimal("1") else close + Decimal("0.5")
    min_oc = min(open_value, close)
    max_oc = max(open_value, close)
    low_value = min_oc - Decimal("0.5") if min_oc > Decimal("1") else min_oc / Decimal("2")
    high_value = max_oc + Decimal("0.5")
    if low_value <= 0:
        low_value = min_oc / Decimal("2")
    return StoredDailyBar(
        id=uuid4(),
        instrument_id=instrument_id,
        trade_date=trade_date,
        open=open_value,
        high=high_value,
        low=low_value,
        close=close,
        prev_close=close - Decimal("0.1") if close > Decimal("0.2") else close / Decimal("2"),
        volume=volume,
        amount=amount,
        adjustment="none",
        trading_status=trading_status.value,
        source_provider="fixture_dev",
        source_batch_id=_BAR_BATCH_ID,
        observed_at=datetime(2026, 7, 31, 9, 0, tzinfo=UTC),
        revision=revision,
        row_hash="0" * 64,
        created_at=datetime(2026, 7, 31, 9, 0, tzinfo=UTC),
    )


@dataclass
class _FakeSession:
    """Stand-in for a SQLAlchemy ``Session`` that records lookups."""

    snapshot_by_id: dict[UUID, SimpleNamespace] = field(default_factory=dict)

    def get(self, model: type, key: Any) -> Any:
        if model is InputSnapshotRow:
            return self.snapshot_by_id.get(key)
        raise AssertionError(f"_FakeSession.get unexpectedly called with {model!r}")


@dataclass
class _FakeUoW:
    """Stand-in for :class:`SqlAlchemyUnitOfWork`.

    Wires the real :class:`invest_storage.repositories` classes against a
    MagicMock session so the service can exercise the production code
    paths (snapshot lookup, daily-bar read, run + item persistence,
    state-machine transitions) without booting a real database.
    """

    session: MagicMock
    candidate_pool_runs_repo: SqlAlchemyCandidatePoolRunRepository
    candidate_pool_items_repo: SqlAlchemyCandidatePoolItemRepository
    daily_bars_repo: SqlAlchemyDailyBarRepository

    @property
    def candidate_pool_runs(self) -> SqlAlchemyCandidatePoolRunRepository:
        return self.candidate_pool_runs_repo

    @property
    def candidate_pool_items(self) -> SqlAlchemyCandidatePoolItemRepository:
        return self.candidate_pool_items_repo

    @property
    def daily_bars(self) -> SqlAlchemyDailyBarRepository:
        return self.daily_bars_repo

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def __enter__(self) -> _FakeUoW:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _build_uow_factory(
    *,
    snapshot: SimpleNamespace | None,
    daily_bars_by_instrument: dict[UUID, StoredDailyBar | None],
    inserted_count: int | None = None,
) -> tuple[Any, _FakeUoW, _FakeSession]:
    session = MagicMock(name="Session")
    snapshots = {snapshot.id: snapshot} if snapshot is not None else {}
    fake_session = _FakeSession(snapshot_by_id=snapshots)
    session.get.side_effect = fake_session.get

    daily_bars_repo = SqlAlchemyDailyBarRepository(session)
    candidate_pool_runs_repo = SqlAlchemyCandidatePoolRunRepository(session)
    candidate_pool_items_repo = SqlAlchemyCandidatePoolItemRepository(session)

    def _get_latest(*, instrument_id: UUID, trade_date: date, adjustment: Any) -> Any:
        return daily_bars_by_instrument.get(instrument_id)

    daily_bars_repo.get_latest = MagicMock(side_effect=_get_latest)  # type: ignore[method-assign]

    persisted_rows: list[CandidatePoolRunRow] = []

    def _add_run(run: CandidatePoolRun) -> CandidatePoolRun:  # type: ignore[name-defined]
        row = CandidatePoolRunRow(
            id=run.id,
            trade_date=run.trade_date,
            algorithm_key=run.algorithm_key,
            algorithm_version=run.algorithm_version,
            parameter_set_key=run.parameter_set_key,
            parameter_hash=run.parameter_hash,
            input_snapshot_id=run.input_snapshot_id,
            market_data_fingerprint=run.market_data_fingerprint,
            input_row_count=run.input_row_count,
            included_count=run.included_count,
            status=run.status.value,
            started_at=run.created_at,
            finished_at=run.finished_at,
            published_at=run.published_at,
            rejected_at=run.rejected_at,
            rejection_reason=run.rejection_reason,
            quality_summary={},
        )
        session.add(row)
        persisted_rows.append(row)
        return run

    candidate_pool_runs_repo.add = MagicMock(side_effect=_add_run)  # type: ignore[method-assign]

    def _get_by_natural_key(
        *,
        trade_date: date,
        algorithm_key: str,
        algorithm_version: str,
        parameter_hash: str,
        input_snapshot_id: UUID,
        market_data_fingerprint: str,
    ) -> CandidatePoolRun | None:
        for row in persisted_rows:
            if (
                row.trade_date == trade_date
                and row.algorithm_key == algorithm_key
                and row.algorithm_version == algorithm_version
                and row.parameter_hash == parameter_hash
                and row.input_snapshot_id == input_snapshot_id
                and row.market_data_fingerprint == market_data_fingerprint
            ):
                return CandidatePoolRun(
                    id=row.id,
                    trade_date=row.trade_date,
                    algorithm_key=row.algorithm_key,
                    algorithm_version=row.algorithm_version,
                    parameter_set_key=row.parameter_set_key,
                    parameter_hash=row.parameter_hash,
                    input_snapshot_id=row.input_snapshot_id,
                    market_data_fingerprint=row.market_data_fingerprint,
                    input_row_count=row.input_row_count,
                    included_count=row.included_count,
                    status=CandidatePoolStatus(row.status),
                    created_at=row.started_at,
                    finished_at=row.finished_at,
                    published_at=row.published_at,
                    rejected_at=row.rejected_at,
                    rejection_reason=row.rejection_reason,
                )
        return None

    candidate_pool_runs_repo.get_by_natural_key = MagicMock(side_effect=_get_by_natural_key)  # type: ignore[method-assign]

    def _transition(
        run_id: UUID,
        new_status: CandidatePoolStatus,
        *,
        at: datetime | None = None,
        rejection_reason: str | None = None,
    ) -> Any:
        for row in persisted_rows:
            if row.id == run_id:
                if new_status is CandidatePoolStatus.PUBLISHED:
                    row.published_at = at or datetime.now(UTC)
                if new_status is CandidatePoolStatus.REJECTED:
                    row.rejected_at = at or datetime.now(UTC)
                if new_status is CandidatePoolStatus.VALIDATED:
                    row.finished_at = at or datetime.now(UTC)
                row.status = new_status.value
                if rejection_reason is not None:
                    row.rejection_reason = rejection_reason
                break
        for current in persisted_rows:
            if current.id == run_id:
                return CandidatePoolRun(
                    id=current.id,
                    trade_date=current.trade_date,
                    algorithm_key=current.algorithm_key,
                    algorithm_version=current.algorithm_version,
                    parameter_set_key=current.parameter_set_key,
                    parameter_hash=current.parameter_hash,
                    input_snapshot_id=current.input_snapshot_id,
                    market_data_fingerprint=current.market_data_fingerprint,
                    input_row_count=current.input_row_count,
                    included_count=current.included_count,
                    status=CandidatePoolStatus(current.status),
                    created_at=current.started_at,
                    finished_at=current.finished_at,
                    published_at=current.published_at,
                    rejected_at=current.rejected_at,
                    rejection_reason=current.rejection_reason,
                )
        raise LookupError(f"no run row for {run_id!s}")

    candidate_pool_runs_repo.transition_status = MagicMock(side_effect=_transition)  # type: ignore[method-assign]

    def _bulk_add(run_id: UUID, items: Any) -> int:
        if inserted_count is not None:
            return inserted_count
        for item in items:
            row = CandidatePoolItemRow(
                id=uuid4(),
                run_id=run_id,
                instrument_id=item.instrument_id.value,
                included=item.included,
                rank=item.rank,
                total_score=item.total_score,
                metrics={},
                rule_results=[],
                exclusion_reasons=[],
            )
            session.add(row)
        return len(items)

    candidate_pool_items_repo.bulk_add = MagicMock(side_effect=_bulk_add)  # type: ignore[method-assign]

    uow = _FakeUoW(
        session=session,
        candidate_pool_runs_repo=candidate_pool_runs_repo,
        candidate_pool_items_repo=candidate_pool_items_repo,
        daily_bars_repo=daily_bars_repo,
    )
    factory = MagicMock(name="UnitOfWorkFactory")
    factory.return_value = uow
    return factory, uow, fake_session


def _make_snapshot_row(
    *,
    snapshot_id: UUID,
    instrument_ids: list[UUID],
    snapshot_date: date = _SNAPSHOT_DATE,
) -> SimpleNamespace:
    sorted_ids = sorted(instrument_ids, key=lambda value: value.bytes)
    return SimpleNamespace(
        id=snapshot_id,
        snapshot_date=snapshot_date,
        instrument_ids=[str(value) for value in sorted_ids],
        content_hash="a" * 64,
        row_count=len(sorted_ids),
        created_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
    )


def _build_policy(
    *,
    min_volume: Decimal = Decimal("100000"),
    min_amount: Decimal = Decimal("10000000"),
    max_candidates: int = 50,
) -> CandidatePoolPolicy:
    return CandidatePoolPolicy(
        algorithm_key="minimum_v1",
        algorithm_version="1",
        parameter_set_key="personal_default_v1",
        eligibility=EligibilityCriteria(
            min_volume=min_volume,
            min_amount=min_amount,
        ),
        liquidity=LiquidityCriteria(lookback_days=1, min_valid_days=1),
        price_quality=PriceQualityCriteria(
            lookback_days=1,
            max_missing_ratio=Decimal("0"),
            max_zero_volume_days=0,
        ),
        risk=RiskCriteria(
            volatility_lookback_days=1,
            drawdown_lookback_days=1,
        ),
        selection=SelectionCriteria(max_candidates=max_candidates),
        score_weights=ScoreWeights(
            weights={
                "liquidity": Decimal("0"),
                "stability": Decimal("0"),
                "data_quality": Decimal("0"),
                "listing_maturity": Decimal("0"),
            }
        ),
    )


def _fixed_now() -> datetime:
    return datetime(2026, 7, 31, 10, 0, tzinfo=UTC)


def _unique_dir(prefix: str) -> Path:
    """Return a fresh /tmp directory unique to the test invocation."""

    directory = Path("/tmp") / f"{prefix}-{uuid4().hex[:8]}"
    directory.mkdir()
    return directory


def _cleanup_dir(directory: Path) -> None:
    for child in directory.iterdir():
        child.unlink()
    directory.rmdir()


class PolicyLoaderTest(unittest.TestCase):
    """``load_candidate_pool_policy`` reads and validates the YAML."""

    def test_loads_checked_in_personal_fixture(self) -> None:
        # ``tests/unit/test_candidate_pool_service.py`` lives four levels
        # below the repo root: parents[0]=unit, [1]=tests, [2]=pipeline,
        # [3]=apps, [4]=invest-infra. The fixture ships at the repo root.
        fixture = Path(__file__).resolve().parents[4] / "config" / "candidate-pool-personal.yaml"

        policy = load_candidate_pool_policy(fixture)

        self.assertEqual(policy.algorithm_key, "minimum_v1")
        self.assertEqual(policy.algorithm_version, "1")
        self.assertEqual(policy.parameter_set_key, "personal_default_v1")
        self.assertEqual(policy.selection.max_candidates, 50)
        self.assertEqual(policy.eligibility.min_volume, Decimal("100000"))
        self.assertEqual(policy.eligibility.min_amount, Decimal("10000000"))
        self.assertEqual(len(policy.parameter_hash), 64)

    def test_policy_hash_is_stable_across_repeated_loads(self) -> None:
        directory = _unique_dir("policy-stable")
        try:
            path = _write_yaml(directory / "policy.yaml", _build_yaml_payload())
            first = load_candidate_pool_policy(path)
            second = load_candidate_pool_policy(path)
            self.assertEqual(first.parameter_hash, second.parameter_hash)
        finally:
            _cleanup_dir(directory)

    def test_rejects_missing_file(self) -> None:
        missing = Path("/tmp") / f"missing-policy-{uuid4().hex[:8]}.yaml"
        with self.assertRaises(CandidatePoolPolicyError) as ctx:
            load_candidate_pool_policy(missing)
        self.assertIn(str(missing), str(ctx.exception))

    def test_rejects_directory_instead_of_file(self) -> None:
        directory = _unique_dir("directory-policy")
        try:
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(directory)
        finally:
            directory.rmdir()

    def test_rejects_root_that_is_not_a_mapping(self) -> None:
        path = Path("/tmp") / f"list-policy-{uuid4().hex[:8]}.yaml"
        path.write_text("- 1\n- 2\n", encoding="utf-8")
        try:
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            path.unlink()

    def test_rejects_missing_algorithm_block(self) -> None:
        directory = _unique_dir("missing-algo")
        try:
            payload = _build_yaml_payload()
            del payload["algorithm"]
            path = _write_yaml(directory / "policy.yaml", payload)
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            _cleanup_dir(directory)

    def test_rejects_blank_algorithm_key(self) -> None:
        directory = _unique_dir("blank-key")
        try:
            path = _write_yaml(
                directory / "policy.yaml", _build_yaml_payload(algorithm_key="   ")
            )
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            _cleanup_dir(directory)

    def test_rejects_non_positive_max_candidates(self) -> None:
        directory = _unique_dir("bad-max")
        try:
            path = _write_yaml(directory / "policy.yaml", _build_yaml_payload(max_candidates=0))
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            _cleanup_dir(directory)

    def test_rejects_non_numeric_min_volume(self) -> None:
        directory = _unique_dir("bad-vol")
        try:
            path = _write_yaml(
                directory / "policy.yaml", _build_yaml_payload(min_volume="not_a_number")
            )
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            _cleanup_dir(directory)

    def test_rejects_negative_min_amount(self) -> None:
        directory = _unique_dir("bad-amt")
        try:
            path = _write_yaml(
                directory / "policy.yaml", _build_yaml_payload(min_amount=-1)
            )
            with self.assertRaises(CandidatePoolPolicyError):
                load_candidate_pool_policy(path)
        finally:
            _cleanup_dir(directory)


@pytest.fixture
def tmp_yaml_path(tmp_path: Path):
    def _factory(payload: dict[str, Any]) -> Path:
        return _write_yaml(tmp_path / "policy.yaml", payload)

    return _factory


def test_load_candidate_pool_policy_supports_string_and_int_thresholds(tmp_yaml_path: Path) -> None:
    path = tmp_yaml_path(
        _build_yaml_payload(min_volume="50000", min_amount="5000000", max_candidates=10)
    )
    policy = load_candidate_pool_policy(path)
    assert policy.eligibility.min_volume == Decimal("50000")
    assert policy.eligibility.min_amount == Decimal("5000000")
    assert policy.selection.max_candidates == 10


def test_calculator_default_is_the_existing_minimum_implementation() -> None:
    from invest_pipeline.candidate_pool_service import calculate_and_publish_candidate_pool

    # Keyword-only default values live in ``__kwdefaults__`` rather than
    # ``__defaults__``; the service pins the existing default calculator
    # here so a future refactor that swaps in a new calculator is caught.
    kw_defaults = calculate_and_publish_candidate_pool.__kwdefaults__
    assert isinstance(
        kw_defaults["calculator"], DefaultMinimumCandidatePoolCalculator
    )


class CalculateAndPublishTest(unittest.TestCase):
    """``calculate_and_publish_candidate_pool`` end-to-end behaviour."""

    def _setup_uow(
        self,
        *,
        snapshot_id: UUID,
        instrument_ids: list[UUID],
        bars_by_instrument: dict[UUID, StoredDailyBar | None],
        snapshot_date: date = _SNAPSHOT_DATE,
        inserted_count: int | None = None,
    ) -> tuple[Any, _FakeUoW, CandidatePoolPolicy]:
        snapshot = _make_snapshot_row(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            snapshot_date=snapshot_date,
        )
        policy = _build_policy()
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot,
            daily_bars_by_instrument=bars_by_instrument,
            inserted_count=inserted_count,
        )
        return factory, uow, policy

    def test_calculates_persists_and_publishes_through_state_machine(self) -> None:
        snapshot_id = uuid4()
        instr_a = UUID("00000000-0000-0000-0000-000000000001")
        instr_b = UUID("00000000-0000-0000-0000-000000000002")
        instr_c = UUID("00000000-0000-0000-0000-000000000003")
        instrument_ids = [instr_a, instr_b, instr_c]
        bars = {
            instr_a: _make_stored_bar(
                instrument_id=instr_a,
                close=Decimal("12"),
                volume=Decimal("2000000"),
            ),
            instr_b: _make_stored_bar(
                instrument_id=instr_b,
                close=Decimal("8"),
                volume=Decimal("500000"),
            ),
            instr_c: None,  # missing bar becomes ``no_data``
        }
        factory, uow, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument=bars,
        )

        result = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertIsInstance(result, CandidatePoolPublishResult)
        self.assertEqual(result.run.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(result.run.published_at, _fixed_now())
        self.assertEqual(result.run.input_snapshot_id, snapshot_id)
        self.assertEqual(result.run.input_row_count, 3)
        self.assertEqual(result.run.included_count, 2)
        self.assertEqual(result.run.trade_date, _TRADE_DATE)
        self.assertEqual(result.run.parameter_hash, policy.parameter_hash)

        # Calculator produced 3 items (one per instrument in the snapshot),
        # of which the missing bar surfaces as ``no_data`` and the two
        # supplied bars rank by turnover descending.
        self.assertEqual(len(result.result.items), 3)
        included_items = [item for item in result.result.items if item.included]
        self.assertEqual(len(included_items), 2)
        self.assertEqual(included_items[0].rank, 1)
        self.assertEqual(included_items[1].rank, 2)
        excluded_items = [item for item in result.result.items if not item.included]
        self.assertEqual(len(excluded_items), 1)
        self.assertEqual(excluded_items[0].exclusion_reasons[0].code, "no_data")

        # Repositories were invoked once each in the documented order.
        uow.candidate_pool_runs_repo.add.assert_called_once()  # type: ignore[attr-defined]
        uow.candidate_pool_items_repo.bulk_add.assert_called_once()  # type: ignore[attr-defined]
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )
        transitions = [
            call.args[1]
            for call in uow.candidate_pool_runs_repo.transition_status.call_args_list  # type: ignore[attr-defined]
        ]
        self.assertEqual(
            transitions,
            [CandidatePoolStatus.VALIDATED, CandidatePoolStatus.PUBLISHED],
        )

    def test_persisted_item_count_mismatch_raises(self) -> None:
        snapshot_id = uuid4()
        instrument_ids = [UUID("00000000-0000-0000-0000-000000000010")]
        factory, uow, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument={
                instrument_ids[0]: _make_stored_bar(instrument_id=instrument_ids[0])
            },
            inserted_count=0,  # deliberately wrong so the safety check fires
        )

        with self.assertRaises(RuntimeError) as ctx:
            calculate_and_publish_candidate_pool(
                uow_factory=factory,
                trade_date=_TRADE_DATE,
                snapshot_id=snapshot_id,
                policy=policy,
                now_factory=_fixed_now,
            )
        self.assertIn("bulk_add inserted 0", str(ctx.exception))
        # State transitions must NOT have run after the mismatch surfaced.
        uow.candidate_pool_runs_repo.transition_status.assert_not_called()  # type: ignore[attr-defined]

    def test_snapshot_not_found_raises(self) -> None:
        snapshot_id = uuid4()
        instrument_ids = [UUID("00000000-0000-0000-0000-000000000020")]
        factory, _, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument={},
        )
        # Replace the UoW factory with one that has no matching snapshot row.
        empty_factory, _, _ = _build_uow_factory(
            snapshot=None,
            daily_bars_by_instrument={},
        )

        with self.assertRaises(CandidatePoolSnapshotNotFoundError) as ctx:
            calculate_and_publish_candidate_pool(
                uow_factory=empty_factory,
                trade_date=_TRADE_DATE,
                snapshot_id=snapshot_id,
                policy=policy,
                now_factory=_fixed_now,
            )
        self.assertIn(str(snapshot_id), str(ctx.exception))

    def test_trade_date_mismatch_with_snapshot_raises(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-000000000030")
        factory, _, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=[instr],
            bars_by_instrument={
                instr: _make_stored_bar(instrument_id=instr)
            },
            snapshot_date=date(2026, 7, 30),  # snapshot for a different date
        )

        with self.assertRaises(ValueError) as ctx:
            calculate_and_publish_candidate_pool(
                uow_factory=factory,
                trade_date=_TRADE_DATE,
                snapshot_id=snapshot_id,
                policy=policy,
                now_factory=_fixed_now,
            )
        message = str(ctx.exception)
        self.assertIn("2026-07-30", message)
        self.assertIn("2026-07-31", message)
        self.assertIn("refuses to silently fall back", message)

    def test_determinism_two_runs_produce_same_hash_and_item_order(self) -> None:
        snapshot_id = uuid4()
        instr_a = UUID("00000000-0000-0000-0000-0000000000a1")
        instr_b = UUID("00000000-0000-0000-0000-0000000000a2")
        instrument_ids = [instr_a, instr_b]
        bars = {
            instr_a: _make_stored_bar(
                instrument_id=instr_a,
                close=Decimal("20"),
                volume=Decimal("200000"),
                amount=Decimal("2000000"),
            ),
            instr_b: _make_stored_bar(
                instrument_id=instr_b,
                close=Decimal("15"),
                volume=Decimal("300000"),
                amount=Decimal("1500000"),
            ),
        }

        first_factory, _, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument=bars,
        )
        first_result = calculate_and_publish_candidate_pool(
            uow_factory=first_factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        second_factory, _, _ = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument=bars,
        )
        second_result = calculate_and_publish_candidate_pool(
            uow_factory=second_factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(
            first_result.result.items, second_result.result.items
        )
        self.assertEqual(
            first_result.run.parameter_hash, second_result.run.parameter_hash
        )

    def test_missing_bar_surfaces_as_no_data_included_count_drops(self) -> None:
        snapshot_id = uuid4()
        present = UUID("00000000-0000-0000-0000-0000000000b1")
        absent = UUID("00000000-0000-0000-0000-0000000000b2")
        instrument_ids = [present, absent]
        factory, _, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=instrument_ids,
            bars_by_instrument={
                present: _make_stored_bar(instrument_id=present),
                absent: None,
            },
        )

        result = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(result.run.included_count, 1)
        excluded = [item for item in result.result.items if not item.included]
        self.assertEqual(len(excluded), 1)
        self.assertEqual(excluded[0].exclusion_reasons[0].code, "no_data")
        self.assertEqual(excluded[0].instrument_id.value, absent)

    def test_only_bars_matching_trade_date_and_adjustment_none_are_used(self) -> None:
        # The repository's get_latest is parameterised by trade_date and
        # Adjust.NONE; this test asserts the service forwards those
        # arguments exactly so no off-date / non-NONE bars can leak in.
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-0000000000c1")
        factory, uow, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=[instr],
            bars_by_instrument={instr: None},
        )

        calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        latest_call = uow.daily_bars_repo.get_latest.call_args  # type: ignore[attr-defined]
        self.assertEqual(latest_call.kwargs["trade_date"], _TRADE_DATE)
        self.assertEqual(latest_call.kwargs["adjustment"].value, "none")
        self.assertEqual(latest_call.kwargs["instrument_id"], instr)

    def test_missing_source_batch_id_is_rejected_without_transition(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-0000000000c2")
        factory, uow, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=[instr],
            bars_by_instrument={
                instr: replace(
                    _make_stored_bar(instrument_id=instr),
                    source_batch_id=None,
                )
            },
        )

        with self.assertRaisesRegex(ValueError, "missing source_batch_id"):
            calculate_and_publish_candidate_pool(
                uow_factory=factory,
                trade_date=_TRADE_DATE,
                snapshot_id=snapshot_id,
                policy=policy,
                now_factory=_fixed_now,
            )
        uow.candidate_pool_runs_repo.transition_status.assert_not_called()

    def test_state_machine_transitions_only_calculated_to_validated_to_published(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-0000000000d1")
        factory, uow, policy = self._setup_uow(
            snapshot_id=snapshot_id,
            instrument_ids=[instr],
            bars_by_instrument={
                instr: _make_stored_bar(instrument_id=instr)
            },
        )

        calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        call_args_list = uow.candidate_pool_runs_repo.transition_status.call_args_list  # type: ignore[attr-defined]
        statuses = [call.args[1] for call in call_args_list]
        self.assertEqual(
            statuses,
            [CandidatePoolStatus.VALIDATED, CandidatePoolStatus.PUBLISHED],
        )
        for call in call_args_list:
            self.assertEqual(call.kwargs["at"], _fixed_now())


def test_calculator_input_items_are_persisted_with_input_snapshot_id() -> None:
    snapshot_id = uuid4()
    instr_a = UUID("00000000-0000-0000-0000-0000000000e1")
    instr_b = UUID("00000000-0000-0000-0000-0000000000e2")
    instrument_ids = [instr_a, instr_b]
    policy = _build_policy()
    factory, _, _ = _build_uow_factory(
        snapshot=_make_snapshot_row(
            snapshot_id=snapshot_id, instrument_ids=instrument_ids
        ),
        daily_bars_by_instrument={
            instr_a: _make_stored_bar(instrument_id=instr_a, close=Decimal("100")),
            instr_b: _make_stored_bar(instrument_id=instr_b, close=Decimal("50")),
        },
    )

    result = calculate_and_publish_candidate_pool(
        uow_factory=factory,
        trade_date=_TRADE_DATE,
        snapshot_id=snapshot_id,
        policy=policy,
        now_factory=_fixed_now,
    )

    bulk_call = factory.return_value.candidate_pool_items_repo.bulk_add.call_args
    persisted_items = bulk_call.args[1]
    assert isinstance(persisted_items, tuple)
    assert len(persisted_items) == 2
    instrument_set = {item.instrument_id.value for item in persisted_items}
    assert instrument_set == {instr_a, instr_b}
    assert result.run.input_snapshot_id == snapshot_id


def test_published_run_carries_terminal_timestamps_from_utc_now() -> None:
    snapshot_id = uuid4()
    instr = UUID("00000000-0000-0000-0000-0000000000f1")
    policy = _build_policy()
    factory, _, _ = _build_uow_factory(
        snapshot=_make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr]),
        daily_bars_by_instrument={
            instr: _make_stored_bar(instrument_id=instr)
        },
    )

    result = calculate_and_publish_candidate_pool(
        uow_factory=factory,
        trade_date=_TRADE_DATE,
        snapshot_id=snapshot_id,
        policy=policy,
        now_factory=_fixed_now,
    )

    assert result.run.status == CandidatePoolStatus.PUBLISHED
    assert result.run.published_at == _fixed_now()
    assert result.run.published_at.tzinfo is not None


def test_repeated_identical_invocations_produce_identical_policy_hash() -> None:
    snapshot_id = uuid4()
    instr = UUID("00000000-0000-0000-0000-000000000101")
    policy = _build_policy()
    factory, _, _ = _build_uow_factory(
        snapshot=_make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr]),
        daily_bars_by_instrument={
            instr: _make_stored_bar(instrument_id=instr)
        },
    )

    first = calculate_and_publish_candidate_pool(
        uow_factory=factory,
        trade_date=_TRADE_DATE,
        snapshot_id=snapshot_id,
        policy=policy,
        now_factory=_fixed_now,
    )
    second_factory, _, _ = _build_uow_factory(
        snapshot=_make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr]),
        daily_bars_by_instrument={
            instr: _make_stored_bar(instrument_id=instr)
        },
    )
    second = calculate_and_publish_candidate_pool(
        uow_factory=second_factory,
        trade_date=_TRADE_DATE,
        snapshot_id=snapshot_id,
        policy=policy,
        now_factory=_fixed_now,
    )

    assert first.run.parameter_hash == second.run.parameter_hash
    assert first.run.parameter_hash == policy.parameter_hash


class IdempotentRerunTest(unittest.TestCase):
    """Rerunning the service with the same natural key must return the same run.

    The first call is allowed to insert the run and walk the state machine.
    Subsequent identical calls MUST reuse the existing row (so the DB unique
    constraint never fires) and MUST NOT touch the state machine. The freshly
    calculated :class:`CandidatePoolResult` is still returned alongside so
    callers can audit the deterministic recompute.
    """

    @staticmethod
    def _build_state(
        snapshot_id: UUID, instrument_ids: list[UUID]
    ) -> tuple[SimpleNamespace, dict[UUID, StoredDailyBar | None]]:
        snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=instrument_ids)
        bars = {
            instrument_id: _make_stored_bar(instrument_id=instrument_id)
            for instrument_id in instrument_ids
        }
        return snapshot, bars

    def test_rerun_returns_existing_run_and_skips_insert_and_transitions(self) -> None:
        snapshot_id = uuid4()
        instr_a = UUID("00000000-0000-0000-0000-000000000011")
        instr_b = UUID("00000000-0000-0000-0000-000000000012")
        snapshot, bars = self._build_state(snapshot_id, [instr_a, instr_b])
        policy = _build_policy()
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars
        )

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        self.assertEqual(first.run.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )

        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(second.run.id, first.run.id)
        self.assertEqual(second.run.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(
            second.run.published_at, first.run.published_at
        )
        self.assertEqual(
            second.run.parameter_hash, policy.parameter_hash
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_items_repo.bulk_add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.get_by_natural_key.call_count, 2  # type: ignore[attr-defined]
        )

    def test_rerun_still_returns_freshly_calculated_result(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-000000000013")
        snapshot, bars = self._build_state(snapshot_id, [instr])
        policy = _build_policy()
        factory, _, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars
        )

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(
            first.result.items, second.result.items
        )
        self.assertEqual(
            first.result.summary.included_count,
            second.result.summary.included_count,
        )

    def test_first_run_behavior_unchanged_when_no_existing_run(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-000000000014")
        factory, uow, _ = _build_uow_factory(
            snapshot=_make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr]),
            daily_bars_by_instrument={instr: _make_stored_bar(instrument_id=instr)},
        )
        policy = _build_policy()

        result = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(result.run.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.get_by_natural_key.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )


class MarketDataFingerprintTest(unittest.TestCase):
    """Six-part natural key behaviour tied to ``compute_market_data_fingerprint``.

    Each test exercises one invariant of the safe-by-construction
    re-run contract:

    * identical selected bar revisions keep a single, immutable
      :class:`CandidatePoolRun` (idempotent rerun);
    * changing a selected bar's ``revision`` (or materialising a bar
      that was previously missing) produces a *new* run instead of
      overwriting the audit history;
    * an empty selected-bar set still yields a stable fingerprint so
      no-data days do not regress to non-idempotent reruns.

    The tests also assert that the fingerprint on the returned
    :class:`CandidatePoolRun` matches both the value the service handed
    to the repository's ``get_by_natural_key`` lookup and the value
    persisted onto the row.
    """

    def test_identical_selected_revisions_remain_idempotent(self) -> None:
        snapshot_id = uuid4()
        instr_a = UUID("00000000-0000-0000-0000-000000000021")
        instr_b = UUID("00000000-0000-0000-0000-000000000022")
        snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr_a, instr_b])
        bars_by_instrument = {
            instr_a: _make_stored_bar(instrument_id=instr_a, revision=1),
            instr_b: _make_stored_bar(instrument_id=instr_b, revision=1),
        }
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars_by_instrument
        )
        policy = _build_policy()

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertEqual(second.run.id, first.run.id)
        self.assertEqual(second.run.market_data_fingerprint, first.run.market_data_fingerprint)
        self.assertEqual(len(second.run.market_data_fingerprint), 64)
        for char in second.run.market_data_fingerprint:
            self.assertIn(char, "0123456789abcdef")
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_items_repo.bulk_add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.get_by_natural_key.call_count, 2  # type: ignore[attr-defined]
        )
        for call in uow.candidate_pool_runs_repo.get_by_natural_key.call_args_list:  # type: ignore[attr-defined]
            self.assertEqual(
                call.kwargs["market_data_fingerprint"], first.run.market_data_fingerprint
            )

    def test_changing_a_selected_revision_creates_a_second_run(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-000000000023")
        snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr])
        first_bar = _make_stored_bar(instrument_id=instr, revision=1)
        revised_bar = _make_stored_bar(instrument_id=instr, revision=2)
        bars_by_instrument = {instr: first_bar}
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars_by_instrument
        )
        policy = _build_policy()

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        first_fingerprint = first.run.market_data_fingerprint

        # Mutate the underlying bar so the next invocation observes a
        # revised DailyBar under the same snapshot/policy.
        bars_by_instrument[instr] = revised_bar

        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertNotEqual(second.run.id, first.run.id)
        self.assertNotEqual(
            second.run.market_data_fingerprint, first_fingerprint
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 2  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_items_repo.bulk_add.call_count, 2  # type: ignore[attr-defined]
        )
        # Two transitions per run (CALCULATED -> VALIDATED -> PUBLISHED).
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 4  # type: ignore[attr-defined]
        )
        # The lookup fingerprint the service sent to the repository on
        # the rerun must equal the freshly computed fingerprint for the
        # revised selection and equal the persisted run fingerprint.
        lookup_calls = uow.candidate_pool_runs_repo.get_by_natural_key.call_args_list  # type: ignore[attr-defined]
        self.assertEqual(len(lookup_calls), 2)
        self.assertEqual(lookup_calls[0].kwargs["market_data_fingerprint"], first_fingerprint)
        self.assertEqual(
            lookup_calls[1].kwargs["market_data_fingerprint"],
            second.run.market_data_fingerprint,
        )
        self.assertEqual(
            lookup_calls[1].kwargs["market_data_fingerprint"],
            second.run.market_data_fingerprint,
        )

    def test_previously_missing_bar_creates_a_second_run(self) -> None:
        snapshot_id = uuid4()
        instr = UUID("00000000-0000-0000-0000-000000000024")
        snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr])
        bars_by_instrument: dict[UUID, StoredDailyBar | None] = {instr: None}
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars_by_instrument
        )
        policy = _build_policy()

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        first_fingerprint = first.run.market_data_fingerprint

        # The provider now supplies a bar for the previously-missing
        # instrument; under the old five-part key this would collide,
        # but the six-part key binds market-data identity so the
        # service must mint a new immutable run.
        bars_by_instrument[instr] = _make_stored_bar(instrument_id=instr, revision=1)

        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        self.assertNotEqual(second.run.id, first.run.id)
        self.assertNotEqual(
            second.run.market_data_fingerprint, first_fingerprint
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 2  # type: ignore[attr-defined]
        )

    def test_empty_selected_bar_set_stays_stable_and_idempotent(self) -> None:
        snapshot_id = uuid4()
        instr_a = UUID("00000000-0000-0000-0000-000000000025")
        instr_b = UUID("00000000-0000-0000-0000-000000000026")
        snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr_a, instr_b])
        # Every instrument's bar is missing -> the service observes an
        # empty selected-bar set on every invocation.
        bars_by_instrument: dict[UUID, StoredDailyBar | None] = {instr_a: None, instr_b: None}
        factory, uow, _ = _build_uow_factory(
            snapshot=snapshot, daily_bars_by_instrument=bars_by_instrument
        )
        policy = _build_policy()

        first = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )
        second = calculate_and_publish_candidate_pool(
            uow_factory=factory,
            trade_date=_TRADE_DATE,
            snapshot_id=snapshot_id,
            policy=policy,
            now_factory=_fixed_now,
        )

        # The fingerprint for an empty selection is itself a valid 64-
        # char lowercase hex digest, and the helper supports it via
        # its generic Iterable[DailyBar] signature.
        self.assertEqual(len(first.run.market_data_fingerprint), 64)
        for char in first.run.market_data_fingerprint:
            self.assertIn(char, "0123456789abcdef")

        self.assertEqual(second.run.id, first.run.id)
        self.assertEqual(
            second.run.market_data_fingerprint,
            first.run.market_data_fingerprint,
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_items_repo.bulk_add.call_count, 1  # type: ignore[attr-defined]
        )
        self.assertEqual(
            uow.candidate_pool_runs_repo.transition_status.call_count, 2  # type: ignore[attr-defined]
        )

        # Lookup fingerprint on both invocations equals the run's
        # fingerprint, proving the service both uses and persists it.
        lookup_calls = uow.candidate_pool_runs_repo.get_by_natural_key.call_args_list  # type: ignore[attr-defined]
        self.assertEqual(len(lookup_calls), 2)
        for call in lookup_calls:
            self.assertEqual(
                call.kwargs["market_data_fingerprint"],
                first.run.market_data_fingerprint,
            )
        # Cross-check the helper itself agrees the empty selection
        # yields the same fingerprint the service computed.
        self.assertEqual(
            compute_market_data_fingerprint([]),
            first.run.market_data_fingerprint,
        )


def test_returned_run_fingerprint_matches_lookup_and_persisted_row() -> None:
    snapshot_id = uuid4()
    instr = UUID("00000000-0000-0000-0000-000000000027")
    snapshot = _make_snapshot_row(snapshot_id=snapshot_id, instrument_ids=[instr])
    factory, uow, _ = _build_uow_factory(
        snapshot=snapshot,
        daily_bars_by_instrument={instr: _make_stored_bar(instrument_id=instr)},
    )
    policy = _build_policy()

    result = calculate_and_publish_candidate_pool(
        uow_factory=factory,
        trade_date=_TRADE_DATE,
        snapshot_id=snapshot_id,
        policy=policy,
        now_factory=_fixed_now,
    )

    add_call = uow.candidate_pool_runs_repo.add.call_args  # type: ignore[attr-defined]
    persisted_run = add_call.args[0]
    lookup_call = uow.candidate_pool_runs_repo.get_by_natural_key.call_args  # type: ignore[attr-defined]

    assert result.run.market_data_fingerprint == persisted_run.market_data_fingerprint
    assert lookup_call.kwargs["market_data_fingerprint"] == result.run.market_data_fingerprint
    assert len(result.run.market_data_fingerprint) == 64


if __name__ == "__main__":
    unittest.main()
