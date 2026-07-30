"""Shared fixtures for the M1 storage tests.

The Testcontainers PostgreSQL container and its derived fixtures
(``engine``, ``database_url``, ``db_session``, ``repository``,
``batch_repository``, ``session_factory_fixture``, ``uow_factory``) are
defined here. They are **not** autouse, so the mock-based unit tests
in this directory do not pull the Docker chain and remain runnable in
environments without Docker.

The schema/table bootstrap and the per-test truncation live in
``tests/storage/integration/conftest.py`` and are only resolved for
tests in the ``integration`` subdirectory. Mock tests never see them.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

import pytest
from invest_storage.database import session_factory
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

log = logging.getLogger(__name__)

POSTGRES_IMAGE = os.environ.get("TESTCONTAINERS_POSTGRES_IMAGE", "postgres:16-alpine")


def _docker_available() -> bool:
    """Probe whether the Docker daemon is reachable.

    The probe is cheap and leaves no side effects; a ``DockerContainer``
    context manager either succeeds (Docker is reachable) or raises
    (Docker is not running, the socket is missing, or the user is
    not in the ``docker`` group). The ``INVEST_SKIP_DOCKER_TESTS``
    escape hatch lets developers opt out explicitly.
    """

    if os.environ.get("INVEST_SKIP_DOCKER_TESTS") == "1":
        return False
    try:
        probe = DockerContainer("alpine:3.19")
        with probe:
            return True
    except Exception as exc:  # pragma: no cover - environment probe
        log.warning("Docker probe failed: %s", exc)
        return False


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    if not _docker_available():
        pytest.skip(
            "Docker is not available; Testcontainers-based PostgreSQL "
            "integration tests are skipped. Unset INVEST_SKIP_DOCKER_TESTS "
            "and ensure the Docker daemon is running to execute the tests."
        )

    container = PostgresContainer(
        POSTGRES_IMAGE,
        username="invest",
        password="invest_dev_password",
        dbname="invest",
        driver="psycopg",
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url(driver="psycopg")


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="session")
def session_factory_fixture(engine: Engine) -> sessionmaker[Session]:
    """Plain ``sessionmaker`` bound to the test engine.

    Used by ``uow_factory`` to build UnitOfWork instances without
    going through the savepoint-isolated ``db_session`` fixture.
    """

    return session_factory(engine)


@pytest.fixture(scope="session")
def uow_factory(session_factory_fixture: sessionmaker[Session]):
    """Return a callable that builds a fresh :class:`SqlAlchemyUnitOfWork`.

    Tests ask for a new UoW via ``uow_factory()`` so the session
    lifetime and transaction boundary are owned by the test, not the
    fixture.
    """

    from invest_storage import SqlAlchemyUnitOfWork

    def _build() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory_fixture)

    return _build