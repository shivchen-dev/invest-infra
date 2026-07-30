from __future__ import annotations

from collections.abc import Iterator

import dagster as dg
from sqlalchemy.orm import Session

from invest_pipeline.config import get_settings
from invest_pipeline.providers import MockInstrumentProvider
from invest_storage.database import build_engine, session_factory
from invest_storage.repositories import SqlAlchemyInstrumentRepository


@dg.asset(group_name="market_data", compute_kind="python")
def seed_instruments(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    provider = MockInstrumentProvider()
    instruments = provider.list_instruments()

    engine = build_engine(get_settings().database_url)
    factory = session_factory(engine)
    session: Session = factory()
    try:
        repository = SqlAlchemyInstrumentRepository(session)
        count = repository.upsert_many(instruments)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

    context.log.info("Upserted %s instruments", count)
    return dg.MaterializeResult(metadata={"row_count": count, "provider": "mock"})
