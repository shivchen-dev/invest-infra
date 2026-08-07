# Research lifecycle — PR-5.5 todo

- [x] Add failing migration/model contract tests
- [x] Implement ResearchRun/ResearchResult migration and row models
- [x] Add failing repository/UoW behavior tests
- [x] Implement repositories, codecs, CAS, identity lookup, and UoW ports
- [x] Update lifecycle implementation-plan status and PR sequence
- [x] Run focused and regression tests
- [x] Run Ruff, architecture checks, and `git diff --check`
- [x] ARC independent full-diff review

## Test evidence (PR-5.5)

- `tests/test_migration_chain.py`: 11 passed.
- Storage mocks under `tests/storage/` (mock tests, integration excluded): 205 passed.
- Focused PostgreSQL integration (`tests/storage/integration/test_research_run_result_repositories.py`): 9 passed.
- Full pipeline suite: 1461 passed.

Lifecycle completion is not claimed by this slice; the JiuwenSwarm Adapter (PR-6) and the read-only Research API (PR-7) remain pending.
