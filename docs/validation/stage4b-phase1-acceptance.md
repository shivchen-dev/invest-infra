# Stage 4B Phase 1 Acceptance

Date: 2026-08-10
Baseline: `1644e99` (`HEAD` and `origin/main` before this slice)

## Scope

This acceptance covers Checkpoint C's seeded traceability slice only:

`ResearchCase → MarketObservationSnapshot → ResearchEvidenceBundle → ResearchRun → ResearchResult`

The test reuses the existing PostgreSQL Testcontainers fixture, seeded
`ResearchCase`/`EvidencePack` fixtures, SQLAlchemy repositories, and the
deterministic `FakeResearchRunner`. It does not cover UI, Breadth, Style,
Theme, Rotation, or an external/production research runner.

## Runtime evidence

The focused integration test completed against a real PostgreSQL container:

```text
PYTHONPATH=apps/pipeline/src:packages/domain/src:packages/storage/src:tests \
  python3 -m pytest tests/storage/integration/test_research_run_result_repositories.py -q
10 passed in 11.49s
```

The new test,
`test_seeded_case_observation_bundle_run_result_traceability`, asserted at
runtime that:

- the seeded case transitions `DRAFT → READY → RUNNING → COMPLETED`;
- the deterministic market-temperature builder creates and persists the
  observation snapshot;
- the bundle persists the evidence-pack hash and market-observation snapshot
  reference (snapshot ID and content hash);
- the run persists as `SUCCEEDED` with the case, evidence pack, and bundle IDs;
- the fake runner result round-trips with the same run, evidence pack, bundle,
  and valid evidence IDs.

The test asserts the generated UUIDs and content hashes in the live database;
this report intentionally does not substitute hand-written IDs or hashes for
those runtime values.

## Supporting gates

All relevant focused gates completed successfully:

| Gate | Command result |
| --- | --- |
| Domain runner and bundle | 62 passed |
| Storage repository mocks | 61 passed |
| Pipeline orchestration | 14 passed |
| Migration-chain contract | 14 passed |
| Market Temperature API/OpenAPI tests (`apps/api/.venv`) | 4 passed, 1 existing deprecation warning |
| Ruff on changed integration test | passed |
| `git diff --check` | passed |

The system Python path alone does not contain FastAPI; the API test was run
with the repository's existing `apps/api/.venv` via `uv run`, so this is not
reported as an API acceptance blocker. PostgreSQL and the seeded fixtures were
available for the integration run. No production seed deployment or external
AI execution was claimed.
