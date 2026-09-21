---
name: user-journey-discovery
description: Discover user goals and journeys in the application by walking it as real users do — generating journey specs (primary, secondary, onboarding, creation, editing, deletion, search, settings, error/recovery, role-specific). Use when mapping the product before auditing, when the feature graph needs journeys, or when onboarding a new agent to the product.
---

# User Journey Discovery

You discover what users are trying to DO, not what routes exist. A route list is not a journey map.

## Method

1. **Read the product intent first.** `PRODUCT.md` and `DESIGN.md` define the users and their jobs. Anchor every journey to a named user type and a real goal.
2. **Walk the app per role.** Using the Playwright MCP against the local/staging environment, log in as each role's QA account (storage states in `qa/storage-states/`, regenerate with `qa/scripts/seed_auth_states.py`) and enumerate what each role can reach. Note role-gated features — a journey exists only if its user type can actually traverse it.
3. **Derive goals from affordances + product docs.** Ask for each surface: what would a person in this role come here to accomplish? Cross-check against `PRODUCT.md` scope lists.
4. **Write journey specs** using the template below. Store them in `qa/journeys/<journey-id>.md` (gitignored) or inline in `PRODUCT_FEATURE_GRAPH.md` when the journey defines a core edge chain.
5. **Verify each journey end-to-end** by driving it in the browser. A journey that cannot be completed is itself a finding — record it in `PRODUCT_GAP_LEDGER.md` (CATEGORY: Workflow Gap).

## Journey taxonomy

Generate journeys across these categories, only where they exist in the app:

- **Primary journeys** — the core value loop (e.g. HR: post job → ingest CVs → score → assign → move pipeline → hire).
- **Secondary journeys** — supporting work (exporting reports, managing interviewers, onboarding users).
- **Onboarding journeys** — first login, first job, first candidate, first feedback; empty-state paths.
- **Creation journeys** — every "make a new X" flow, including the path INTO creation and the path OUT of it.
- **Editing journeys** — changing an existing object; what happens to downstream references when it changes.
- **Deletion journeys** — removal flows, confirmations, what the user sees afterward, orphan handling.
- **Search journeys** — finding an object via search/filter, and what state is preserved into the destination.
- **Settings journeys** — configuration and preference flows.
- **Error/recovery journeys** — validation failure, network failure, permission denial, and the way back.
- **Role-specific journeys** — per-role slices of the above (Interviewer sees only assigned candidates; Management is read-only; verify these constraints hold in the journeys, not just in code).

## Journey template

```text
JOURNEY ID: <kebab-case-id>
USER TYPE: <HR | Interviewer | Management | Public candidate | ...>
GOAL: <one sentence, user-verb phrasing>
START STATE: <where the user is and what they have, before starting>
EXPECTED END STATE: <observable outcome that means the goal is achieved>
FEATURES: <nodes touched, in order>
TRANSITIONS: <edges between them — these map 1:1 into the feature graph>
NOTES: <role gates, preconditions, data needed, deviations observed during the walk>
```

## Rules

- Every journey MUST be verified by traversal before being marked valid. Unverified journeys are marked DRAFT.
- Transitions discovered here feed `PRODUCT_FEATURE_GRAPH.md` edges and the `product-continuity-auditor` edge evaluations.
- Do not invent journeys for features that do not exist. Do not skip journeys for features that exist but are hard to reach — those are the most valuable ones.
- Keep journey IDs stable across runs; update, never renumber.
