# Bulletproofing Implementation Plan

State at planning time: 10 gaps VERIFIED, 1 OPEN (GAP-011). 15 Django regression
tests green, 424-app test suite green, 10 journey specs, feature graph verified
for the core edges. This plan closes everything remaining and hardens the
system so regressions cannot silently return.

Principles carried from the continuity system: fix shared implementations, test
transitions not pages, evidence before claims, one ledger entry per confirmed
gap, no fix without a guard.

---

## Phase 1 — Clear the ledger (GAP-011 + carried-over observations)

### 1.1 GAP-011: silent rejection-email batch on job close (P2, OPEN)

- **Files:** `jobs/views.py` (`JobCloseView.post`, lines ~124-158), `jobs/templates/jobs/job_detail.html` (toast is server-side message, no template change needed)
- **Change:** count `emailed` / `failed` in the existing loop; append to the success message: `"; N active candidate(s) were emailed rejection notices."` — plus a separate `messages.error` when `failed > 0` naming the count (never the addresses). Keep the loop synchronous (the code comment already flags the async swap point; do not change transport in this fix).
- **Guard:** new test in `tests/test_gap_regressions.py` — close a job with 2 active applicants (patched email backend), assert the toast contains "2 active candidate(s) were emailed rejection notices"; a second test with a forced send failure asserts the error message appears and closure still succeeds.
- **Verify:** live close of a disposable job; ledger → VERIFIED.

### 1.2 Carried-over observations (decide: fix or WONT-FIX with reason)

| Item | Decision | Rationale |
|---|---|---|
| Topbar search box empty after back (page filter keeps value) | **FIX (P3, small)** | One-line: re-populate topbar input from `?q=` when on the candidates list. `templates/base.html` + tiny inline script. Guard: transition test asserting back-preserves both boxes. |
| Kanban cards: no keyboard move alternative (a11y) | **FIX (P2)** | Cards are `tabindex=0` but inert. Add a keyboard path: Enter/Space on a focused card opens a small "Move to…" menu (reuse the same `pipeline:move` endpoint + board toast). Keyboard-only users currently cannot run the core pipeline. Guard: Playwright a11y-transition test (keyboard-only stage move). |
| Calendar entries not clickable | **FIX (P3, small)** | Wrap each `upcoming-card` in a link to the candidate detail (data already on `app`). Guard: template test asserting the link. |
| `badge-feedback` semantic overloading (6 meanings, 1 style) + "Feedback Pending" uses `badge-feedback` on detail rows but `badge-pending` on the feedback list | **FIX (P3)** | Introduce `badge-state` (neutral info) for counts, keep `badge-pending` for pending states; unify "Feedback Pending" to `badge-pending` in `_app_row.html`. Shared-first: single template touch + CSS. Guard: grep-style template test asserting consistent class per semantic. |

Order within Phase 1: 1.1 → keyboard move → badge unification → topbar search → calendar links. Each lands with its guard test before the next starts.

---

## Phase 2 — Close the discovery coverage gaps (edges never walked)

These are the surfaces no cycle has verified yet. Each gets a real-customer walk
+ evidence; confirmed findings become ledger entries before any fix.

### 2.1 Talent pool + retention chain (needs closed-job data)
- Seed a disposable closed job with rejected ≥80-score applicants (fixture command or test-data script — extend `seed_testdata`, do not touch real rows).
- Walk: closed job detail → talent-pool suggestions → "Add to this posting" → application created → where the user lands (expect: job detail with the new application visible).
- Walk: retention report → "View candidates →" per closed job → filtered list state handoff.
- Ledger any gap; update feature graph edges.

### 2.2 Availability → scheduling chain (interviewer self-service)
- Walk: interviewer with no windows → availability banner → set window → slot preview updates on HR side → interview scheduling (`interviewer-slots` HTMX) → double-book probe (the seed data has one) → what the interviewer sees on conflict.
- This chain gates the core interview loop; treat conflicts and ineligible picks as first-class transitions.

### 2.3 Notifications full lifecycle (mark-all-read, unread-only filter, popover polling)
- Walk: mark-all-read → badge clears → unread-only tab → stale badge after actions elsewhere.
- Cheap; fold into the same session as 2.2.

### 2.4 Score reset, CV overlay, rounds delete, job reopen (small affordances)
- Batch-walk these in one session; they share the confirm-modal pattern. Verify each: confirmation copy accuracy, post-action state, and next action.

### 2.5 Public apply E2E (submit with real file)
- The apply form was only inspected, never submitted. Submit a real PDF → thanks page → candidate appears in the job's pipeline with parsed fields. Verify the fallback-contact merge path (typed name fills only parse gaps).

---

## Phase 3 — Permanent test infrastructure (make it bulletproof)

### 3.1 Playwright transition specs (the empty directory becomes real)
Convert the proven Django regression tests + the highest-value transitions into
browser-level specs in `tests/feature-transitions/` (runner already configured
via `qa/playwright.config.js`):

