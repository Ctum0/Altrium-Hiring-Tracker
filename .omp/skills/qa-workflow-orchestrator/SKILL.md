---
name: qa-workflow-orchestrator
description: Orchestrate the full product-continuity workflow — DISCOVER, MAP, GENERATE JOURNEYS, EXPLORE, IDENTIFY TRANSITION GAPS, REPRODUCE, COLLECT EVIDENCE, ROOT CAUSE, PRIORITIZE, FIX, REGRESSION, VERIFY, UPDATE GAP LEDGER. Use when starting a continuity audit cycle, when the user asks to "run the QA workflow" or "audit the product", or when resuming an in-progress audit cycle.
---

# QA Workflow Orchestrator

Run the phases in order. Discovery before code. Evidence before claims. Fixes after prioritization.

```text
DISCOVER → MAP → GENERATE JOURNEYS → EXPLORE → IDENTIFY TRANSITION GAPS →
REPRODUCE → COLLECT EVIDENCE → ROOT CAUSE → PRIORITIZE → FIX → REGRESSION →
VERIFY → UPDATE GAP LEDGER
```

## Phase map

| Phase | What happens | Skill / artifact |
|---|---|---|
| DISCOVER | Walk the app per role; enumerate reachable features. | `user-journey-discovery` |
| MAP | Update the feature graph: nodes, edges, per-edge documentation. | `PRODUCT_FEATURE_GRAPH.md` |
| GENERATE JOURNEYS | Write/refresh journey specs per taxonomy. | `user-journey-discovery`, `qa/journeys/` |
| EXPLORE | Goal-driven exploration as a real customer; expectation test at each transition. | `real-customer-explorer` |
| IDENTIFY TRANSITION GAPS | Evaluate edges on the 14-point check; dead-end and state-handoff sweeps. | `product-continuity-auditor`, `state-handoff-tester` |
| REPRODUCE | Confirm each candidate gap reproduces. | `bug-investigator` |
| COLLECT EVIDENCE | Screenshot, console, network, trace → `qa/` tree. | `bug-investigator` |
| ROOT CAUSE | Source-level diagnosis; blast radius. | `bug-investigator` |
| PRIORITIZE | Order by user-goal impact: broken continuity > lost context > friction > cosmetic. | ledger P0/P1/P2 |
| FIX | Modify source — ONLY this phase touches code. Prefer shared-component fixes. | — |
| REGRESSION | Convert fixed gaps into transition tests. | `regression-builder`, `tests/feature-transitions/` |
| VERIFY | Re-drive the fixed transition; run the regression suite. | Playwright MCP + `qa/playwright.config.js` |
| UPDATE GAP LEDGER | Status transitions: OPEN → INVESTIGATING → FIXING → FIXED → VERIFIED (or WONT-FIX / DUPLICATE). | `PRODUCT_GAP_LEDGER.md` |

## Rules

- **Do not skip discovery.** Even when the user names a specific problem, discovery contextualizes it — unless the user explicitly scopes the run to a single known edge.
- **Do not immediately start modifying code.** FIX begins only after PRIORITIZE produces a prioritized list and the user (or an explicit standing instruction) has green-lit fixes.
- **Read-only discovery:** GitHub read-only, database read-only, no production mutation, staging/local environment only. Source modification happens only in FIX.
- **Least privilege throughout:** no production credentials, no secrets in logs/reports/screenshots/traces, storage states stay out of Git.
- Resume support: the ledger's STATUS field is the workflow's state. Start any session by reading `PRODUCT_GAP_LEDGER.md` and `PRODUCT_FEATURE_GRAPH.md`; continue from the first non-VERIFIED entry or the phase the user names.
- One cycle ends when every new ledger entry reaches VERIFIED or an explicit deferral (WONT-FIX with reason), and the feature graph reflects any new edges discovered.
- Batch independent exploration slices as parallel subagents when the run is large; keep interpretation, prioritization, and fixes in the main session.
