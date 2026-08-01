# Hook Guidelines

> How hooks are used in this project.

---

## Overview

<!--
Document your project's hook conventions here.

Questions to answer:
- What custom hooks do you have?
- How do you handle data fetching?
- What are the naming conventions?
- How do you share stateful logic?
-->

The project uses TanStack React Query for server state. Hooks should wrap a
query/mutation with a stable query key and return the library's loading,
error, and data state to the component.

---

## Custom Hook Patterns

<!-- How to create and structure custom hooks -->

Use `use*` names for custom hooks. Keep query keys deterministic and scoped by
resource plus request parameters; do not fetch in render bodies or effects when
React Query is the appropriate owner.

---

## Data Fetching

<!-- How data fetching is handled (React Query, SWR, etc.) -->

The API client in `apps/web/src/api.ts` is the boundary for HTTP requests.
Normalize transport failures there or in the query function, not in each view.

---

## Naming Conventions

<!-- Hook naming rules (use*, etc.) -->

Avoid hooks that silently retry forever, manufacture market data, or duplicate
the API client's URL and response mapping logic.

---

## Common Mistakes

<!-- Hook-related mistakes your team has made -->

(To be filled by the team)
