from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from invest_storage.database import build_engine, session_factory
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from invest_api.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return session_factory(get_engine())


def get_db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
