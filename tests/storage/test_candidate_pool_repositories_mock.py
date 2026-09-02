"""Mock-based unit tests for the candidate-pool storage repositories.

Each test drives a :class:`unittest.mock.MagicMock` ``Session`` so
:class:`SqlAlchemyCandidatePoolRunRepository` and
:class:`SqlAlchemyCandidatePoolItemRepository` can be verified without
spinning up Testcontainers or speaking to a real PostgreSQL.

The tests pin three contracts:

- The repository calls the expected ``Session`` API
  (``add``, ``add_all``, ``flush``, ``get``, ``scalars``).
- The ORM-to-domain mapping returns
  :class:`invest_domain.candidate_pool.models.CandidatePoolRun` /
  :class:`invest_domain.candidate_pool.models.CandidatePoolItem`
  instances carrying the same field values as the mock row.
- :meth:`transition_status` flows through the domain
  :meth:`invest_domain.candidate_pool.models.CandidatePoolRun.transition_to`
  so illegal transitions surface as ``ValueError`` from the repository
  without writing anything to the database.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.candidate_pool.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    CandidatePoolStatus,
    EligibilityCriteria,
    ExclusionReason,
    LiquidityCriteria,
    PriceQualityCriteria,
    RiskCriteria,
    RuleOutcome,
    RuleSeverity,
    ScoreWeights,
    SelectionCriteria,
)
from invest_domain.instruments import InstrumentId
from invest_storage.models import CandidatePoolItemRow, CandidatePoolRunRow
from invest_storage.repositories import (
    SqlAlchemyCandidatePoolItemRepository,
    SqlAlchemyCandidatePoolRunRepository,
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def _make_run(
    *,
    run_id: UUID | None = None,
    trade_date: date = date(2026, 7, 31),
    algorithm_key: str = "candidate_pool.v1",
    algorithm_version: str = "v1.0",
    parameter_set_key: str = "default",
    parameter_hash: str = "a" * 64,
    input_snapshot_id: UUID | None = None,
    input_row_count: int = 100,
    included_count: int = 10,
    status: CandidatePoolStatus = CandidatePoolStatus.CALCULATED,
    created_at: datetime | None = None,
    finished_at: datetime | None = None,
    published_at: datetime | None = None,
    rejected_at: datetime | None = None,
    rejection_reason: str | None = None,
    market_data_fingerprint: str = "f" * 64,
) -> CandidatePoolRun:
    return CandidatePoolRun(
        id=run_id or uuid4(),
        trade_date=trade_date,
        algorithm_key=algorithm_key,
        algorithm_version=algorithm_version,
        parameter_set_key=parameter_set_key,
        parameter_hash=parameter_hash,
        input_snapshot_id=input_snapshot_id or uuid4(),
        input_row_count=input_row_count,
        included_count=included_count,
        status=status,
        created_at=created_at or _utc(2026, 7, 31, 9),
        finished_at=finished_at,
        published_at=published_at,
        rejected_at=rejected_at,
        rejection_reason=rejection_reason,
        market_data_fingerprint=market_data_fingerprint,
    )


def _make_run_row(
    *,
    row_id: UUID | None = None,
    trade_date: date = date(2026, 7, 31),
    status: str = "calculated",
    included_count: int = 10,
    input_row_count: int = 100,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    published_at: datetime | None = None,
    rejected_at: datetime | None = None,
    rejection_reason: str | None = None,
    quality_summary: dict[str, Any] | None = None,
    algorithm_key: str = "candidate_pool.v1",
    algorithm_version: str = "v1.0",
    parameter_set_key: str = "default",
    parameter_hash: str = "a" * 64,
    input_snapshot_id: UUID | None = None,
    market_data_fingerprint: str = "f" * 64,
) -> MagicMock:
    """Build a mock that looks like a :class:`CandidatePoolRunRow`."""

    base = _utc(2026, 7, 31, 9)
    row = MagicMock(spec=CandidatePoolRunRow)
    row.id = row_id or uuid4()
    row.trade_date = trade_date
    row.algorithm_key = algorithm_key
    row.algorithm_version = algorithm_version
    row.parameter_set_key = parameter_set_key
    row.parameter_hash = parameter_hash
    row.input_snapshot_id = input_snapshot_id or uuid4()
    row.market_data_fingerprint = market_data_fingerprint
    row.input_row_count = input_row_count
    row.included_count = included_count
    row.status = status
    row.started_at = started_at or base
    row.finished_at = finished_at
    row.published_at = published_at
    row.rejected_at = rejected_at
    row.rejection_reason = rejection_reason
    row.quality_summary = quality_summary if quality_summary is not None else {}
    row.created_at = row.started_at
    return row


def _make_item(
    *,
    instrument_id: UUID | None = None,
    included: bool = True,
    rank: int | None = 1,
    total_score: Decimal | None = Decimal("0.85"),
    metrics: dict[str, Decimal] | None = None,
    rule_results: tuple[RuleOutcome, ...] = (),
    exclusion_reasons: tuple[ExclusionReason, ...] = (),
) -> CandidatePoolItem:
    return CandidatePoolItem(
        instrument_id=InstrumentId(instrument_id or uuid4()),
        included=included,
        rank=rank,
        total_score=total_score,
        metrics=metrics or {"liquidity": Decimal("1.5")},
        rule_results=rule_results,
        exclusion_reasons=exclusion_reasons,
    )


def _make_item_row(
    *,
    run_id: UUID | None = None,
    instrument_id: UUID | None = None,
    included: bool = True,
    rank: int | None = 1,
    total_score: Decimal | None = None,
    metrics: dict[str, Any] | None = None,
    rule_results: list[Any] | None = None,
    exclusion_reasons: list[Any] | None = None,
) -> MagicMock:
    """Build a mock that looks like a :class:`CandidatePoolItemRow`."""

    row = MagicMock(spec=CandidatePoolItemRow)
    row.run_id = run_id or uuid4()
    row.instrument_id = instrument_id or uuid4()
    row.included = included
    row.rank = rank
    row.total_score = total_score
    row.metrics = metrics if metrics is not None else {"liquidity": "1.5"}
    row.rule_results = rule_results if rule_results is not None else []
    row.exclusion_reasons = exclusion_reasons if exclusion_reasons is not None else []
    return row


class SqlAlchemyCandidatePoolRunRepositoryMockTests(unittest.TestCase):
    """Mock-based tests for :class:`SqlAlchemyCandidatePoolRunRepository`."""

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyCandidatePoolRunRepository(self._session)

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------

    def test_add_inserts_calculated_row(self) -> None:
        run = _make_run(status=CandidatePoolStatus.CALCULATED)

        result = self._repo.add(run)

        self.assertEqual(self._session.add.call_count, 1)
        self.assertEqual(self._session.flush.call_count, 1)
        added_row = self._session.add.call_args[0][0]
        self.assertIsInstance(added_row, CandidatePoolRunRow)
        self.assertEqual(added_row.status, "calculated")
        self.assertEqual(added_row.trade_date, run.trade_date)
        self.assertEqual(added_row.algorithm_key, run.algorithm_key)
        self.assertEqual(added_row.algorithm_version, run.algorithm_version)
        self.assertEqual(added_row.parameter_set_key, run.parameter_set_key)
        self.assertEqual(added_row.parameter_hash, run.parameter_hash)
        self.assertEqual(added_row.input_snapshot_id, run.input_snapshot_id)
        self.assertEqual(
            added_row.market_data_fingerprint, run.market_data_fingerprint
        )
        self.assertEqual(added_row.input_row_count, run.input_row_count)
        self.assertEqual(added_row.included_count, run.included_count)
        self.assertEqual(added_row.started_at, run.created_at)
        self.assertEqual(added_row.quality_summary, {})
        self.assertIsInstance(result, CandidatePoolRun)
        self.assertEqual(result.id, run.id)
        self.assertEqual(result.status, CandidatePoolStatus.CALCULATED)

    def test_add_writes_market_data_fingerprint(self) -> None:
        fingerprint = "1" * 64
        run = _make_run(market_data_fingerprint=fingerprint)

        result = self._repo.add(run)

        added_row = self._session.add.call_args[0][0]
        self.assertEqual(
            added_row.market_data_fingerprint, fingerprint
        )
        self.assertEqual(result.market_data_fingerprint, fingerprint)

    def test_add_persists_quality_summary(self) -> None:
        run = _make_run()

        self._repo.add(run, quality_summary={"coverage": 0.97, "rule_errors": 0})

        added_row = self._session.add.call_args[0][0]
        self.assertEqual(
            added_row.quality_summary,
            {"coverage": 0.97, "rule_errors": 0},
        )

    def test_add_rejects_non_calculated_state(self) -> None:
        run = _make_run(status=CandidatePoolStatus.VALIDATED)

        with self.assertRaises(ValueError):
            self._repo.add(run)
        self._session.add.assert_not_called()

    # ------------------------------------------------------------------
    # get_by_id
    # ------------------------------------------------------------------

    def test_get_by_id_returns_run_when_present(self) -> None:
        run_id = uuid4()
        fingerprint = "2" * 64
        row = _make_run_row(
            row_id=run_id, status="validated", market_data_fingerprint=fingerprint
        )
        self._session.get.return_value = row

        result = self._repo.get_by_id(run_id)

        self._session.get.assert_called_once_with(CandidatePoolRunRow, run_id)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, run_id)
        self.assertEqual(result.status, CandidatePoolStatus.VALIDATED)
        self.assertEqual(result.market_data_fingerprint, fingerprint)

    def test_row_to_candidate_pool_run_round_trips_market_data_fingerprint(
        self,
    ) -> None:
        fingerprint = "3" * 64
        run_id = uuid4()
        row = _make_run_row(
            row_id=run_id, status="validated", market_data_fingerprint=fingerprint
        )
        self._session.get.return_value = row

        result = self._repo.get_by_id(run_id)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result.market_data_fingerprint, fingerprint
        )

    def test_get_by_id_returns_none_when_absent(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        result = self._repo.get_by_id(missing)

        self._session.get.assert_called_once_with(CandidatePoolRunRow, missing)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # get_by_natural_key
    # ------------------------------------------------------------------

    def test_get_by_natural_key_returns_run_when_present(self) -> None:
        snapshot_id = uuid4()
        fingerprint = "4" * 64
        row = _make_run_row(
            status="published",
            algorithm_key="candidate_pool.v1",
            algorithm_version="v1.0",
            parameter_hash="a" * 64,
            input_snapshot_id=snapshot_id,
            market_data_fingerprint=fingerprint,
            published_at=_utc(2026, 7, 31, 11),
        )
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = row

        result = self._repo.get_by_natural_key(
            trade_date=date(2026, 7, 31),
            algorithm_key="candidate_pool.v1",
            algorithm_version="v1.0",
            parameter_hash="a" * 64,
            input_snapshot_id=snapshot_id,
            market_data_fingerprint=fingerprint,
        )

        self.assertEqual(self._session.scalars.call_count, 1)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, row.id)
        self.assertEqual(result.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(result.input_snapshot_id, snapshot_id)
        self.assertEqual(result.parameter_hash, "a" * 64)
        self.assertEqual(result.market_data_fingerprint, fingerprint)

    def test_get_by_natural_key_returns_none_when_absent(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        result = self._repo.get_by_natural_key(
            trade_date=date(2026, 7, 31),
            algorithm_key="candidate_pool.v1",
            algorithm_version="v1.0",
            parameter_hash="a" * 64,
            input_snapshot_id=uuid4(),
            market_data_fingerprint="5" * 64,
        )

        self.assertEqual(self._session.scalars.call_count, 1)
        self.assertIsNone(result)

    def test_get_by_natural_key_requires_market_data_fingerprint(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        with self.assertRaises(TypeError):
            self._repo.get_by_natural_key(
                trade_date=date(2026, 7, 31),
                algorithm_key="candidate_pool.v1",
                algorithm_version="v1.0",
                parameter_hash="a" * 64,
                input_snapshot_id=uuid4(),
            )
        self._session.scalars.assert_not_called()

    def test_get_by_natural_key_filters_by_market_data_fingerprint(self) -> None:
        snapshot_id = uuid4()
        target_fingerprint = "6" * 64
        other_fingerprint = "7" * 64
        scalars_mock = self._session.scalars.return_value
        scalars_mock.first.return_value = None

        result = self._repo.get_by_natural_key(
            trade_date=date(2026, 7, 31),
            algorithm_key="candidate_pool.v1",
            algorithm_version="v1.0",
            parameter_hash="a" * 64,
            input_snapshot_id=snapshot_id,
            market_data_fingerprint=target_fingerprint,
        )

        self.assertEqual(self._session.scalars.call_count, 1)
        stmt = self._session.scalars.call_args[0][0]
        column_comparisons = list(stmt.whereclause.get_children())
        fingerprints = [
            child.right.value
            for child in column_comparisons
            if getattr(child.left, "name", None) == "market_data_fingerprint"
        ]
        self.assertEqual(fingerprints, [target_fingerprint])
        self.assertNotIn(other_fingerprint, fingerprints)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # list_by_status / list_by_trade_date
    # ------------------------------------------------------------------

    def test_list_by_status_filters_and_orders(self) -> None:
        first = _make_run_row(status="calculated")
        second = _make_run_row(status="calculated")
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [first, second]

        result = self._repo.list_by_status(CandidatePoolStatus.CALCULATED)

        self.assertEqual(self._session.scalars.call_count, 1)
        scalars_mock.all.assert_called_once_with()
        self.assertEqual(len(result), 2)
        self.assertTrue(
            all(r.status == CandidatePoolStatus.CALCULATED for r in result)
        )
        self.assertTrue(all(isinstance(r, CandidatePoolRun) for r in result))

    def test_list_by_status_accepts_raw_string(self) -> None:
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = []

        result = self._repo.list_by_status("calculated")

        self.assertEqual(result, [])
        # The repository must translate the string into the same SQL
        # path - the SELECT call is made exactly once.
        self.assertEqual(self._session.scalars.call_count, 1)

    def test_list_by_status_rejects_negative_pagination(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_status(
                CandidatePoolStatus.CALCULATED, limit=-1
            )
        with self.assertRaises(ValueError):
            self._repo.list_by_status(
                CandidatePoolStatus.CALCULATED, offset=-1
            )
        self._session.scalars.assert_not_called()

    def test_list_by_trade_date_returns_runs(self) -> None:
        run_a = _make_run_row()
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [run_a]

        result = self._repo.list_by_trade_date(date(2026, 7, 31))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].trade_date, run_a.trade_date)
        self.assertEqual(self._session.scalars.call_count, 1)

    def test_list_by_trade_date_rejects_negative_pagination(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_trade_date(date(2026, 7, 31), limit=-1)
        with self.assertRaises(ValueError):
            self._repo.list_by_trade_date(date(2026, 7, 31), offset=-1)
        self._session.scalars.assert_not_called()

    # ------------------------------------------------------------------
    # transition_status
    # ------------------------------------------------------------------

    def test_transition_status_validated_persists_status(self) -> None:
        run_id = uuid4()
        finished = _utc(2026, 7, 31, 10)
        existing = _make_run_row(row_id=run_id, status="calculated")
        self._session.get.return_value = existing

        result = self._repo.transition_status(
            run_id, CandidatePoolStatus.VALIDATED, at=finished
        )

        self._session.get.assert_called_once_with(CandidatePoolRunRow, run_id)
        self.assertEqual(existing.status, "validated")
        self.assertEqual(existing.finished_at, finished)
        self.assertIsNone(existing.published_at)
        self.assertIsNone(existing.rejected_at)
        self.assertEqual(self._session.flush.call_count, 1)
        self.assertEqual(result.status, CandidatePoolStatus.VALIDATED)
        self.assertEqual(result.finished_at, finished)

    def test_transition_status_published_sets_published_at(self) -> None:
        run_id = uuid4()
        published = _utc(2026, 7, 31, 11)
        existing = _make_run_row(row_id=run_id, status="validated")
        self._session.get.return_value = existing

        result = self._repo.transition_status(
            run_id, CandidatePoolStatus.PUBLISHED, at=published
        )

        self.assertEqual(existing.status, "published")
        self.assertEqual(existing.published_at, published)
        self.assertEqual(result.status, CandidatePoolStatus.PUBLISHED)
        self.assertEqual(result.published_at, published)

    def test_transition_status_rejected_requires_reason(self) -> None:
        run_id = uuid4()
        rejected = _utc(2026, 7, 31, 11)
        existing = _make_run_row(row_id=run_id, status="validated")
        self._session.get.return_value = existing

        with self.assertRaises(ValueError):
            self._repo.transition_status(
                run_id, CandidatePoolStatus.REJECTED, at=rejected
            )
        self._session.flush.assert_not_called()
        self.assertEqual(existing.status, "validated")
        self.assertIsNone(existing.rejected_at)

    def test_transition_status_rejected_persists_reason(self) -> None:
        run_id = uuid4()
        rejected = _utc(2026, 7, 31, 11)
        existing = _make_run_row(row_id=run_id, status="validated")
        self._session.get.return_value = existing

        result = self._repo.transition_status(
            run_id,
            CandidatePoolStatus.REJECTED,
            at=rejected,
            rejection_reason="coverage below threshold",
        )

        self.assertEqual(existing.status, "rejected")
        self.assertEqual(existing.rejected_at, rejected)
        self.assertEqual(existing.rejection_reason, "coverage below threshold")
        self.assertEqual(result.status, CandidatePoolStatus.REJECTED)
        self.assertEqual(result.rejection_reason, "coverage below threshold")

    def test_transition_status_illegal_skip_publish_raises(self) -> None:
        run_id = uuid4()
        published = _utc(2026, 7, 31, 11)
        existing = _make_run_row(row_id=run_id, status="calculated")
        self._session.get.return_value = existing

        # The state machine forbids CALCULATED -> PUBLISHED; the
        # repository surfaces the domain ``ValueError`` unchanged and
        # does not touch the row.
        with self.assertRaises(ValueError):
            self._repo.transition_status(
                run_id, CandidatePoolStatus.PUBLISHED, at=published
            )
        self._session.flush.assert_not_called()
        self.assertEqual(existing.status, "calculated")
        self.assertIsNone(existing.published_at)

    def test_transition_status_unknown_run_raises_lookup_error(self) -> None:
        missing = uuid4()
        self._session.get.return_value = None

        with self.assertRaises(LookupError):
            self._repo.transition_status(
                missing,
                CandidatePoolStatus.VALIDATED,
                at=_utc(2026, 7, 31, 10),
            )


class SqlAlchemyCandidatePoolItemRepositoryMockTests(unittest.TestCase):
    """Mock-based tests for :class:`SqlAlchemyCandidatePoolItemRepository`."""

    def setUp(self) -> None:
        self._session = MagicMock(name="Session")
        self._repo = SqlAlchemyCandidatePoolItemRepository(self._session)

    # ------------------------------------------------------------------
    # bulk_add
    # ------------------------------------------------------------------

    def test_bulk_add_empty_returns_zero(self) -> None:
        result = self._repo.bulk_add(uuid4(), [])

        self.assertEqual(result, 0)
        self._session.add_all.assert_not_called()
        self._session.flush.assert_not_called()

    def test_bulk_add_persists_rows_for_each_item(self) -> None:
        run_id = uuid4()
        items = [
            _make_item(
                instrument_id=uuid4(),
                included=True,
                rank=1,
                total_score=Decimal("0.91"),
                metrics={"liquidity": Decimal("1.5")},
                rule_results=(
                    RuleOutcome(
                        rule_key="liquidity",
                        passed=True,
                        severity=RuleSeverity.INFO,
                        value=Decimal("1.5"),
                        threshold=Decimal("1.0"),
                    ),
                ),
            ),
            _make_item(
                instrument_id=uuid4(),
                included=False,
                rank=None,
                total_score=None,
                metrics={},
                exclusion_reasons=(
                    ExclusionReason(code="suspended", message="paused"),
                ),
            ),
        ]

        count = self._repo.bulk_add(run_id, items)

        self.assertEqual(count, 2)
        self.assertEqual(self._session.add_all.call_count, 1)
        self.assertEqual(self._session.flush.call_count, 1)
        rows = self._session.add_all.call_args[0][0]
        self.assertEqual(len(rows), 2)
        for row, item in zip(rows, items):
            self.assertIsInstance(row, CandidatePoolItemRow)
            self.assertEqual(row.run_id, run_id)
            self.assertEqual(row.instrument_id, item.instrument_id.value)
            self.assertEqual(row.included, item.included)
            if item.included:
                self.assertEqual(row.rank, 1)
                self.assertEqual(row.total_score, Decimal("0.91"))
                self.assertEqual(row.metrics, {"liquidity": "1.5"})
                self.assertEqual(
                    row.rule_results,
                    [
                        {
                            "rule_key": "liquidity",
                            "passed": True,
                            "severity": "info",
                            "value": "1.5",
                            "threshold": "1.0",
                        }
                    ],
                )
            else:
                self.assertIsNone(row.rank)
                self.assertIsNone(row.total_score)
                self.assertEqual(
                    row.exclusion_reasons,
                    [{"code": "suspended", "message": "paused"}],
                )

    # ------------------------------------------------------------------
    # list_by_run_id
    # ------------------------------------------------------------------

    def test_list_by_run_id_returns_decoded_items(self) -> None:
        run_id = uuid4()
        instrument_id = uuid4()
        row = _make_item_row(
            run_id=run_id,
            instrument_id=instrument_id,
            included=True,
            rank=1,
            total_score=Decimal("0.91"),
            metrics={"liquidity": "1.5", "stability": "0.7"},
            rule_results=[
                {
                    "rule_key": "liquidity",
                    "passed": True,
                    "severity": "info",
                    "value": "1.5",
                    "threshold": "1.0",
                }
            ],
            exclusion_reasons=[],
        )
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [row]

        items = self._repo.list_by_run_id(run_id)

        self.assertEqual(self._session.scalars.call_count, 1)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIsInstance(item, CandidatePoolItem)
        self.assertEqual(item.instrument_id.value, instrument_id)
        self.assertTrue(item.included)
        self.assertEqual(item.rank, 1)
        self.assertEqual(item.total_score, Decimal("0.91"))
        self.assertEqual(item.metrics["liquidity"], Decimal("1.5"))
        self.assertEqual(item.metrics["stability"], Decimal("0.7"))
        self.assertEqual(len(item.rule_results), 1)
        self.assertEqual(item.rule_results[0].rule_key, "liquidity")
        self.assertEqual(item.rule_results[0].severity, RuleSeverity.INFO)
        self.assertEqual(item.rule_results[0].value, Decimal("1.5"))
        self.assertEqual(item.rule_results[0].threshold, Decimal("1.0"))

    def test_list_by_run_id_decodes_exclusion_reasons(self) -> None:
        run_id = uuid4()
        instrument_id = uuid4()
        row = _make_item_row(
            run_id=run_id,
            instrument_id=instrument_id,
            included=False,
            rank=None,
            total_score=None,
            exclusion_reasons=[
                {"code": "suspended", "message": "paused"},
                {"code": "min_listing_days", "message": "too new"},
            ],
        )
        scalars_mock = self._session.scalars.return_value
        scalars_mock.all.return_value = [row]

        items = self._repo.list_by_run_id(run_id)

        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].included)
        self.assertIsNone(items[0].rank)
        self.assertEqual(len(items[0].exclusion_reasons), 2)
        self.assertEqual(items[0].exclusion_reasons[0].code, "suspended")
        self.assertEqual(items[0].exclusion_reasons[1].code, "min_listing_days")

    def test_list_by_run_id_rejects_negative_pagination(self) -> None:
        with self.assertRaises(ValueError):
            self._repo.list_by_run_id(uuid4(), limit=-1)
        with self.assertRaises(ValueError):
            self._repo.list_by_run_id(uuid4(), offset=-1)
        self._session.scalars.assert_not_called()


if __name__ == "__main__":
    unittest.main()