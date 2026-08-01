# Type Safety

> Type safety patterns in this project.

---

## Overview

<!--
Document your project's type safety conventions here.

Questions to answer:
- What type system do you use?
- How are types organized?
- What validation library do you use?
- How do you handle type inference?
-->

The web app uses TypeScript with strict compiler settings. API response types
are defined at the API boundary and components consume those types directly.

---

## Type Organization

<!-- Where types are defined, shared types vs local types -->

Keep transport types near `apps/web/src/api.ts`; keep component-only view types
near the component. Do not create a parallel domain model that diverges from
the FastAPI/OpenAPI contract.

---

## Validation

<!-- Runtime validation patterns (Zod, Yup, io-ts, etc.) -->

Validate and normalize untrusted API data at the boundary. Handle nullable
market fields explicitly; do not use non-null assertions to hide missing data.

---

## Common Patterns

<!-- Type utilities, generics, type guards -->

Prefer inferred types from typed helpers, discriminated unions for state, and
explicit return types for reusable hooks and API functions.

---

## Forbidden Patterns

<!-- any, type assertions, etc. -->

Avoid `any`, broad casts, and unchecked JSON access. Keep TypeScript's `tsc -b`
typecheck in the build path.