| Spec | Guards | Source |
|---|---|---|
| `login-to-dashboard.spec.ts` | role redirects (HR/IV/MGMT), lockout message | journey: error-recovery |
| `dashboard-kpi-to-filtered-list.spec.ts` | GAP-004 KPI + deep links | Gap004 test |
| `job-detail-round-reorder.spec.ts` | GAP-001 | Gap001 test |
| `mgmt-read-only-candidate.spec.ts` | GAP-002 | Gap002 test |
| `upload-to-filtered-list.spec.ts` | GAP-006 + parse toast | live-verified flow |
| `stage-move-feedback-gate.spec.ts` | GAP-008 (sticky toast + revert) | live-verified flow |
| `assign-notification-clickthrough.spec.ts` | assignment lifecycle | cycle-2 walk |
| `needs-review-badge.spec.ts` | GAP-003 | Gap003 test |
| `close-job-email-feedback.spec.ts` | GAP-011 (after 1.1) | new |
| `keyboard-stage-move.spec.ts` | keyboard a11y fix (after 1.2) | new |

Auth via `qa/storage-states/*.json`; base URL from `QA_BASE_URL`; tests must
create their own disposable data (unique slugs) — no dependence on the dev DB's
existing rows. Deterministic, sequential (config already sets workers=1).

### 3.2 One-command entry points
- `qa/Makefile` (or npm scripts): `make qa-server` (start dev server), `make qa-states` (seed storage states), `make qa-test` (Django regression suite), `make qa-e2e` (Playwright specs), `make qa-all`.
- Purpose: any future agent (or you) runs one command and gets the full guard suite; no tribal knowledge.

### 3.3 CI wiring (the repo has none)
- Add `.github/workflows/qa.yml`: Python matrix (3.13) → ruff → Django test suite (sqlite) → Playwright specs against a seeded runserver (single job, chromium only — the config's expansion point stays).
- Secrets: none needed (sqlite, no AI key — AI-dependent paths already degrade gracefully; tests must not depend on Groq).
- Lighthouse CI (Part 24 of the original spec): add as a **separate optional workflow** triggered manually/on-demand first, thresholds set after one baseline run — not gating. Do not make it primary.

### 3.4 Flake-proofing rules for the specs
- No network/AI dependencies (patch at the view layer is impossible in browser tests — instead use jobs/candidates whose AI features are already populated, or accept the graceful-degradation path).
- Every spec seeds and cleans its own data via a tiny `qa/scripts/e2e_seed.py` (idempotent, unique slugs).
- One assertion theme per spec; failures name the broken transition.

---

## Phase 4 — Hardening sweeps (defense in depth)

### 4.1 UI consistency inventory completion
- Run the `ui-consistency-inventory` pass to fill the graph's UI-patterns section: occurrence counts for buttons/forms/modals/empty/loading/error states across all templates, with shared-implementation mapping.
- Output: pattern table in `PRODUCT_FEATURE_GRAPH.md`; any new inconsistencies → ledger.

### 4.2 Accessibility journey pass
- `accessibility-reviewer` over the 3 core journeys (HR pipeline move, IV feedback submit, public apply) with axe-core + keyboard walks; findings → ledger with journey context. The Kanban keyboard fix (1.2) removes the biggest known blocker; this pass hunts for the rest (focus management in modals, form error announcement, dark-theme contrast on frosted glass).

### 4.3 State-handoff matrix completion
- Run `state-handoff-tester` across every edge in the graph's HR chain; fill the `state passed` fields with observed values; catch the class of bugs cycle 1 found (context loss) systematically rather than by luck.

### 4.4 Session/credential hygiene
- The seed script's `--username` borrow mode is now used for exploration; document it in `qa/scripts/README` (or script docstring) so future agents don't regenerate over a working binding.
- Add a `.gitignore` canary: a CI step that fails if `qa/storage-states/*.json` is ever staged.

---

## Execution order & checkpoints

```
Phase 1 (ledger clear)          ← code changes, each with guard test
  1.1 GAP-011  → 1.2 keyboard → badges → topbar → calendar
Checkpoint: full Django suite + ruff + ledger all VERIFIED/closed

Phase 2 (discovery coverage)    ← read-only walks, ledger updates
  2.1 talent pool → 2.2 availability → 2.3 notifications → 2.4 affordances → 2.5 public apply
Checkpoint: feature graph has zero unverified core edges; new gaps ledgered

Phase 3 (test infrastructure)   ← specs + CI
  3.1 specs → 3.2 entry points → 3.3 CI → 3.4 flake rules
Checkpoint: `make qa-all` green locally; CI green on push

Phase 4 (hardening sweeps)      ← audits feeding the next ledger cycle
  4.1 inventory → 4.2 a11y → 4.3 handoff matrix → 4.4 hygiene
Checkpoint: next cycle's backlog exists in the ledger, system is self-sustaining
```

Estimated shape: Phase 1 is ~4 small code changes + tests; Phase 2 is 3-4
browser sessions; Phase 3 is the bulk of the durable value (10 specs + CI);
Phase 4 is audit passes whose findings seed the next FIX cycle.

## Definition of "bulletproof"

1. Every confirmed gap is VERIFIED or WONT-FIX with a written reason.
2. Every fix has a guard that fails on regression (Django-level and, for the
   core 10 transitions, browser-level).
3. `make qa-all` runs the whole guard suite in one command; CI runs it on every push.
4. The feature graph has no unverified core edges; every edge documents its state handoff.
5. New-session agents resume from the ledger + graph alone, no tribal knowledge.
