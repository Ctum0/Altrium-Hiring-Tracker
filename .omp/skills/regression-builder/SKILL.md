---
name: regression-builder
description: Convert confirmed bugs and product gaps into permanent Playwright regression tests that assert the complete affected transition, not just the final UI state. Use after a bug is fixed or a gap is closed, or when a critical workflow needs a permanent guard.
---

# Regression Builder

Every confirmed important bug or product gap becomes a permanent regression test. A fix without a regression test is an unverified fix.

## Where tests live

`tests/feature-transitions/` — organized around transitions, not pages:

```text
tests/feature-transitions/
  dashboard-to-projects.spec.ts
  create-project-to-detail.spec.ts
  ...
```

Name files `<source>-to-<destination>.spec.ts` matching the feature-graph edge. One spec file may hold several related tests for the same edge. Only create tests that correspond to real application workflows — derive the edge list from `PRODUCT_FEATURE_GRAPH.md`.

Runner: Playwright test runner, config at `qa/playwright.config.js` (`npx playwright test tests/feature-transitions` — config is picked up from `qa/` via `--config qa/playwright.config.js`). Auth via storage states from `qa/scripts/seed_auth_states.py` (`test.use({ storageState: 'qa/storage-states/hr.json' })`).

## Test the transition, not the endpoint

BAD:

```text
assert button exists
```

GOOD:

```text
Create Project
→ submit
→ verify success
→ verify Project Detail opens
→ verify correct project
→ verify expected next actions
```

Assert what a user observes at each step of the edge: arrival URL, state carried over (the created object's name/ID appears), feedback shown, and the next logical action being present and functional. The bug being guarded defines which steps matter — a state-handoff bug needs the handoff asserted; a dead-end bug needs the next action asserted.

## Priorities

- **P0** — a core workflow breaks or loses user work (creation flows, pipeline movement, feedback submission, role access). Must exist for every confirmed P0 bug.
- **P1** — a core workflow degrades (wrong state displayed, lost context, confusing recovery).
- **P2** — friction, consistency drift. Write only when cheap; do not accumulate tautological P2 tests.

## Test quality bar

- Assert observable behavior (URLs, visible text, element roles/states, data shown), never implementation details (source text, field copies, internal state).
- Deterministic and isolated: seed the data the test needs or use dedicated QA accounts; never depend on leftovers from a previous test. Workers run sequentially (`qa/playwright.config.js`) — tests may rely on order only when the transition itself is sequential by nature; prefer explicit setup.
- Full-suite-safe: tests must not corrupt data other tests need. Clean up created objects when feasible, or namespace them (unique slugs/timestamps).
- Use `data-testid` selectors when present, accessible roles/names otherwise; avoid brittle text-only or positional selectors.
- One behavior per test; a failing test names the broken behavior.

## Workflow

1. Confirm the bug is fixed (or reproduce it first to watch the test fail — a regression test that never failed is unproven).
2. Write the transition test per the bar above.
3. Run it: must pass on the fixed code. If you wrote it before the fix, run it against pre-fix code to confirm it fails.
4. Record the test path in the `PRODUCT_GAP_LEDGER.md` entry's REGRESSION TEST field.
5. Run the whole `tests/feature-transitions/` suite to check isolation.

## Rules

- NEVER write a test just so the change "has tests". If no plausible bug would fail the test, don't write it — use a throwaway script instead.
- NEVER pad: same-path parameter rows, bare not-throw, length-grew checks.
- Never assert the fix's implementation; assert what the user gets.
- If an existing test pins wording or incidental behavior rather than a contract, delete it rather than re-pinning it to new text.
