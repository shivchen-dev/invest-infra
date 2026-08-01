# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

Components are functional React components. `App.tsx` owns page composition
and uses explicit loading/error/empty states for API-backed views.

---

## Component Structure

<!-- Standard structure of a component file -->

Keep component props small and explicitly typed. Prefer composition and plain
props over a global component registry or implicit context.

---

## Props Conventions

<!-- How props should be defined and typed -->

Use the existing stylesheet approach in `apps/web/src/styles.css`; do not add
a styling framework or component library without a separate decision.

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

Interactive elements must remain keyboard reachable, have readable labels, and
retain visible loading/error states. Do not hide API failures behind empty UI.

---

## Accessibility

<!-- A11y requirements and patterns -->

Do not put fetch calls, database assumptions, or investment decisions inside
presentational components. Keep server data handling in the API/query layer.

Example component shape:

```tsx
export function App(): JSX.Element {
  return <main aria-label="Investment dashboard">...</main>;
}
```

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)
