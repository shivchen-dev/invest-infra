"""Mock-based unit tests for the ETF-profile field-evidence storage repository.

The tests drive a :class:`unittest.mock.MagicMock` ``Session`` so the
:class:`invest_storage.repositories.SqlAlchemyEtfProfileFieldRepository`
can be verified without spinning up Testcontainers or speaking to a real
PostgreSQL. They pin five contracts:

- :meth:`SqlAlchemyEtfProfileFieldRepository.add` inserts an
  ``analytics.etf_profile_fields`` row carrying every domain field from
  the :class:`invest_domain.etf_profile.models.FieldEvidence` input,
  including the type-discriminated value envelope
  (``field_value_text`` / ``field_value_numeric`` / ``field_value_date``)
  and the ``content_hash`` natural key.
- :meth:`SqlAlchemyEtfProfileFieldRepository.upsert` is idempotent on
  the ``content_hash`` natural key: a re-write of the same business
  content is a no-op; a different provider / revision (different
  ``content_hash``) is stored as a coexisting row so the evidence
  history is preserved.
- :meth:`SqlAlchemyEtfProfileFieldRepository.get_by_instrument` returns
  every evidence row for ``instrument_id`` ordered by ``created_at``
  ascending, mapped back to the domain :class:`FieldEvidence`.
- :meth:`SqlAlchemyEtfProfileFieldRepository.get_by_instrument_field`
  returns every evidence row for ``(instrument_id, field_key)``
  ordered by ``created_at`` ascending, mapped back to the domain
  :class:`FieldEvidence`.
- ``TEXT`` / ``DECIMAL`` / ``DATE`` / ``None`` values round-trip end to
  end: the column carrying the value depends on the ``value_type`` and
  the alternative columns stay ``NULL``.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from invest_domain.etf_profile import (
    FieldEvidence,
    FieldEvidenceSource,
    FieldKey,
    FieldValueType,
)
from invest_domain.research import QualityStatus
from invest_storage import (
    EtfProfileFieldRow,
    SqlAlchemyEtfProfileFieldRepository,
)
from sqlalchemy.orm import Session

_OBSERVED_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


def _source(**overrides: object) -> FieldEvidenceSource:
    base: dict[str, object] = {
        "provider_key": "akshare",
        "dataset_key": "etf_profile_snapshot",
        "observed_at": _OBSERVED_AT,
        "source_batch_id": uuid4(),
        "revision": 1,
    }
    base.update(overrides)
    return FieldEvidenceSource(**base)


def _evidence(
    *,
    instrument_id: UUID | None = None,
    field_key: FieldKey = FieldKey.MANAGER,
    value: str | Decimal | date | None = "华夏基金",
    value_type: FieldValueType = FieldValueType.TEXT,
    source: FieldEvidenceSource | None = None,
    quality_status: QualityStatus = QualityStatus.COMPLETE,
    confidence_score: Decimal = Decimal("0.95"),
) -> FieldEvidence:
    return FieldEvidence(
        instrument_id=instrument_id or uuid4(),
        field_key=field_key,
        value=value,
        value_type=value_type,
        source=source or _source(),
        quality_status=quality_status,
        confidence_score=confidence_score,
    )


def _make_row(evidence: FieldEvidence) -> MagicMock:
    """Build a MagicMock row that mirrors the column layout for ``evidence``."""

    row = MagicMock(spec=EtfProfileFieldRow)
    row.id = uuid4()
    row.instrument_id = evidence.instrument_id
    row.field_key = evidence.field_key.value
    row.value_type = evidence.value_type.value
    row.field_value_text = (
        evidence.value if isinstance(evidence.value, str) else None
    )
    row.field_value_numeric = (
        evidence.value if isinstance(evidence.value, Decimal) else None
    )
    row.field_value_date = (
        evidence.value if isinstance(evidence.value, date) else None
    )
    row.source_provider = evidence.source.provider_key
    row.source_dataset = evidence.source.dataset_key
    row.observed_at = evidence.source.observed_at
    row.source_batch_id = evidence.source.source_batch_id
    row.source_revision = evidence.source.revision
    row.quality_status = evidence.quality_status.value
    row.confidence_score = evidence.confidence_score
    row.content_hash = evidence.content_hash
    created_at = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    row.created_at = created_at
    # Mirror the row's ``created_at`` back onto the domain evidence so
    # the round-trip equality check in the test matches the same
    # audit timestamp the storage layer would persist.
    object.__setattr__(evidence, "created_at", created_at)
    return row


class EtfProfileFieldRepositoryUpsertTests(unittest.TestCase):
    """Mock tests covering the ``add`` / ``upsert`` write paths."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfProfileFieldRepository(self._session)

    def test_add_inserts_text_row_with_all_columns(self) -> None:
        evidence = _evidence()
        existing = _make_row(evidence)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            existing.id
        )
        self._session.scalars.return_value.first.return_value = existing

        result = self._repo.add(evidence)

        self.assertEqual(result, evidence)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params

        self.assertEqual(params["instrument_id"], evidence.instrument_id)
        self.assertEqual(params["field_key"], evidence.field_key.value)
        self.assertEqual(params["value_type"], evidence.value_type.value)
        self.assertEqual(params["field_value_text"], evidence.value)
        self.assertIsNone(params["field_value_numeric"])
        self.assertIsNone(params["field_value_date"])
        self.assertEqual(
            params["source_provider"], evidence.source.provider_key
        )
        self.assertEqual(
            params["source_dataset"], evidence.source.dataset_key
        )
        self.assertEqual(params["observed_at"], evidence.source.observed_at)
        self.assertEqual(
            params["source_batch_id"], evidence.source.source_batch_id
        )
        self.assertEqual(
            params["source_revision"], evidence.source.revision
        )
        self.assertEqual(
            params["quality_status"], evidence.quality_status.value
        )
        self.assertEqual(
            params["confidence_score"], evidence.confidence_score
        )
        self.assertEqual(params["content_hash"], evidence.content_hash)

    def test_add_inserts_decimal_row_into_numeric_column(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.MANAGEMENT_FEE,
            value=Decimal("0.0015"),
            value_type=FieldValueType.DECIMAL,
        )
        existing = _make_row(evidence)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            existing.id
        )
        self._session.scalars.return_value.first.return_value = existing

        self._repo.add(evidence)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertIsNone(params["field_value_text"])
        self.assertEqual(
            params["field_value_numeric"], Decimal("0.0015")
        )
        self.assertIsNone(params["field_value_date"])

    def test_add_inserts_date_row_into_date_column(self) -> None:
        inception = date(2013, 3, 25)
        evidence = _evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=inception,
            value_type=FieldValueType.DATE,
        )
        existing = _make_row(evidence)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            existing.id
        )
        self._session.scalars.return_value.first.return_value = existing

        self._repo.add(evidence)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertIsNone(params["field_value_text"])
        self.assertIsNone(params["field_value_numeric"])
        self.assertEqual(params["field_value_date"], inception)

    def test_add_inserts_none_value_for_missing_evidence(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.MISSING,
        )
        existing = _make_row(evidence)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            existing.id
        )
        self._session.scalars.return_value.first.return_value = existing

        self._repo.add(evidence)

        statement = self._session.execute.call_args.args[0]
        params = statement.compile().params
        self.assertIsNone(params["field_value_text"])
        self.assertIsNone(params["field_value_numeric"])
        self.assertIsNone(params["field_value_date"])

    def test_add_returns_existing_row_on_content_hash_conflict(self) -> None:
        evidence = _evidence()
        existing = _make_row(evidence)
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = existing

        result = self._repo.add(evidence)

        self.assertEqual(result, evidence)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

    def test_add_raises_when_conflict_but_row_missing(self) -> None:
        evidence = _evidence()
        self._session.execute.return_value.scalar_one_or_none.return_value = None
        self._session.scalars.return_value.first.return_value = None

        with self.assertRaises(RuntimeError):
            self._repo.add(evidence)

    def test_upsert_inserts_new_row(self) -> None:
        evidence = _evidence()
        existing = _make_row(evidence)
        # ``upsert`` first looks up by content_hash (returns None); then
        # ``add`` calls ``execute`` to insert; the post-insert
        # ``_find_by_content_hash`` call returns the persisted row.
        self._session.scalars.return_value.first.side_effect = [
            None,
            existing,
        ]
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            existing.id
        )

        result = self._repo.upsert(evidence)

        self.assertEqual(result, evidence)
        self._session.execute.assert_called_once()
        self._session.flush.assert_called_once_with()

    def test_upsert_is_noop_on_content_hash_match(self) -> None:
        evidence = _evidence()
        existing = _make_row(evidence)
        self._session.scalars.return_value.first.return_value = existing

        result = self._repo.upsert(evidence)

        self.assertEqual(result, evidence)
        self._session.execute.assert_not_called()
        self._session.flush.assert_not_called()

    def test_upsert_allows_distinct_provider_revisions_to_coexist(self) -> None:
        """Two different ``content_hash`` values must coexist as separate rows.

        The repository never collapses distinct provider / revision
        observations into a single row; the ``content_hash`` natural key
        is what guards idempotency, while a different ``source_revision``
        produces a different digest and therefore a new row.
        """

        first = _evidence()
        second = _evidence(
            field_key=first.field_key,
            value=first.value,
            value_type=first.value_type,
            source=_source(
                provider_key=first.source.provider_key,
                dataset_key=first.source.dataset_key,
                observed_at=first.source.observed_at,
                source_batch_id=first.source.source_batch_id,
                revision=first.source.revision + 1,
            ),
        )
        self.assertNotEqual(first.content_hash, second.content_hash)

        # First call: insert succeeds, returns first row.
        first_row = _make_row(first)
        self._session.execute.return_value.scalar_one_or_none.return_value = (
            first_row.id
        )
        self._session.scalars.return_value.first.return_value = first_row
        first_result = self._repo.add(first)
        self.assertEqual(first_result, first)

        # Second call: different content_hash => no existing row => insert.
        self._session.execute.reset_mock()
        self._session.flush.reset_mock()
        self._session.scalars.return_value.first.return_value = None
        second_row = _make_row(second)
        self._session.scalars.return_value.first.return_value = second_row
        second_result = self._repo.add(second)
        self.assertEqual(second_result, second)
        self._session.execute.assert_called_once()


