"""Round-trip migration test for ``20260812_0018_stock_price_limits``.

Brings a transient Testcontainers PostgreSQL up, runs Alembic against it
via ``subprocess`` so the migration scripts execute exactly as they do
in production (no in-process ``MetaData.create_all`` shortcut), and
asserts the upgrade contract (table, columns, primary key, foreign
keys, unique constraint, check constraints, indexes) and the
downgrade contract (table and indexes dropped).

The local ``_docker_available()`` probe mirrors ``tests/storage/conftest.py``
so this test honours the same ``INVEST_SKIP_DOCKER_TESTS=1`` opt-out as
the rest of the storage test-suite.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_CWD = _REPO_ROOT / "apps" / "migrations"


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


POSTGRES_IMAGE = "postgres:16-alpine"
TARGET_REVISION = "20260812_0018"
DOWN_REVISION = "20260812_0017"

_TABLE = "core.stock_price_limits"

_EXPECTED_COLUMNS: dict[str, str] = {
    "id": "uuid",
    "instrument_id": "uuid",
    "trade_date": "date",
    "regime_id": "character varying",
    "limit_up_price": "numeric",
    "limit_down_price": "numeric",
    "status": "character varying",
    "reference_price": "numeric",
    "source_provider": "character varying",
    "source_batch_id": "uuid",
    "observed_at": "timestamp with time zone",
    "revision": "integer",
    "row_hash": "character varying",
    "created_at": "timestamp with time zone",
}

_EXPECTED_PRIMARY_KEY = "pk_stock_price_limits"

_EXPECTED_FOREIGN_KEYS: dict[str, tuple[str, str]] = {
    "fk_stock_price_limits_instrument_id_core_instruments": (
        "instrument_id",
        "core.instruments.id",
    ),
    "fk_stock_price_limits_source_batch_id_raw_provider_batches": (
        "source_batch_id",
        "raw.provider_batches.id",
    ),
}

_EXPECTED_UNIQUE_CONSTRAINTS: dict[str, set[str]] = {
    "uq_stock_price_limits_instrument_trade_date_revision_row_hash": {
        "instrument_id",
        "trade_date",
        "revision",
        "row_hash",
    },
}

_EXPECTED_CHECK_CONSTRAINTS: set[str] = {
    "ck_stock_price_limits_revision_positive",
    "ck_stock_price_limits_regime_id_nonempty",
    "ck_stock_price_limits_status_nonempty",
    "ck_stock_price_limits_source_provider_nonempty",
    "ck_stock_price_limits_row_hash_len64",
}

_EXPECTED_INDEXES: set[str] = {
    "ix_stock_price_limits_instrument_trade_date",
    "ix_stock_price_limits_trade_date",
}


def _run_alembic(*args: str, database_url: str) -> None:
    cmd = ["uv", "run", "--project", ".", "alembic", *args]
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(cmd, cwd=_MIGRATIONS_CWD, env=env, check=True)


def _column_types(conn: sa.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            """
        ),
        {"schema": table.split(".")[0], "table": table.split(".")[1]},
    ).all()
    return {row[0]: f"{row[1]}|nullable={row[2]}" for row in rows}


def _normalize_array(value: object) -> list[str]:
    """Normalize a PostgreSQL array value to ``list[str]``.

    ``psycopg`` may return ``array_agg(...)`` results either as a Python
    list (when its array adapter is active) or as a string literal such
    as ``"{id}"``. Accept either form and produce a list of strings so
    callers can compare results without knowing the driver specifics.
    """

    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}"):
            inner = value[1:-1]
            return [item for item in inner.split(",") if item]
        return [value]
    return [str(item) for item in value]


def _primary_key(conn: sa.Connection, table: str) -> tuple[str, list[str]]:
    schema, name = table.split(".")
    row = conn.execute(
        sa.text(
            """
            SELECT constraint_name, array_agg(column_name ORDER BY ordinal_position)
            FROM information_schema.key_column_usage
            WHERE table_schema = :schema
              AND table_name = :table
              AND constraint_name = :constraint_name
            GROUP BY constraint_name
            """
        ),
        {"schema": schema, "table": name, "constraint_name": _EXPECTED_PRIMARY_KEY},
    ).first()
    if row is None:
        return _EXPECTED_PRIMARY_KEY, []
    return row[0], _normalize_array(row[1])


