---
name: product-continuity-auditor
description: Audit the application as a feature graph — find gaps BETWEEN features (transitions), not within isolated pages. Use when asked to audit product continuity, find feature gaps, check workflow coherence, or map how features hand off to each other. The EDGE (transition between features) is the primary unit of analysis.
---

# Product Continuity Auditor

You audit the application as a directed graph, not a set of pages.

- **NODE** = a feature (Dashboard, Jobs list, Create Job, Job Detail, Kanban Board, Candidate Detail, Feedback Form, Settings, Notifications…)
- **EDGE** = a transition from one feature to another, taken by a user pursuing a goal.

Pages are not features. A single page can contain several nodes; a single feature can span pages. The unit of analysis is the EDGE.

## Baseline product map

`PRODUCT_FEATURE_GRAPH.md` (repo root) holds the current feature graph with per-edge documentation. Read it first. If it is stale or incomplete, extend it during the audit — the map is a living artifact, not a one-off report.

If the map does not exist yet, bootstrap it by walking the app: start at login, enumerate reachable nodes for each role (HR, Interviewer, Management), and record every observed transition. Use the Playwright MCP (`browser_navigate` + `browser_snapshot`) against the local/staging environment — never against production.

## The 14-point edge evaluation

For every important edge, evaluate:

1. **Discoverability** — can the user find the way into the next feature from where they are?
2. **User intent** — does the transition match what the user is trying to accomplish at this moment?
3. **Context preservation** — is the current task, selection, filter, or object carried into the next feature?
4. **State handoff** — does the destination receive and display the state the source produced (object ID, name, status, query)?
5. **Data continuity** — is data entered or changed upstream reflected downstream without re-entry or loss?
6. **Navigation** — is the path direct, or does it require unrelated detours (up → over → down)?
7. **Feedback** — does the user see confirmation that the transition happened and succeeded?
8. **Error recovery** — when the transition fails, can the user recover without losing work?
9. **Next logical action** — after arriving, is the next step obvious and available?
10. **Exit path** — can the user leave the destination without dead-ending?
11. **UI consistency** — does the transition reuse the app's established patterns (buttons, cards, modals, empty states)?
12. **Terminology consistency** — are the same concepts named the same way on both ends of the edge?
13. **Efficiency** — is redundant input or navigation required?
14. **Dead-end risk** — can the user end up somewhere with no useful next action?

## Method

1. **Discover** — walk each role's reachable feature set (see `user-journey-discovery` skill for journey scaffolding).
2. **Enumerate edges** — list every transition a real user would take, per role. Include the unhappy edges: error → recovery, empty state → first action, deletion → where the user lands.
3. **Traverse** — drive each edge in a real browser with the Playwright MCP. Prefer accessibility snapshots (`browser_snapshot`) for semantic interaction; use screenshots only when visual positioning matters.
4. **Evaluate** — score each edge against the 14 points. Record evidence (snapshot, screenshot, network log) for every failure — never report an unverified gap.
5. **Classify** — for each failing edge, decide: UX gap, state-handoff bug, navigation gap, terminology drift, dead end, or working-as-designed.
6. **Record** — write confirmed gaps to `PRODUCT_GAP_LEDGER.md` using its template. Set STATUS: OPEN.
7. **Prioritize** — order by user-goal impact: broken workflow continuity > lost context > friction > cosmetic.

## Rules

- NEVER modify application source during an audit. Audit is read-only on code; the browser may create/mutate test data in the local/staging environment only.
- Do not flag a gap from memory or code reading alone — reproduce it in the browser or cite captured evidence.
- An edge that fails the 14-point check only on aesthetics is NOT a continuity gap; note it, don't ledger it.
- Report per-role: an edge that works for HR but dead-ends for Interviewer is a gap.
- Cite exact URLs, element names, and state values in findings. Vague findings are rejected findings.
