"""Fixtures for the M1 storage **integration** tests.

Lives in ``tests/storage/integration/`` so the autouse bootstrap and
per-test truncation only run for tests that actually need a database.
Mock-based unit tests in the parent ``tests/storage/`` directory never
see these fixtures and therefore keep running in environments without
Docker.

The PostgreSQL container, engine and session-factory fixtures are
inherited from the parent ``tests/storage/conftest.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from invest_storage.models import Base
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


@pytest.fixture(scope="session", autouse=True)
def _create_schemas_and_tables(engine: Engine) -> Iterator[None]:
    """Create ``core`` / ``raw`` / ``app`` schemas and ORM tables once.

    Autouse within this conftest only - mock tests in the parent
    directory never instantiate the ``engine`` fixture and therefore
    skip this step.
    """

    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _truncate_between_tests(engine: Engine) -> Iterator[None]:
    """Wipe every persisted table before each integration test runs.

    The ``db_session`` fixture only isolates operations that go through
    itself; tests that build a UnitOfWork against the bare
    ``session_factory_fixture`` commit at the SQL level. To guarantee
    a clean slate without forcing every test to thread savepoints
    through the UoW, we ``TRUNCATE`` every table between tests.
    """

    tables = [
        f'"{schema}"."{table.name}"'
        for schema in ("raw", "core", "app")
        for table in reversed(Base.metadata.sorted_tables)
        if table.schema == schema
    ]
    if tables:
        with engine.begin() as connection:
            connection.execute(
                text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
            )
    yield


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    """Yield a savepoint-isolated ``Session`` per test.

    The session participates in a single outer transaction owned by
    this fixture. The session's ``commit`` / ``rollback`` calls hit a
    savepoint inside the outer transaction, so test code can use the
    normal SQLAlchemy commit/rollback API without polluting the
    database. When the fixture tears down the outer transaction is
    rolled back, wiping every change the test made.
    """

    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", future=True
    )
    try:
        yield session
    finally:
        session.close()
        if outer_transaction.is_active:
            outer_transaction.rollback()
        connection.close()


@pytest.fixture()
def repository(db_session: Session):
    """Yield a fresh :class:`SqlAlchemyInstrumentRepository` per test."""

    from invest_storage import SqlAlchemyInstrumentRepository

    return SqlAlchemyInstrumentRepository(db_session)


@pytest.fixture()
def batch_repository(db_session: Session):
    """Yield a fresh :class:`SqlAlchemyProviderBatchRepository` per test."""

    from invest_storage import SqlAlchemyProviderBatchRepository

    return SqlAlchemyProviderBatchRepository(db_session)