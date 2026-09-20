---
name: state-handoff-tester
description: Verify that state produced by feature A is correctly received and displayed by feature B across every important transition — object IDs, names, filters, selections, status, permissions. Use when a transition loses context, shows stale/wrong data, or when building transition tests that must assert the handoff explicitly.
---

# State Handoff Tester

For every important transition A → B, the state A produces is a contract that B must honor.

## Step 1 — Inventory the produced state

Before testing a transition, list what A produces that B should receive. Typical state:

- object ID and object name (created/edited/deleted object)
- current project / job / candidate context
- current organization scope
- filters and search query
- selected item(s)
- permissions granted or changed
- status / stage / state transitions
- uploaded data (files, parsed CVs)
- in-progress form content
- sort order, pagination position

## Step 2 — Verify the handoff

Drive the transition in the real app (Playwright MCP, local/staging, appropriate role's QA storage state) and verify for EACH piece of state:

1. **Received** — B has access to the state (URL param, session, query, context object).
2. **Displayed** — B shows the correct value, not a stale, default, or placeholder value.
3. **Correct object** — B is operating on the exact object A produced (the newly created one, not an older lookalike).
4. **Preserved through refresh** — the handoff survives a page reload where the user would expect it to (deep link, shareable state).
5. **Preserved through back** — returning A → B → A → B keeps the state consistent.

## The handoff matrix

Record per transition:

```text
TRANSITION: <A> → <B>
STATE PRODUCED BY A: <list>
RECEIVED: yes/no per item
DISPLAYED CORRECTLY: yes/no per item
CORRECT OBJECT: yes/no
SURVIVES REFRESH: yes/no/n-a
SURVIVES BACK: yes/no/n-a
GAPS: <what breaks, with evidence>
```

## Failure patterns to hunt

- B defaults to "first item in list" instead of the object A just created.
- Filter/query lost when navigating from results to detail and back.
- Selection cleared by an unrelated action in between.
- Status shown in B reflects pre-update values (stale cache, no re-fetch).
- After deletion, B still references the deleted object (dangling links, 404 mid-flow).
- After search → detail → back, the search results page reset instead of preserving the query.
- Context loss after save / update / creation / deletion / search — the user lands somewhere that no longer knows what they were working on.

## Integration

- Findings → `PRODUCT_GAP_LEDGER.md` (CATEGORY: State Handoff) with reproduction and evidence.
- Confirmed handoff contracts → regression tests via `regression-builder`; the test MUST assert the carried state (e.g. the created object's name appears in the destination), not merely that navigation happened.
- Edge entries in `PRODUCT_FEATURE_GRAPH.md` get a `state passed` field — keep it current with what the handoff matrix shows.

## Rules

- Never accept "the page loaded" as a successful handoff. The handoff is the data, not the navigation.
- Verify with two different objects when practical (first-in-list vs a middle item) to catch default-value masking.
- Evidence for every claimed gap: snapshot/screenshot plus the state values observed on both sides.
