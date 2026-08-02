"""PostgreSQL-backed end-to-end test for the personal daily pipeline.

This test exercises the *real* CLI and API processes against a real Postgres
instance, but it intentionally avoids importing any application package into
the test process. The only Python dependencies needed are :mod:`pytest` and a
DB driver (SQLAlchemy + psycopg).

The test is skipped automatically when ``DATABASE_URL`` is not provided.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

TRADE_DATE = "2026-07-30"
PROVIDER_KEY = "fixture_dev"

API_HEALTH_TIMEOUT_S = 60.0
API_POLL_INTERVAL_S = 0.5

RAW_TABLES = (
    "raw.provider_requests",
    "raw.provider_attempts",
    "raw.provider_batches",
)
CORE_TABLES = ("core.instruments", "core.daily_bars")
PUBLISHED_RUNS_TABLE = "analytics.candidate_pool_runs"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not provided; skipping Postgres E2E test.")
    return url


def _make_engine(database_url: str) -> Engine:
    return sa.create_engine(database_url, future=True)


def _run_uv(project: str, *args: str, database_url: str) -> None:
    cmd = [
        "uv",
        "run",
        "--project",
        project,
        *args,
    ]
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["INVEST_PIPELINE_PROVIDER_KEY"] = PROVIDER_KEY
    subprocess.run(cmd, cwd=_repo_root(), env=env, check=True)


def _count_successful_raw_rows(conn: sa.Connection) -> dict[str, int]:
    return {
        table: int(
            conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE status = :status"),
                {"status": "succeeded"},
            ).scalar_one()
        )
        for table in RAW_TABLES
    }


def _table_count(conn: sa.Connection, table: str) -> int:
    return int(conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())


def _max_revision(conn: sa.Connection, table: str) -> int | None:
    row = conn.execute(sa.text(f"SELECT MAX(revision) FROM {table}")).first()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _fetch_snapshot(
    conn: sa.Connection, trade_date: str
) -> tuple[str, int]:
    row = conn.execute(
        sa.text(
            "SELECT id, row_count FROM analytics.input_snapshots "
            "WHERE snapshot_date = :trade_date ORDER BY id DESC LIMIT 1"
        ),
        {"trade_date": trade_date},
    ).first()
    if row is None:
        pytest.fail(
            f"No analytics.input_snapshots row found for trade_date={trade_date}."
        )
    return str(row[0]), int(row[1])


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_api(port: int) -> None:
    url = f"http://127.0.0.1:{port}/api/v1/candidate-pool/latest"
    deadline = time.monotonic() + API_HEALTH_TIMEOUT_S
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError) as exc:
            last_err = exc
        time.sleep(API_POLL_INTERVAL_S)
    raise AssertionError(f"API did not become healthy on port {port}: {last_err}")


def _get_latest_candidate_pool(port: int) -> dict:
    url = f"http://127.0.0.1:{port}/api/v1/candidate-pool/latest"
    with urllib.request.urlopen(url, timeout=5.0) as resp:
        assert resp.status == 200, f"unexpected status {resp.status}"
        payload = resp.read().decode("utf-8")
    return json.loads(payload)


def test_personal_daily_pipeline_postgres() -> None:
    database_url = _require_database_url()
    repo_root = _repo_root()

    # 1) Bring schema up to head.
    subprocess.run(
        ["uv", "run", "--project", ".", "alembic", "upgrade", "head"],
        cwd=repo_root / "apps" / "migrations",
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )

    engine = _make_engine(database_url)

    # 2) First run of the personal daily CLI.
    _run_uv(
        "apps/pipeline",
        "python",
        "-m",
        "invest_pipeline.personal_daily_cli",
        "--trade-date",
        TRADE_DATE,
        database_url=database_url,
    )

    with engine.begin() as conn:
        # raw.* successful rows (counted defensively across common status names).
        raw_counts = _count_successful_raw_rows(conn)
        for table, count in raw_counts.items():
            assert count > 0, f"Expected successful rows in {table}, found {count}."

        # core tables populated.
        for table in CORE_TABLES:
            assert _table_count(conn, table) > 0, f"{table} is empty."

        # analytics input snapshot + published pool / items alignment.
        snapshot_id, snapshot_row_count = _fetch_snapshot(conn, TRADE_DATE)
        assert snapshot_row_count > 0, "Snapshot row_count must be positive."

        pool_count = int(
            conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM analytics.candidate_pool_runs "
                    "WHERE input_snapshot_id = :snapshot_id AND status = 'published'"
                ),
                {"snapshot_id": snapshot_id},
            ).scalar_one()
        )
        assert pool_count == 1, (
            f"Expected exactly 1 candidate pool for snapshot {snapshot_id}, "
            f"found {pool_count}."
        )

        items_count = int(
            conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM analytics.candidate_pool_items "
                    "WHERE run_id IN ("
                    " SELECT id FROM analytics.candidate_pool_runs "
                    " WHERE input_snapshot_id = :snapshot_id"
                    ")"
                ),
                {"snapshot_id": snapshot_id},
            ).scalar_one()
        )
        assert items_count == snapshot_row_count, (
            f"candidate_pool_items ({items_count}) must equal "
            f"snapshot row_count ({snapshot_row_count})."
        )

        # 3) Idempotence: re-run CLI and assert daily_bars / runs unchanged.
        daily_bars_max_rev_before = _max_revision(conn, "core.daily_bars")
        daily_bars_count_before = _table_count(conn, "core.daily_bars")
        runs_nk_count_before = int(
            conn.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {PUBLISHED_RUNS_TABLE} "
                    "WHERE trade_date = :trade_date"
                ),
                {"trade_date": TRADE_DATE},
            ).scalar_one()
        )

    _run_uv(
        "apps/pipeline",
        "python",
        "-m",
        "invest_pipeline.personal_daily_cli",
        "--trade-date",
        TRADE_DATE,
        database_url=database_url,
    )

    with engine.begin() as conn:
        daily_bars_max_rev_after = _max_revision(conn, "core.daily_bars")
        daily_bars_count_after = _table_count(conn, "core.daily_bars")
        runs_nk_count_after = int(
            conn.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM {PUBLISHED_RUNS_TABLE} "
                    "WHERE trade_date = :trade_date"
                ),
                {"trade_date": TRADE_DATE},
            ).scalar_one()
        )

    assert daily_bars_count_after == daily_bars_count_before, (
        f"daily_bars count changed on rerun: "
        f"{daily_bars_count_before} -> {daily_bars_count_after}"
    )
    assert daily_bars_max_rev_after == daily_bars_max_rev_before, (
        f"daily_bars max(revision) changed on rerun: "
        f"{daily_bars_max_rev_before} -> {daily_bars_max_rev_after}"
    )
    assert runs_nk_count_after == runs_nk_count_before, (
        f"candidate_pool_runs natural-key count changed on rerun: "
        f"{runs_nk_count_before} -> {runs_nk_count_after}"
    )

    # 4) Start the API and verify the published pool is served.
    port = _find_free_port()
    api_cmd = [
        "uv",
        "run",
        "--project",
        "apps/api",
        "uvicorn",
        "invest_api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    api_env = {**os.environ, "DATABASE_URL": database_url}
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(api_cmd, cwd=repo_root, env=api_env)
        _wait_for_api(port)
        payload = _get_latest_candidate_pool(port)
        assert payload.get("snapshot_date") == TRADE_DATE, (
            f"API latest snapshot_date {payload.get('snapshot_date')} != {TRADE_DATE}"
        )
        items = payload.get("items") or []
        assert len(items) == snapshot_row_count, (
            f"API items ({len(items)}) must equal snapshot row_count "
            f"({snapshot_row_count})."
        )
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
