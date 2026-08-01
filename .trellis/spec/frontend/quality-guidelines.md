# Quality Guidelines

> Code quality standards for frontend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

The web quality gate is `pnpm typecheck`/`npm run typecheck` and
`npm run build` from `apps/web`. Keep the client independently buildable from
the Python apps.

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

Do not add a second API client, direct database access, unchecked `any`, or
investment logic that bypasses the backend contracts.

---

## Required Patterns

<!-- Patterns that must always be used -->

Keep API loading, error, empty, and partial-data states visible. Use focused
component tests when behavior becomes non-trivial; typecheck is mandatory for
every UI change.

---

## Testing Requirements

<!-- What level of testing is expected -->

Review API contract alignment, type safety, accessibility, responsive layout,
error states, and whether the change is isolated to the web app boundary.

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
