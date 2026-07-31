"""Tests for the ``market_data`` bounded context (value types + models)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from invest_domain.instruments.models import Instrument, InstrumentId, InstrumentType
from invest_domain.market_data.models import (
    BarSource,
    DailyBar,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderFailureStage,
    ProviderRequest,
    bar_source_metadata_hash,
)
from invest_domain.market_data.ports import (
    EtfMarketDataProvider,
    InstrumentProvider,
    ProviderDataContractError,
)
from invest_domain.market_data.values import (
    Adjust,
    Currency,
    Exchange,
    TradingStatus,
)
from invest_domain.shared.canonical import CANONICAL_HASH_SCHEMA_VERSION

from .conftest import make_bar_source


class TestValueEnums:
    def test_adjust_production_only_is_none(self) -> None:
        assert Adjust.production_only() == (Adjust.NONE,)

    @pytest.mark.parametrize("member", ["NONE", "QFQ", "HFQ"])
    def test_adjust_members_exist(self, member: str) -> None:
        assert hasattr(Adjust, member)

    def test_exchange_allow_list_is_sse_szse(self) -> None:
        assert {m.value for m in Exchange} == {"SSE", "SZSE"}

    def test_currency_is_cny(self) -> None:
        assert {m.value for m in Currency} == {"CNY"}

    def test_trading_status_values(self) -> None:
        assert {m.value for m in TradingStatus} == {"normal", "suspended"}


class TestProviderDataContractError:
    def test_code_and_message_are_required(self) -> None:
        with pytest.raises(ValueError):
            ProviderDataContractError(code="", message="oops")
        with pytest.raises(ValueError):
            ProviderDataContractError(code="x", message="   ")

    def test_repr_includes_code(self) -> None:
        err = ProviderDataContractError(code="MALFORMED", message="bad payload")
        assert "[MALFORMED]" in str(err)
        assert "bad payload" in str(err)
        assert err.provider_key is None

    def test_provider_key_is_optional(self) -> None:
        err = ProviderDataContractError(
            code="MALFORMED", message="bad payload", provider_key="cifang"
        )
        assert err.provider_key == "cifang"

    def test_provider_data_contract_error_is_a_value_error(self) -> None:
        # Adapters may use ``except ValueError`` for the broad family.
        err = ProviderDataContractError(code="X", message="Y")
        assert isinstance(err, ValueError)


class TestBarSource:
    def test_blank_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            BarSource(
                provider_key="",
                source_batch_id=uuid4(),
                observed_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
            )

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            BarSource(
                provider_key="fixture_dev",
                source_batch_id=uuid4(),
                observed_at=datetime(2026, 7, 30),
            )

    def test_metadata_hash_is_deterministic(self) -> None:
        batch_id = uuid4()
        observed = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
        a = bar_source_metadata_hash(
            BarSource("fixture_dev", batch_id, observed)
        )
        b = bar_source_metadata_hash(
            BarSource("fixture_dev", batch_id, observed)
        )
        assert a == b

    def test_metadata_hash_diffs_when_source_changes(self) -> None:
        # Sanity check: the source hash is independent of row_hash and
        # does change when audit metadata changes (e.g. new batch).
        h1 = bar_source_metadata_hash(make_bar_source())
        h2 = bar_source_metadata_hash(make_bar_source())
        assert h1 != h2


class _Builder:
    """Builds DailyBar instances with all required fields, but flexible overrides."""

    def __init__(self, instrument_id: InstrumentId, source: BarSource) -> None:
        self._iid = instrument_id
        self._source = source

    def normal(
        self,
        *,
        trade_date: date = date(2026, 7, 30),
        open: str = "3.10",
        high: str = "3.18",
        low: str = "3.08",
        close: str = "3.15",
        prev_close: str = "3.09",
        volume: str = "1000",
        amount: str = "3150000",
        revision: int = 1,
        source: BarSource | None = None,
    ) -> DailyBar:
        return DailyBar.build(
            instrument_id=self._iid,
            trade_date=trade_date,
            open=Decimal(open),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            prev_close=Decimal(prev_close),
            volume=Decimal(volume),
            amount=Decimal(amount),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=source or self._source,
            revision=revision,
        )

    def suspended(
        self,
        *,
        trade_date: date = date(2026, 7, 30),
        revision: int = 1,
        source: BarSource | None = None,
    ) -> DailyBar:
        return DailyBar.build(
            instrument_id=self._iid,
            trade_date=trade_date,
            open=None,
            high=None,
            low=None,
            close=None,
            prev_close=None,
            volume=None,
            amount=None,
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.SUSPENDED,
            source=source or self._source,
            revision=revision,
        )


class TestDailyBarInvariants:
    def test_normal_bar_is_constructed(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        bar = _Builder(instrument_id, bar_source).normal()
        assert bar.trading_status is TradingStatus.NORMAL
        assert bar.adjustment is Adjust.NONE
        assert bar.row_hash is not None
        assert len(bar.row_hash) == 64

    def test_hash_is_64_hex(self, instrument_id: InstrumentId, bar_source: BarSource) -> None:
        bar = _Builder(instrument_id, bar_source).normal()
        assert all(c in "0123456789abcdef" for c in bar.row_hash)

    def test_same_data_same_hash(self, instrument_id: InstrumentId, bar_source: BarSource) -> None:
        a = _Builder(instrument_id, bar_source).normal()
        b = _Builder(instrument_id, bar_source).normal()
        assert a.row_hash == b.row_hash

    def test_different_close_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(close="3.15")
        b = _Builder(instrument_id, bar_source).normal(close="3.16")
        assert a.row_hash != b.row_hash

    def test_different_open_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(open="3.10")
        b = _Builder(instrument_id, bar_source).normal(open="3.11")
        assert a.row_hash != b.row_hash

    def test_different_high_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(high="3.18")
        b = _Builder(instrument_id, bar_source).normal(high="3.19")
        assert a.row_hash != b.row_hash

    def test_different_low_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(low="3.08")
        b = _Builder(instrument_id, bar_source).normal(low="3.07")
        assert a.row_hash != b.row_hash

    def test_different_prev_close_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(prev_close="3.09")
        b = _Builder(instrument_id, bar_source).normal(prev_close="3.10")
        assert a.row_hash != b.row_hash

    def test_different_volume_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(volume="1000")
        b = _Builder(instrument_id, bar_source).normal(volume="1001")
        assert a.row_hash != b.row_hash

    def test_different_amount_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(amount="3150000")
        b = _Builder(instrument_id, bar_source).normal(amount="3150001")
        assert a.row_hash != b.row_hash

    def test_different_trade_date_different_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(trade_date=date(2026, 7, 30))
        b = _Builder(instrument_id, bar_source).normal(trade_date=date(2026, 7, 31))
        assert a.row_hash != b.row_hash

    def test_different_instrument_id_different_hash(
        self, bar_source: BarSource
    ) -> None:
        a = _Builder(InstrumentId.generate(), bar_source).normal()
        b = _Builder(InstrumentId.generate(), bar_source).normal()
        assert a.row_hash != b.row_hash

    def test_suspended_bar_different_from_normal_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        normal = _Builder(instrument_id, bar_source).normal()
        suspended = _Builder(instrument_id, bar_source).suspended()
        assert normal.row_hash != suspended.row_hash

    # ---- ADR-0005 §8: audit-only fields MUST NOT change row_hash ----

    def test_revision_change_does_not_change_hash(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        """A revision bump (re-collect, no business change) MUST keep the same hash."""
        a = _Builder(instrument_id, bar_source).normal(revision=1)
        b = _Builder(instrument_id, bar_source).normal(revision=2)
        c = _Builder(instrument_id, bar_source).normal(revision=42)
        assert a.row_hash == b.row_hash == c.row_hash

    def test_source_change_does_not_change_hash(
        self, instrument_id: InstrumentId
    ) -> None:
        """Audit metadata (provider_key, source_batch_id, observed_at) MUST NOT
        affect row_hash; the same business content re-collected by a different
        batch must produce the same digest.
        """
        a = _Builder(instrument_id, make_bar_source()).normal()
        b = _Builder(
            instrument_id,
            make_bar_source(
                provider_key="cifang",
                source_batch_id=uuid4(),
                observed_at=datetime(2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc),
            ),
        ).normal()
        assert a.row_hash == b.row_hash

    def test_source_metadata_hash_versus_row_hash_are_distinct(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        bar = _Builder(instrument_id, bar_source).normal()
        audit_hash = bar_source_metadata_hash(bar_source)
        assert bar.row_hash != audit_hash
        assert len(bar.row_hash) == 64
        assert len(audit_hash) == 64

    # ---- Decimal / canonical normalization ----

    def test_decimal_normalization_strips_trailing_zeros(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(close="3.15")
        b = _Builder(instrument_id, bar_source).normal(close="3.15000")
        assert a.row_hash == b.row_hash

    def test_volume_normalization_is_canonical(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        a = _Builder(instrument_id, bar_source).normal(volume="1000")
        b = _Builder(instrument_id, bar_source).normal(volume="1000.0000")
        assert a.row_hash == b.row_hash

    # ---- Adjustment / status / numeric guards ----

    def test_qfq_adjustment_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="ADR-0005"):
            DailyBar.build(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                open=Decimal("3.10"),
                high=Decimal("3.18"),
                low=Decimal("3.08"),
                close=Decimal("3.15"),
                prev_close=Decimal("3.09"),
                volume=Decimal("1000"),
                amount=Decimal("3150000"),
                adjustment=Adjust.QFQ,
                trading_status=TradingStatus.NORMAL,
                source=bar_source,
                revision=1,
            )

    def test_hfq_adjustment_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="ADR-0005"):
            DailyBar.build(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                open=Decimal("3.10"),
                high=Decimal("3.18"),
                low=Decimal("3.08"),
                close=Decimal("3.15"),
                prev_close=Decimal("3.09"),
                volume=Decimal("1000"),
                amount=Decimal("3150000"),
                adjustment=Adjust.HFQ,
                trading_status=TradingStatus.NORMAL,
                source=bar_source,
                revision=1,
            )

    def test_high_below_open_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="high"):
            _Builder(instrument_id, bar_source).normal(open="3.30", high="3.20")

    def test_low_above_close_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="low"):
            _Builder(instrument_id, bar_source).normal(
                low="3.20", close="3.15", high="3.30"
            )

    def test_zero_open_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            _Builder(instrument_id, bar_source).normal(open="0")

    def test_negative_volume_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="volume"):
            _Builder(instrument_id, bar_source).normal(volume="-1")

    # ---- Suspended rows: no fabrication per ADR-0005 §6 ----

    def test_suspended_bar_rejects_ohlcv(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="SUSPENDED"):
            DailyBar.build(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                open=Decimal("3.10"),  # type: ignore[arg-type]
                high=Decimal("3.18"),  # type: ignore[arg-type]
                low=Decimal("3.08"),  # type: ignore[arg-type]
                close=Decimal("3.15"),  # type: ignore[arg-type]
                prev_close=Decimal("3.09"),  # type: ignore[arg-type]
                volume=Decimal("1000"),  # type: ignore[arg-type]
                amount=Decimal("3150000"),  # type: ignore[arg-type]
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.SUSPENDED,
                source=bar_source,
                revision=1,
            )

    def test_suspended_bar_is_constructed(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        bar = _Builder(instrument_id, bar_source).suspended()
        assert bar.trading_status is TradingStatus.SUSPENDED
        assert bar.open is None
        assert bar.row_hash is not None

    # ---- Revision / row_hash / hash_schema_version guards ----

    def test_revision_zero_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="revision"):
            _Builder(instrument_id, bar_source).normal(revision=0)

    def test_wrong_row_hash_is_rejected(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="row_hash"):
            DailyBar(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                open=Decimal("3.10"),
                high=Decimal("3.18"),
                low=Decimal("3.08"),
                close=Decimal("3.15"),
                prev_close=Decimal("3.09"),
                volume=Decimal("1000"),
                amount=Decimal("3150000"),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=bar_source,
                revision=1,
                row_hash="0" * 64,
            )

    def test_supplying_correct_row_hash_round_trips(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        bar = _Builder(instrument_id, bar_source).normal()
        verified = DailyBar(
            instrument_id=instrument_id,
            trade_date=date(2026, 7, 30),
            open=Decimal("3.10"),
            high=Decimal("3.18"),
            low=Decimal("3.08"),
            close=Decimal("3.15"),
            prev_close=Decimal("3.09"),
            volume=Decimal("1000"),
            amount=Decimal("3150000"),
            adjustment=Adjust.NONE,
            trading_status=TradingStatus.NORMAL,
            source=bar_source,
            revision=1,
            row_hash=bar.row_hash,
        )
        assert verified.row_hash == bar.row_hash

    def test_hash_schema_version_must_match_current(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        with pytest.raises(ValueError, match="hash_schema_version"):
            DailyBar(
                instrument_id=instrument_id,
                trade_date=date(2026, 7, 30),
                open=Decimal("3.10"),
                high=Decimal("3.18"),
                low=Decimal("3.08"),
                close=Decimal("3.15"),
                prev_close=Decimal("3.09"),
                volume=Decimal("1000"),
                amount=Decimal("3150000"),
                adjustment=Adjust.NONE,
                trading_status=TradingStatus.NORMAL,
                source=bar_source,
                revision=1,
                row_hash="0" * 64,
                hash_schema_version=CANONICAL_HASH_SCHEMA_VERSION + 1,
            )


class TestProviderRequest:
    def test_request_is_constructed(self) -> None:
        request = ProviderRequest(
            provider_key="fixture_dev",
            dataset_key="etf_daily_bars",
            request_key="req-1",
            params={"symbol": "510050"},
            created_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
        )
        assert request.provider_key == "fixture_dev"
        assert request.dataset_key == "etf_daily_bars"
        assert request.request_key == "req-1"
        assert request.params == {"symbol": "510050"}

    def test_blank_provider_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderRequest(
                provider_key="",
                dataset_key="etf_daily_bars",
                request_key="req-1",
            )

    def test_blank_dataset_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderRequest(
                provider_key="fixture_dev",
                dataset_key="",
                request_key="req-1",
            )

    def test_blank_request_key_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderRequest(
                provider_key="fixture_dev",
                dataset_key="etf_daily_bars",
                request_key="",
            )

    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderRequest(
                provider_key="fixture_dev",
                dataset_key="etf_daily_bars",
                request_key="req-1",
                created_at=datetime(2026, 7, 30, 8, 0, 0),
            )


class TestProviderAttempt:
    def test_attempt_is_constructed_for_succeeded(self) -> None:
        request_id = uuid4()
        started = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 7, 30, 8, 0, 5, tzinfo=timezone.utc)
        attempt = ProviderAttempt(
            request_id=request_id,
            attempt_number=1,
            status=ProviderAttemptStatus.SUCCEEDED,
            started_at=started,
            finished_at=finished,
            duration_ms=5_000,
        )
        assert attempt.request_id == request_id
        assert attempt.attempt_number == 1
        assert attempt.status is ProviderAttemptStatus.SUCCEEDED
        assert attempt.duration_ms == 5_000
        assert attempt.error_stage is None

    def test_failed_attempt_requires_error_stage_and_code(self) -> None:
        request_id = uuid4()
        started = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
        finished = datetime(2026, 7, 30, 8, 0, 5, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=request_id,
                attempt_number=1,
                status=ProviderAttemptStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_ms=5_000,
                error_stage=None,
                error_code="TIMEOUT",
                error_message="upstream timeout",
            )
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=request_id,
                attempt_number=1,
                status=ProviderAttemptStatus.FAILED,
                started_at=started,
                finished_at=finished,
                duration_ms=5_000,
                error_stage=ProviderFailureStage.TIMEOUT,
                error_code="",
                error_message="upstream timeout",
            )

    def test_attempt_number_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=uuid4(),
                attempt_number=0,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=timezone.utc),
                duration_ms=5_000,
            )

    def test_naive_started_at_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=uuid4(),
                attempt_number=1,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=datetime(2026, 7, 30, 8, 0, 0),
                finished_at=datetime(2026, 7, 30, 8, 0, 5, tzinfo=timezone.utc),
                duration_ms=5_000,
            )

    def test_finished_before_started_is_rejected(self) -> None:
        started = datetime(2026, 7, 30, 8, 0, 5, tzinfo=timezone.utc)
        finished = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=uuid4(),
                attempt_number=1,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=started,
                finished_at=finished,
                duration_ms=-5_000,
            )

    def test_negative_duration_is_rejected(self) -> None:
        started = datetime(2026, 7, 30, 8, 0, 0, tzinfo=timezone.utc)
        finished = started + timedelta(seconds=5)
        with pytest.raises(ValueError):
            ProviderAttempt(
                request_id=uuid4(),
                attempt_number=1,
                status=ProviderAttemptStatus.SUCCEEDED,
                started_at=started,
                finished_at=finished,
                duration_ms=-1,
            )


class TestProviderBatch:
    def test_batch_is_constructed(
        self, instrument_id: InstrumentId, bar_source: BarSource
    ) -> None:
        bar = _Builder(instrument_id, bar_source).normal()
        batch = ProviderBatch(
            attempt_id=uuid4(),
            records=(bar,),
            raw_payload_hash="abc",
            status=ProviderBatchStatus.SUCCEEDED,
        )
        assert len(batch.records) == 1
        assert batch.status is ProviderBatchStatus.SUCCEEDED

    def test_blank_raw_payload_hash_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ProviderBatch(
                attempt_id=uuid4(),
                records=(),
                raw_payload_hash="",
                status=ProviderBatchStatus.SUCCEEDED,
            )

    def test_failed_status_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="FAILED"):
            ProviderBatch(
                attempt_id=uuid4(),
                records=(),
                raw_payload_hash="abc",
                status=ProviderBatchStatus.FAILED,
            )

    def test_attempt_id_must_be_uuid(self) -> None:
        with pytest.raises(TypeError):
            ProviderBatch(
                attempt_id="not-a-uuid",  # type: ignore[arg-type]
                records=(),
                raw_payload_hash="abc",
                status=ProviderBatchStatus.SUCCEEDED,
            )

    def test_warnings_must_be_tuple(self) -> None:
        with pytest.raises(ValueError):
            ProviderBatch(
                attempt_id=uuid4(),
                records=(),
                raw_payload_hash="abc",
                status=ProviderBatchStatus.SUCCEEDED,
                warnings=["a warning"],  # type: ignore[arg-type]
            )


class TestPorts:
    """The Protocols must be runtime-checkable so adapters can be type-checked."""

    def test_etf_market_data_provider_protocol_is_satisfied_by_a_dummy(self) -> None:
        class _Dummy(EtfMarketDataProvider):
            @property
            def provider_key(self) -> str:
                return "fixture_dev"

            def fetch_instruments(
                self, as_of: date
            ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[Instrument] | None]:
                request_id = uuid4()
                attempt_id = uuid4()
                request = ProviderRequest(
                    provider_key=self.provider_key,
                    dataset_key="etf_instruments",
                    request_key=f"instruments-{as_of.isoformat()}",
                    created_at=datetime(as_of.year, as_of.month, as_of.day, 8, 0, tzinfo=timezone.utc),
                )
                attempt = ProviderAttempt(
                    request_id=request_id,
                    attempt_number=1,
                    status=ProviderAttemptStatus.SUCCEEDED,
                    started_at=datetime(as_of.year, as_of.month, as_of.day, 8, 0, tzinfo=timezone.utc),
                    finished_at=datetime(as_of.year, as_of.month, as_of.day, 8, 1, tzinfo=timezone.utc),
                    duration_ms=60_000,
                )
                batch = ProviderBatch(
                    attempt_id=attempt_id,
                    records=(),
                    raw_payload_hash="x",
                    status=ProviderBatchStatus.SUCCEEDED,
                )
                return request, attempt, batch

            def fetch_daily_bars(
                self,
                symbols: Sequence[str],
                start_date: date,
                end_date: date,
            ) -> tuple[ProviderRequest, ProviderAttempt, ProviderBatch[DailyBar] | None]:
                request_id = uuid4()
                attempt_id = uuid4()
                request = ProviderRequest(
                    provider_key=self.provider_key,
                    dataset_key="etf_daily_bars",
                    request_key=f"daily-bars-{start_date.isoformat()}-{end_date.isoformat()}",
                    created_at=datetime(start_date.year, start_date.month, start_date.day, 8, 0, tzinfo=timezone.utc),
                )
                attempt = ProviderAttempt(
                    request_id=request_id,
                    attempt_number=1,
                    status=ProviderAttemptStatus.SUCCEEDED,
                    started_at=datetime(start_date.year, start_date.month, start_date.day, 8, 0, tzinfo=timezone.utc),
                    finished_at=datetime(start_date.year, start_date.month, start_date.day, 8, 1, tzinfo=timezone.utc),
                    duration_ms=60_000,
                )
                batch = ProviderBatch(
                    attempt_id=attempt_id,
                    records=(),
                    raw_payload_hash="x",
                    status=ProviderBatchStatus.SUCCEEDED,
                )
                return request, attempt, batch

        dummy = _Dummy()
        assert isinstance(dummy, EtfMarketDataProvider)

    def test_instrument_provider_protocol_is_satisfied(self) -> None:
        class _Provider(InstrumentProvider):
            def list_instruments(self) -> Sequence[Instrument]:
                return [
                    Instrument("510300", "沪深300ETF", "SSE", InstrumentType.ETF),
                ]

        assert isinstance(_Provider(), InstrumentProvider)

    def test_legacy_and_canonical_instrument_provider_are_the_same_class(self) -> None:
        # ``invest_domain.ports.InstrumentProvider`` is a re-export of the
        # canonical ``invest_domain.market_data.ports.InstrumentProvider``;
        # they must be the same object so isinstance checks are stable.
        from invest_domain.ports import InstrumentProvider as LegacyProvider

        assert LegacyProvider is InstrumentProvider