def _foreign_keys(conn: sa.Connection, table: str) -> dict[str, tuple[str, str]]:
    schema, name = table.split(".")
    rows = conn.execute(
        sa.text(
            """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                (
                    SELECT string_agg(
                        tbl.table_schema || '.' || tbl.table_name || '.' || col.column_name,
                        ','
                    )
                    FROM information_schema.referential_constraints rc
                    JOIN information_schema.key_column_usage kcu2
                         ON kcu2.constraint_schema = rc.unique_constraint_schema
                        AND kcu2.constraint_name = rc.unique_constraint_name
                    JOIN information_schema.tables tbl
                         ON tbl.table_schema = kcu2.table_schema
                        AND tbl.table_name = kcu2.table_name
                    JOIN information_schema.columns col
                         ON col.table_schema = kcu2.table_schema
                        AND col.table_name = kcu2.table_name
                        AND col.ordinal_position = kcu2.ordinal_position
                    WHERE rc.constraint_schema = tc.constraint_schema
                      AND rc.constraint_name = tc.constraint_name
                ) AS referenced
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                 ON kcu.constraint_schema = tc.constraint_schema
                AND kcu.constraint_name = tc.constraint_name
            WHERE tc.table_schema = :schema
              AND tc.table_name = :table
              AND tc.constraint_type = 'FOREIGN KEY'
            """
        ),
        {"schema": schema, "table": name},
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def _unique_constraints(conn: sa.Connection, table: str) -> dict[str, list[str]]:
    schema, name = table.split(".")
    rows = conn.execute(
        sa.text(
            """
            SELECT constraint_name, array_agg(column_name ORDER BY ordinal_position)
            FROM information_schema.key_column_usage
            WHERE table_schema = :schema
              AND table_name = :table
              AND constraint_name LIKE 'uq_%'
            GROUP BY constraint_name
            """
        ),
        {"schema": schema, "table": name},
    ).all()
    return {row[0]: _normalize_array(row[1]) for row in rows}


def _check_constraints(conn: sa.Connection, table: str) -> set[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        sa.text(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_schema = :schema
              AND table_name = :table
              AND constraint_type = 'CHECK'
            """
        ),
        {"schema": schema, "table": name},
    ).all()
    return {row[0] for row in rows}


def _indexes(conn: sa.Connection, table: str) -> set[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        sa.text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = :schema AND tablename = :table
            """
        ),
        {"schema": schema, "table": name},
    ).all()
    return {row[0] for row in rows}


def _table_exists(conn: sa.Connection, table: str) -> bool:
    schema, name = table.split(".")
    row = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema AND table_name = :table
            """
        ),
        {"schema": schema, "table": name},
    ).first()
    return row is not None


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
    eng = sa.create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(scope="session")
def migrated_engine(engine: Engine, database_url: str) -> Iterator[Engine]:
    _run_alembic("upgrade", "head", database_url=database_url)
    yield engine
    _run_alembic("downgrade", "base", database_url=database_url)


def test_upgrade_creates_stock_price_limits_table(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        assert _table_exists(conn, _TABLE), f"{_TABLE} should exist after upgrade to head"

        columns = _column_types(conn, _TABLE)
        for column, expected in _EXPECTED_COLUMNS.items():
            assert column in columns, f"missing column {column!r} on {_TABLE}"
            assert columns[column].startswith(expected), (
                f"column {column!r} on {_TABLE} has type {columns[column]!r}, "
                f"expected to start with {expected!r}"
            )

        pk_name, pk_columns = _primary_key(conn, _TABLE)
        assert pk_name == _EXPECTED_PRIMARY_KEY, (
            f"primary key on {_TABLE} is named {pk_name!r}, expected {_EXPECTED_PRIMARY_KEY!r}"
        )
        assert pk_columns == ["id"], f"primary key on {_TABLE} is {pk_columns!r}, expected ['id']"

        foreign_keys = _foreign_keys(conn, _TABLE)
        for fk_name, (column, referenced) in _EXPECTED_FOREIGN_KEYS.items():
            assert fk_name in foreign_keys, (
                f"missing foreign key {fk_name!r} on {_TABLE}; present: {sorted(foreign_keys)}"
            )
            assert foreign_keys[fk_name] == (column, referenced), (
                f"foreign key {fk_name!r} on {_TABLE} maps "
                f"{foreign_keys[fk_name]!r}, expected ({column!r}, {referenced!r})"
            )

        unique_constraints = _unique_constraints(conn, _TABLE)
        for uq_name, expected_columns in _EXPECTED_UNIQUE_CONSTRAINTS.items():
            assert uq_name in unique_constraints, (
                f"missing unique constraint {uq_name!r} on {_TABLE}; "
                f"present: {sorted(unique_constraints)}"
            )
            assert set(unique_constraints[uq_name]) == expected_columns, (
                f"unique constraint {uq_name!r} on {_TABLE} covers "
                f"{unique_constraints[uq_name]!r}, expected {sorted(expected_columns)!r}"
            )

        check_constraints = _check_constraints(conn, _TABLE)
        missing_checks = _EXPECTED_CHECK_CONSTRAINTS - check_constraints
        assert not missing_checks, (
            f"missing CHECK constraints on {_TABLE}: {sorted(missing_checks)}; "
            f"present: {sorted(check_constraints)}"
        )

        indexes = _indexes(conn, _TABLE)
        missing_indexes = _EXPECTED_INDEXES - indexes
        assert not missing_indexes, (
            f"missing indexes on {_TABLE}: {sorted(missing_indexes)}; present: {sorted(indexes)}"
        )


def test_downgrade_drops_stock_price_limits_table(
    postgres_container: PostgresContainer, database_url: str
) -> None:
    _run_alembic("upgrade", "head", database_url=database_url)
    _run_alembic("downgrade", DOWN_REVISION, database_url=database_url)

    engine = sa.create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            assert not _table_exists(conn, _TABLE), (
                f"{_TABLE} should be dropped after downgrade to {DOWN_REVISION}"
            )
            assert not _indexes(conn, _TABLE), (
                f"indexes on {_TABLE} should be dropped after downgrade to {DOWN_REVISION}; "
                f"still present: {sorted(_indexes(conn, _TABLE))}"
            )
        _run_alembic("upgrade", TARGET_REVISION, database_url=database_url)
        with engine.begin() as conn:
            assert _table_exists(conn, _TABLE), (
                f"{_TABLE} should be restored after upgrade to {TARGET_REVISION}"
            )
    finally:
        _run_alembic("downgrade", "base", database_url=database_url)
        engine.dispose()
