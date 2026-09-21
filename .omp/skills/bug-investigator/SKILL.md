---
name: bug-investigator
description: Investigate and root-cause reported issues — reproduce, capture evidence (screenshot, console, network, trace), inspect source, determine root cause and blast radius. Use when a bug, gap, or anomaly needs confirmation and diagnosis before any fix. Produces evidence-backed bug reports, not speculation.
---

# Bug Investigator

Nothing is a bug until it reproduces. No root cause without evidence.

## Investigation protocol

1. **Reproduce.** Drive the reported scenario in the local/staging environment with the Playwright MCP. If the report came from a user journey, replay the exact journey up to the failure point. Record the exact steps.
2. **Confirm reproducibility.** Run it twice. Note whether it is deterministic, intermittent, or state-dependent. An intermittent reproduction must state the suspected trigger condition.
3. **Capture screenshot** of the failure state (`browser_take_screenshot`) → `qa/screenshots/`.
4. **Capture console** (`browser_console_messages`) — errors, warnings, failed promises.
5. **Inspect network** (`browser_network_requests`, then `browser_network_request` for the failing call) — status codes, payloads, redirects, latency. Failed requests and unexpected redirects are primary suspects in transition bugs.
6. **Capture trace when useful.** For intermittent or timing-sensitive failures: `browser_start_tracing` → reproduce → `browser_stop_tracing`; store in `qa/traces/`. For UX flows a video (`browser_start_video`) can be clearer.
7. **Inspect source code.** Map the observed behavior to the code path: view → template → URL → view logic → model. This is a Django app: check `*/views.py`, `*/urls.py`, `templates/`, and shared template includes.
8. **Determine root cause.** The root cause explains ALL observed symptoms, not just the first one. If your explanation requires ignoring a symptom, keep digging.
9. **Identify affected components/features.** Which nodes and edges of the feature graph does this touch? Shared components (`templates/includes/`, base template blocks, common form patterns) multiply blast radius.
10. **Determine whether other workflows are affected.** Search for sibling call sites and sibling flows that share the broken pattern. A bug in one transition often exists in its siblings.

## Report format

```text
BUG ID: BUG-<NNN>
TITLE: <one line, symptom-oriented>
CATEGORY: <State Handoff | Navigation | UX | Data | Accessibility | Visual Regression | Performance | Regression>
SOURCE FEATURE: <node the user came from>
DESTINATION FEATURE: <node where it failed>
USER GOAL: <what the user was trying to do>
EXPECTED: <observable correct behavior>
ACTUAL: <observable wrong behavior>
REPRODUCTION: <exact steps, environment, account role, data preconditions>
EVIDENCE: <paths to screenshot/console/network/trace artifacts under qa/>
ROOT CAUSE: <file:symbol-level explanation, or "under investigation">
AFFECTED AREAS: <other features/flows sharing the root cause>
PRIORITY: <P0 blocks a core workflow | P1 degrades a core workflow | P2 friction/polish>
PROPOSED FIX: <concrete change, file-level>
```

Write confirmed bugs to `PRODUCT_GAP_LEDGER.md` (STATUS: INVESTIGATING → FIXING as work proceeds).

## Rules

- Do not call something a bug without sufficient evidence. "Looks wrong to me" is a hypothesis; reproduce it or file it as a hypothesis explicitly.
- Do not fix during investigation unless the fix is trivially safe and the user asked for fix-and-investigate together. The FIX phase is separate.
- Never expose secrets in evidence: no passwords, tokens, session cookies, or private user data in screenshots, logs, or reports. Redact before storing.
- Test data mutations happen only against the local/staging environment.
- If the root cause is in a shared component, say so explicitly — the fix belongs there, not in the pages that expose it.
