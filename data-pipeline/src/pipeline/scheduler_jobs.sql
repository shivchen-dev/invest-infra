-- T-06: Scheduler jobs audit table (idempotent — safe to run multiple times)
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id              SERIAL PRIMARY KEY,
    job_name        VARCHAR(100) NOT NULL UNIQUE,       -- 1 row per pipeline function
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP WITH TIME ZONE,
    status          VARCHAR(20) NOT NULL DEFAULT 'running'
                    CHECK (status IN ('success', 'failed', 'running')),
    record          JSONB                               -- full pipeline result dict
);
