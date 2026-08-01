# Directory Structure

> How backend code is organized in this project.

---

## Overview

<!--
Document your project's backend directory structure here.

Questions to answer:
- How are modules/packages organized?
- Where does business logic live?
- Where are API endpoints defined?
- How are utilities and helpers organized?
-->

The repository is a Python modular monolith split by deployable responsibility.
Keep domain code framework-free and keep provider-specific code in Pipeline.

---

## Directory Layout

```
apps/api/src/invest_api/                 FastAPI routes and schemas
apps/pipeline/src/invest_pipeline/       Dagster assets and adapters
apps/migrations/migrations/versions/     Alembic migrations
packages/domain/src/invest_domain/       pure models, ports, errors
packages/storage/src/invest_storage/     SQLAlchemy models, repositories, UoW
apps/web/src/                             React + TypeScript UI
```

---

## Module Organization

<!-- How should new features/modules be organized? -->

Feature-specific application orchestration belongs in its owning app. Domain
ports and models belong in `packages/domain`; SQLAlchemy stays in storage;
FastAPI must not import Pipeline adapters. Provider implementations belong in
`apps/pipeline/src/invest_pipeline/adapters/<provider_key>/`.

---

## Naming Conventions

<!-- File and folder naming rules -->

Use lowercase snake_case for Python modules and packages, PascalCase for
Python classes, and descriptive `test_*.py` names. Do not create a generic
plugin framework or a second `providers.py`/`providers/` namespace.

---

## Examples

<!-- Link to well-organized modules as examples -->

Examples: `packages/domain/src/invest_domain/market_data/ports.py`,
`packages/storage/src/invest_storage/repositories.py`,
`apps/pipeline/src/invest_pipeline/adapters/fixture_dev/adapter.py`, and
`apps/api/src/invest_api/routers/etf.py`.
