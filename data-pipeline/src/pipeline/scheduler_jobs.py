"""T-06: Scheduler jobs audit table — track pipeline runs in PostgreSQL.

Each pipeline function gets exactly one row keyed by job_name.
Entry: INSERT ... ON CONFLICT DO UPDATE SET status='running'
Exit:  UPDATE SET finished_at, status, record WHERE job_name=?

No new dependencies — uses existing psycopg2 connection pool from pg_loader.
"""

import json
import logging
from typing import Any

from src.loader.pg import get_conn

logger = logging.getLogger(__name__)

_MIGRATION_SQL = """\
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id              SERIAL PRIMARY KEY,
    job_name        VARCHAR(100) NOT NULL UNIQUE,
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP WITH TIME ZONE,
    status          VARCHAR(20) NOT NULL DEFAULT 'running'
                    CHECK (status IN ('success', 'failed', 'running')),
    record          JSONB
);
"""


def initialize() -> None:
    """Create scheduler_jobs table if it doesn't exist. Safe to call repeatedly."""
    try:
        conn = get_conn().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(_MIGRATION_SQL)
            conn.commit()
            logger.info("scheduler_jobs table ready")
        except Exception as e:
            logger.warning("scheduler_jobs init failed (table may already exist): %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            get_conn().putconn(conn)
    except Exception as e:
        logger.warning("scheduler_jobs connection error: %s", e)


def track_job(func):
    """Decorator: record job start/end in scheduler_jobs table.

    Placement: below @safe_step so safe_step wraps entry, but _track_job's
    INSERT runs first (closer to function). The flow is:
        track_job entry → @safe_step try → func body → @safe_step catch →
        track_job exit (finally)

    Each pipeline function gets one row keyed by job_name.
    """
    name = func.__name__

    def wrapper(*args, **kwargs):
        status = "failed"
        record = None

        # Entry: upsert running row
        _ensure_entry(name)

        try:
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                record = result
            else:
                record = {"result": result}
            status = "success" if not record.get("error") else "failed"
        except Exception as exc:
            logger.error("[%s] %s crashed: %s", name, func.__name__, exc, exc_info=True)
            raise  # re-raise so @safe_step/caller sees the real error
        finally:
            _mark_finished(name, status, record)

        return result

    return wrapper


def _ensure_entry(job_name):
    """INSERT ... ON CONFLICT DO UPDATE SET status='running'."""
    try:
        conn = get_conn().getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """\
INSERT INTO scheduler_jobs (job_name, started_at, status)
VALUES (%s, NOW(), 'running')
ON CONFLICT (job_name) DO UPDATE SET
    started_at  = EXCLUDED.started_at,
    status      = EXCLUDED.status,
    finished_at = NULL,
    record      = NULL
""",
                    (job_name,),
                )
            conn.commit()
        except Exception as e:
            logger.error("[%s] INSERT failed: %s", job_name, e)
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            get_conn().putconn(conn)
    except Exception as e:
        logger.warning("[%s] DB connection failed on entry: %s", job_name, e)


def _mark_finished(job_name, status, record):
    """UPDATE scheduler_jobs with final status + result."""
    try:
        conn = get_conn().getconn()
        try:
            record_json = json.dumps(record, default=str, ensure_ascii=False) if record else None
            with conn.cursor() as cur:
                cur.execute(
                    """\
UPDATE scheduler_jobs
SET finished_at = NOW(), status = %s, record = %s::jsonb
WHERE job_name = %s AND status = 'running'
""",
                    (status, record_json, job_name),
                )
            conn.commit()
        except Exception as e:
            logger.error("[%s] UPDATE failed: %s", job_name, e)
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            get_conn().putconn(conn)
    except Exception as e:
        logger.warning("[%s] DB connection failed on exit: %s", job_name, e)
