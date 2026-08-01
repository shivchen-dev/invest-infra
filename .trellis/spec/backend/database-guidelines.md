# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

<!--
Document your project's database conventions here.

Questions to answer:
- What ORM/query library do you use?
- How are migrations managed?
- What are the naming conventions for tables/columns?
- How do you handle transactions?
-->

PostgreSQL is the Phase 1 database. SQLAlchemy models and repositories live in
`packages/storage`; the domain package must not import SQLAlchemy. Migrations
are an independent application under `apps/migrations` and run with Alembic.

---

## Query Patterns

<!-- How should queries be written? Batch operations? -->

Use repository methods and `SqlAlchemyUnitOfWork`; do not issue SQL from API
routers, Dagster assets, domain models, or Provider adapters. Preserve the
three-layer evidence model: `raw.provider_requests`,
`raw.provider_attempts`, and `raw.provider_batches`.

---

## Migrations

<!-- How to create and run migrations -->

Add versioned migrations under `apps/migrations/migrations/versions/`. Keep one
Alembic head, use explicit upgrade/downgrade functions, and verify the chain
with the repository migration checks.

---

## Naming Conventions

<!-- Table names, column names, index names -->

Use plural snake_case table names and snake_case columns. Phase 1 schemas are
`raw`, `core`, `analytics`, and `ops`; new logic must not write the deprecated
`app` schema. Provider and source identifiers are stored as non-empty strings.

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

Do not add a migration merely to support a fixture or a research-only source.
Do not let adapters commit transactions or accept SQLAlchemy sessions.
