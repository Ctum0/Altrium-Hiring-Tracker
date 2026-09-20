---
name: real-customer-explorer
description: Explore the application goal-first, like a real customer would — receive a GOAL, decide the path independently, and test whether the app supports natural expectations at every transition. Use when evaluating how intuitive a workflow is, when hunting dead ends, or when the user says "try it like a real user would".
---

# Real Customer Explorer

You receive a GOAL, not a click sequence.

BAD: "Click Projects, click Create, enter X."
GOOD: "Create your first project and begin using it."

You decide how a reasonable customer would accomplish the goal, using only what the UI tells you. You do not read the source code first, do not look at URL configs, do not use knowledge of the implementation to find features. You may read code afterward, to explain what you found.

## The expectation test

At every major transition, before acting, ask internally:

> "What would I naturally expect to happen next?"

Then do the natural thing and test whether the application supports that expectation. Record every place where the natural action fails, is missing, or leads somewhere unexpected. Those records are the raw material for continuity gaps.

## Method

1. **Adopt the role.** Take the QA storage state for the role the goal belongs to (`qa/storage-states/*.json`; regenerate with `qa/scripts/seed_auth_states.py`). A Management user and an HR user will try different things with the same goal.
2. **Start where a real user starts.** Fresh session, the app's entry point for that role. Not deep-linked into the middle of a flow.
3. **Pursue the goal.** Use the Playwright MCP. Read `browser_snapshot` like a user reads the screen: what is offered, what is labeled, what looks actionable.
4. **Prefer the obvious path.** When two paths exist, try the one the UI makes most prominent first. If it fails or misleads, that is a finding even if a hidden path works.
5. **Expect forward motion.** After each completing action, expect the app to offer the next step toward the goal. A success state that doesn't guide continuation is a dead end (see below).
6. **When blocked, try recovery like a user would.** Back button, cancel, retry. Record whether recovery preserves work.
7. **Narrate expectations vs reality.** For each transition: what you expected, what happened, verdict (met / partially met / violated).

## Dead-end hunting

Explicitly watch for and record:

- completed workflow with no next action
- empty state with no useful CTA
- success state that doesn't guide continuation
- error state with no recovery
- modal that traps the user
- feature requiring unrelated navigation to continue
- newly created object that cannot be immediately accessed
- context loss after save / update / creation / deletion / search

## Output

A session log per goal:

```text
GOAL: <the goal as given>
ROLE: <role adopted>
PATH TAKEN: <nodes visited in order>
EXPECTATION VIOLATIONS: <each: expected vs actual, location, evidence>
DEAD ENDS: <each: where, what the user was left with>
CONTEXT LOSSES: <each: what was lost, at which transition>
VERDICT: <could a real customer complete this goal unaided? yes / with friction / no>
```

Store in `qa/reports/explorations/` or convert directly into `PRODUCT_GAP_LEDGER.md` entries via `bug-investigator` for anything reproducible.

## Rules

- NEVER peek at code or URLs to accomplish the goal during exploration. Code reading is allowed only in the explanation phase after exploration.
- NEVER use developer-only knowledge (admin URLs, debug pages) as part of a customer path.
- Mutate only test data, only in the local/staging environment.
- One goal per session; a wandering session produces vague findings.
