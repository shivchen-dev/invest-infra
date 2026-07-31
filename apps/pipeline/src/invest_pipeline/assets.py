from __future__ import annotations

from datetime import date

import dagster as dg
from invest_storage.database import build_engine, session_factory
from invest_storage.repositories import (
    NewProviderAttempt,
    NewProviderBatch,
    NewProviderRequest,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderAttemptRepository,
    SqlAlchemyProviderBatchRepository,
    SqlAlchemyProviderRequestRepository,
)
from sqlalchemy.orm import Session

from invest_pipeline.adapters import FixtureDevInstrumentProvider
from invest_pipeline.config import get_settings


@dg.asset(group_name="market_data", compute_kind="python")
def seed_instruments(context) -> dg.MaterializeResult:
    """Seed the canonical ``core.instruments`` rows from the fixture_dev adapter.

    PR-02: the adapter returns the three-layer evidence bundle
    ``(ProviderRequest, ProviderAttempt, ProviderBatch)``. The asset
    persists each layer via its repository in order (request → attempt
    → batch), so the FK wiring on ``provider_attempts`` and
    ``provider_batches`` resolves against the storage-assigned UUIDs.
    The standardized records (``batch.records``) are then upserted into
    ``core.instruments`` via :class:`SqlAlchemyInstrumentRepository`.
    """

    provider = FixtureDevInstrumentProvider()
    request, attempt, batch = provider.fetch_instruments(date.today())

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    session: Session = factory()
    try:
        request_repo = SqlAlchemyProviderRequestRepository(session)
        attempt_repo = SqlAlchemyProviderAttemptRepository(session)
        batch_repo = SqlAlchemyProviderBatchRepository(session)
        instrument_repo = SqlAlchemyInstrumentRepository(session)

        stored_request = request_repo.add(
            NewProviderRequest(
                provider_key=request.provider_key,
                dataset_key=request.dataset_key,
                request_key=request.request_key,
                status="pending",
                request_params=dict(request.params),
            )
        )

        stored_attempt = attempt_repo.add(
            NewProviderAttempt(
                provider_request_id=stored_request.id,
                attempt_no=attempt.attempt_number,
                started_at=attempt.started_at,
                status="succeeded",
                finished_at=attempt.finished_at,
            )
        )

        if batch is not None:
            batch_repo.add(
                NewProviderBatch(
                    provider_request_id=stored_request.id,
                    provider_attempt_id=stored_attempt.id,
                    provider_key=request.provider_key,
                    dataset_key=request.dataset_key,
                    record_count=len(batch.records),
                    payload_sha256=batch.raw_payload_hash,
                    status=batch.status.value,
                    warnings=list(batch.warnings),
                )
            )

        count = instrument_repo.upsert_many(batch.records if batch else ())
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

    context.log.info(
        "Upserted %s instruments via provider=%s request=%s attempt=%s",
        count,
        request.provider_key,
        stored_request.id,
        stored_attempt.id,
    )
    return dg.MaterializeResult(
        metadata={
            "row_count": count,
            "provider": request.provider_key,
            "request_id": str(stored_request.id),
            "attempt_id": str(stored_attempt.id),
        }
    )