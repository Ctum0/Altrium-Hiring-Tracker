# Feature Transition Tests

Playwright tests organized around **transitions between features**, not pages. Each spec file guards one edge of the product feature graph (`PRODUCT_FEATURE_GRAPH.md`).

## Running

```bash
# against the local dev server (default http://127.0.0.1:8100)
npx playwright test --config qa/playwright.config.js tests/feature-transitions

# different base URL
QA_BASE_URL=http://127.0.0.1:8000 npx playwright test --config qa/playwright.config.js tests/feature-transitions
```

## Prerequisites

1. App running locally (`.venv/bin/python manage.py runserver 127.0.0.1:8100 --noreload` or via compose).
2. Auth states generated: `.venv/bin/python qa/scripts/seed_auth_states.py` → `qa/storage-states/{hr,iv,mgmt}.json` (gitignored).
3. Test data: `seed_testdata` command provides jobs/candidates when a spec needs a populated board.

## Conventions

- File name: `<source>-to-<destination>.spec.ts` (edge name from the feature graph).
- Auth: `test.use({ storageState: 'qa/storage-states/hr.json' })` (or `iv` / `mgmt`).
- Assert the complete transition: arrival, state handoff (created object's identity visible in destination), feedback, and the next logical action — not just the final UI state.
- Deterministic and isolated; workers run sequentially; namespace created data; clean up when feasible.
- Selectors: `data-testid` first, accessible role/name second. No positional or text-only brittle selectors.
- Only create specs for real application workflows — derive the edge list from `PRODUCT_FEATURE_GRAPH.md`, not from imagination.

## Current specs

None yet — the first audit cycle's confirmed gaps feed the first specs (see `regression-builder` skill).
