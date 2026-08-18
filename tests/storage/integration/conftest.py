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
from uuid import UUID

import pytest
from invest_storage.models import Base
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

TEST_INPUT_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="session", autouse=True)
def _create_schemas_and_tables(engine: Engine) -> Iterator[None]:
    """Create ``raw`` / ``core`` / ``ops`` / ``app`` / ``analytics`` / ``integration`` schemas and ORM tables once.

    Autouse within this conftest only - mock tests in the parent
    directory never instantiate the ``engine`` fixture and therefore
    skip this step.
    """

    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS ops"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS analytics"))
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS integration"))
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
        for schema in ("raw", "core", "ops", "app", "analytics", "integration")
        for table in reversed(Base.metadata.sorted_tables)
        if table.schema == schema
    ]
    if tables:
        with engine.begin() as connection:
            connection.execute(
                text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
            )
            connection.execute(
                text(
                    "INSERT INTO analytics.input_snapshots "
                    "(id, snapshot_date, instrument_ids, content_hash, row_count) "
                    "VALUES (:id, '2026-07-31', '[]'::jsonb, :content_hash, 1)"
                ),
                {"id": TEST_INPUT_SNAPSHOT_ID, "content_hash": "a" * 64},
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


@pytest.fixture()
def request_repository(db_session: Session):
    """Yield a fresh :class:`SqlAlchemyProviderRequestRepository` per test."""

    from invest_storage import SqlAlchemyProviderRequestRepository

    return SqlAlchemyProviderRequestRepository(db_session)


@pytest.fixture()
def attempt_repository(db_session: Session):
    """Yield a fresh :class:`SqlAlchemyProviderAttemptRepository` per test."""

    from invest_storage import SqlAlchemyProviderAttemptRepository

    return SqlAlchemyProviderAttemptRepository(db_session)