class EtfProfileFieldRepositoryReadTests(unittest.TestCase):
    """Mock tests covering the read surfaces used by the field-evidence API."""

    def setUp(self) -> None:
        self._session = MagicMock(spec=Session)
        self._repo = SqlAlchemyEtfProfileFieldRepository(self._session)

    def test_get_by_instrument_maps_rows_in_order(self) -> None:
        first = _evidence()
        second = _evidence(instrument_id=first.instrument_id)
        self._session.scalars.return_value.all.return_value = [
            _make_row(first),
            _make_row(second),
        ]

        result = self._repo.get_by_instrument(first.instrument_id)

        self.assertEqual(result, [first, second])
        self._session.scalars.assert_called_once()

    def test_get_by_instrument_returns_empty_list_when_absent(self) -> None:
        self._session.scalars.return_value.all.return_value = []

        result = self._repo.get_by_instrument(uuid4())

        self.assertEqual(result, [])

    def test_get_by_instrument_field_maps_rows_in_order(self) -> None:
        first = _evidence(field_key=FieldKey.MANAGER)
        second = _evidence(
            field_key=FieldKey.MANAGER,
            source=_source(
                provider_key=first.source.provider_key,
                dataset_key=first.source.dataset_key,
                observed_at=first.source.observed_at,
                source_batch_id=first.source.source_batch_id,
                revision=first.source.revision + 1,
            ),
        )
        self._session.scalars.return_value.all.return_value = [
            _make_row(first),
            _make_row(second),
        ]

        result = self._repo.get_by_instrument_field(
            first.instrument_id, FieldKey.MANAGER
        )

        self.assertEqual(result, [first, second])
        self._session.scalars.assert_called_once()

    def test_get_by_instrument_field_returns_empty_list_when_absent(self) -> None:
        self._session.scalars.return_value.all.return_value = []

        result = self._repo.get_by_instrument_field(
            uuid4(), FieldKey.MANAGER
        )

        self.assertEqual(result, [])


