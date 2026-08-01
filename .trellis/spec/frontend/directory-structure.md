# Directory Structure

> How frontend code is organized in this project.

---

## Overview

<!--
Document your project's frontend directory structure here.

Questions to answer:
- Where do components live?
- How are features/modules organized?
- Where are shared utilities?
- How are assets organized?
-->

The web app is a small React + TypeScript + Vite client. It consumes the API
through the typed helpers in `apps/web/src/api.ts` and does not contain a
second backend or database model.

---

## Directory Layout

```
apps/web/src/main.tsx       React bootstrap
apps/web/src/App.tsx        application composition and page state
apps/web/src/api.ts         API client and response types
apps/web/src/styles.css     global styles
```

---

## Module Organization

<!-- How should new features be organized? -->

Keep feature UI in `src/` until a real feature requires subdirectories. Shared
server access belongs in `api.ts`; do not call the database or Pipeline from
the browser.

---

## Naming Conventions

<!-- File and folder naming rules -->

Use PascalCase for React components, camelCase for functions/variables, and
`.tsx` for components. Keep API field names aligned with the FastAPI schema.

---

## Examples

<!-- Link to well-organized modules as examples -->

Current examples are `apps/web/src/App.tsx`, `apps/web/src/api.ts`, and
`apps/web/src/main.tsx`.
