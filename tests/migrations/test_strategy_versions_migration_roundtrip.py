"""Real PostgreSQL round trip for StrategyVersion migration 0023."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "apps" / "migrations"
IMAGE = os.environ.get("TESTCONTAINERS_POSTGRES_IMAGE", "postgres:16-alpine")
TARGET = "20260826_0023"
DOWN = "20260826_0022"


def _docker_available() -> bool:
    if os.environ.get("INVEST_SKIP_DOCKER_TESTS") == "1":
        return False
    try:
        with DockerContainer("alpine:3.19"):
            return True
    except Exception:  # pragma: no cover - environment probe
        return False


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker is unavailable for Testcontainers PostgreSQL")
    container = PostgresContainer(
        IMAGE,
        username="invest",
        password="invest_dev_password",
        dbname="invest",
        driver="psycopg",
    )
    container.start()
    try:
        yield container.get_connection_url(driver="psycopg")
    finally:
        container.stop()


def _alembic(revision: str, *, direction: str, database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        ["uv", "run", "--project", ".", "alembic", direction, revision],
        cwd=MIGRATIONS,
        env=env,
        check=True,
    )


def _assert_upgrade_contract(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    assert inspector.has_table("strategy_versions", schema="analytics")
    assert {column["name"] for column in inspector.get_columns(
        "strategy_versions", schema="analytics"
    )} == {
        "strategy_id",
        "strategy_key",
        "version",
        "artifact_ref",
        "artifact_hash",
        "source_hashes",
        "decision_ref",
        "decision_hash",
        "decided_by_agent_id",
        "audit_id",
        "approved_at",
        "activated_at",
        "created_at",
    }
    assert {constraint["name"] for constraint in inspector.get_unique_constraints(
        "strategy_versions", schema="analytics"
    )} == {
        "uq_strategy_versions_strategy_key_version",
        "uq_strategy_versions_artifact_hash",
        "uq_strategy_versions_decision_hash",
    }
    indexes = {
        index["name"]: index
        for index in inspector.get_indexes("strategy_versions", schema="analytics")
    }
    assert "ix_strategy_versions_audit_id" in indexes
    assert indexes["uq_strategy_versions_activated_strategy_key"]["unique"]
    with engine.connect() as connection:
        indexdef = connection.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname='analytics' AND tablename='strategy_versions' "
                "AND indexname='uq_strategy_versions_activated_strategy_key'"
            )
        ).scalar_one()
    assert "WHERE (activated_at IS NOT NULL)" in indexdef


def test_strategy_versions_migration_round_trip(database_url: str) -> None:
    engine = sa.create_engine(database_url)
    try:
        _alembic(DOWN, direction="upgrade", database_url=database_url)
        _alembic(TARGET, direction="upgrade", database_url=database_url)
        _assert_upgrade_contract(engine)

        _alembic(DOWN, direction="downgrade", database_url=database_url)
        assert not sa.inspect(engine).has_table(
            "strategy_versions", schema="analytics"
        )

        _alembic(TARGET, direction="upgrade", database_url=database_url)
        _assert_upgrade_contract(engine)
    finally:
        engine.dispose()
