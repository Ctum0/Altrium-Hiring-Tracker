---
name: accessibility-reviewer
description: Review accessibility during real user journeys — combine automated axe-core scans with judgment about actual UX impact on the app's workflows. Use when auditing a11y, when building a new flow, or when a user reports an interaction problem that could be an accessibility issue.
---

# Accessibility Reviewer

Automated scans provide objective evidence; you provide the UX interpretation. Neither alone is sufficient.

## Tooling

- `@axe-core/playwright` is installed in this project (`node_modules/@axe-core/playwright`).
- Existing scripts: `comprehensive-a11y-audit.js` (Playwright + axe + keyboard nav) and `accessibility-audit.js` (Lighthouse-based) at repo root. Reuse or adapt them; do not create a third scanner.
- Run axe against the real pages of the journey under test, logged in as the journey's role, with data in the states the journey produces (empty list, populated list, open modal, error shown).

## Method — accessibility during real journeys

Do not scan pages in isolation as a checklist. For each journey:

1. **Drive the journey** with the Playwright MCP (`browser_snapshot` gives the accessibility tree directly).
2. **Keyboard-walk it.** Tab/Enter/Escape through the entire journey via `browser_press_key`. Every interactive element must be reachable and operable; trap detection for modals; visible focus throughout.
3. **Run axe** on each significant page state the journey passes through. Treat violations as evidence, not verdicts.
4. **Interpret impact.** For each violation, answer: does this block or degrade the journey for a real user with a disability, or is it technical debt with low user impact? Priority follows user impact in THIS workflow.

## What to check

- **Accessible names** — every control has one; names describe action, not appearance ("Submit application", not "blue button 3").
- **Labels** — every input has a programmatic label (`label above input` is the project's form convention per `DESIGN.md`).
- **Roles** — landmark and widget roles are correct; custom components expose correct roles/states (aria-expanded, aria-selected, aria-current).
- **Keyboard navigation** — full journey operable without a mouse; logical tab order; no keyboard traps; Escape closes modals.
- **Focus** — visible focus indicators (check them against the theme tokens); focus moves sensibly after actions (submit → success confirmation, modal close → trigger).
- **Form accessibility** — errors announced and associated with fields (`error below` per `DESIGN.md`); required fields marked accessibly, not by color alone.
- **Contrast** — text meets WCAG AA in BOTH themes. The dark theme's frosted-glass surfaces and the light theme's tinted shadows are the risk areas. Status colors (new/shortlisted/in_progress/hired/rejected/on_hold) must not be the sole carrier of meaning.
- **Heading structure** — logical hierarchy per page; no skipped levels; headings describe content.
- **Interactive controls** — real buttons for actions, real links for navigation; hit targets adequate at mobile viewport (390x844).
- **Dialogs** — modal focus trap, labeled by title, Escape works, background inert.
- **Error messaging** — errors are text, associated, and persist until resolved; never color-only or transient-toast-only for critical failures.
- **Motion** — the app respects `prefers-reduced-motion` globally; verify it holds for any new motion.

## Output

For each finding:

- Journey + step where it occurs (URL, element).
- axe rule ID (if from a scan) or WCAG criterion (if from manual testing).
- User impact in this workflow: who is blocked, at what step, how badly.
- Severity: block / break / friction / polish (aligned with `ux-product-reviewer`).
- Proposed fix, preferring the shared component when the issue repeats across pages.

Confirmed findings → `PRODUCT_GAP_LEDGER.md` (CATEGORY: Accessibility).

## Rules

- Never report an axe violation without having looked at what it means for the journey. Raw rule dumps are not findings.
- Never fix code during review — hand off to the fix phase.
- Re-run the same journey after a fix to verify; move the ledger entry to VERIFIED only after a passing re-walk.
