# State Management

> How state is managed in this project.

---

## Overview

<!--
Document your project's state management conventions here.

Questions to answer:
- What state management solution do you use?
- How is local vs global state decided?
- How do you handle server state?
- What are the patterns for derived state?
-->

Use local React state for transient UI state, URL state for shareable filters,
and TanStack React Query for server state. Do not introduce Redux or another
global store for the current application size.

---

## State Categories

<!-- Local state, global state, server state, URL state -->

Promote state only when multiple unrelated components truly share it. Derived
values should be calculated from the authoritative query/API data rather than
copied into another mutable store.

---

## When to Use Global State

<!-- Criteria for promoting state to global -->

Query cache behavior must respect the API's date and quality metadata. A stale
or partial response must not be presented as a fresh trading-date result.

---

## Server State

<!-- How server data is cached and synchronized -->

Do not duplicate server data in local state, store secrets in browser state, or
make a global store a substitute for a typed API contract.

---

## Common Mistakes

<!-- State management mistakes your team has made -->

(To be filled by the team)