class EtfProfileFieldRepositoryValueTypeTests(unittest.TestCase):
    """Mock tests covering the value-type discriminated output mapping."""

    def test_text_evidence_round_trips(self) -> None:
        evidence = _evidence(value="华夏基金", value_type=FieldValueType.TEXT)
        row = _make_row(evidence)
        session = MagicMock(spec=Session)
        session.scalars.return_value.all.return_value = [row]
        repo = SqlAlchemyEtfProfileFieldRepository(session)

        result = repo.get_by_instrument(evidence.instrument_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], evidence)
        self.assertEqual(result[0].value, "华夏基金")

    def test_decimal_evidence_round_trips(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.MANAGEMENT_FEE,
            value=Decimal("0.0015"),
            value_type=FieldValueType.DECIMAL,
        )
        row = _make_row(evidence)
        session = MagicMock(spec=Session)
        session.scalars.return_value.all.return_value = [row]
        repo = SqlAlchemyEtfProfileFieldRepository(session)

        result = repo.get_by_instrument(evidence.instrument_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].value, Decimal("0.0015"))

    def test_date_evidence_round_trips(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.INCEPTION_DATE,
            value=date(2013, 3, 25),
            value_type=FieldValueType.DATE,
        )
        row = _make_row(evidence)
        session = MagicMock(spec=Session)
        session.scalars.return_value.all.return_value = [row]
        repo = SqlAlchemyEtfProfileFieldRepository(session)

        result = repo.get_by_instrument(evidence.instrument_id)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].value, date(2013, 3, 25))

    def test_none_value_evidence_round_trips(self) -> None:
        evidence = _evidence(
            field_key=FieldKey.AUM,
            value=None,
            value_type=FieldValueType.DECIMAL,
            quality_status=QualityStatus.MISSING,
        )
        row = _make_row(evidence)
        session = MagicMock(spec=Session)
        session.scalars.return_value.all.return_value = [row]
        repo = SqlAlchemyEtfProfileFieldRepository(session)

        result = repo.get_by_instrument(evidence.instrument_id)

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].value)
        self.assertEqual(result[0].quality_status, QualityStatus.MISSING)


if __name__ == "__main__":
    unittest.main()
