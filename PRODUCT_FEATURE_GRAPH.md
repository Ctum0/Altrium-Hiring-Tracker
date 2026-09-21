# Product Feature Graph

The application as a feature graph. NODE = feature, EDGE = transition between features. This is the persistent mental model for every future agent working on continuity — keep it current.

Status: **VERIFIED (first pass)** — nodes and core edges walked live in a real browser on 2026-09-21 against the local dev server (port 8100), all three roles. Per-edge documentation filled for the edges traversed; edges not yet walked are marked `unverified`.

## Conventions

Per-edge documentation fields: *user goal · expected next action · actual next action · state passed · context preserved · navigation · feedback · known gaps*.

Edge entry format:

```text
### <SOURCE> → <DESTINATION>
- user goal:
- expected next action:
- actual next action:
- state passed:
- context preserved:
- navigation:
- feedback:
- known gaps:
```

## Nodes (by Django app) — all verified reachable

### Auth / entry (accounts)
- Login (`/login/`) — POST-only logout; axes lockout after 5 failures (1h cooloff)
- Home router (`/`) — HR/Management → HR dashboard; Interviewer → interviewer dashboard
- HR Dashboard (`/hr-dashboard/`) — KPIs, stage chart, AI insights, escalations, top positions, stage performance
- Interviewer Dashboard (`/interviewer-dashboard/`) — assigned candidates table, pending feedback KPI, availability banner
- Reports export (`/reports/export/`, CSV) · Retention report (`/reports/retention/`)
- Interviewer Roster (`/interviewer-roster/`) · Interviewer Profile (`/interviewer/<pk>/`, HR can edit matching fields)
- Onboard account (`/onboard/`, HR-only)
- My Availability (`/my-availability/`) · My Calendar (`/my-calendar/`)

### Jobs
- Jobs list (`/jobs/`) · Create job (`/jobs/create/`)
- Job detail (`/jobs/<pk>/`) · Kanban board (`/jobs/<pk>/board/`)
- Rounds setup (`/jobs/<pk>/rounds-setup/`, creation-time only) · round create/delete/reorder
- Job edit / close (reason required) / reopen
- Talent pool add (`/jobs/<pk>/talent-pool-add/<application_pk>/`)

### Candidates
- CV upload (`/candidates/upload/`, `?job=` preselect) · Import (`/candidates/import/`, paste-profile)
- Candidates list (`/candidates/`, filters: q/job/stage/min_score/needs_review/all; tabs preserve filters)
- Candidate detail (`/candidates/<pk>/`) · Review (`/candidates/<pk>/review/`) · bulk review (`/candidates/review-all/`, HR-only)
- Score (`/candidates/<pk>/score/`) · Delete
- Application actions: AI fit (403 for management), assign (+HTMX slot preview), interview details/slots
- Public apply (`/candidates/apply/<job_pk>/` → thanks) · Careers (`/careers/`)
- Offboarding (`/candidates/offboarding/`)

### Pipeline
- Stage move (`/pipeline/move/<pk>/`) — feedback gate (409), unrouted support, audit trail, milestone emails

### Feedback
- Feedback list (`/feedback/`, pending tab scoped to the viewer's actionable rows)
- Feedback form (`/feedback/<app_pk>/<round_pk>/`, ?next= context return; AI suggest/polish)
- Feedback detail + history

### Notifications
- Notification list (`/notifications/`) · popover (topbar, 30s unread poll) · mark read/all-read

## Roles (verified)

- **HR** — full workflow; sidebar: Dashboard, Jobs, Interviewers, Candidates, Feedback, Notifications
- **Interviewer (IV)** — sidebar: Dashboard, Candidates, Feedback, Notifications, My Availability, My Calendar. Candidates list scoped to assigned/panel. Jobs & Roster hidden from nav; `/jobs/` direct URL renders the list read-only (no New job, no edit links) — reachable but unlinked, by design per JobBoardView docs.
- **Management (MGMT)** — sidebar: Dashboard, Jobs, Interviewers, Candidates, Feedback, Notifications. All write controls hidden (no New job/Edit/Close/Deactivate/Onboard/Mark-reviewed); server enforces 403s. One UI leak: "Generate AI assessment" button renders (GAP-002).

## Core edges — verified with per-edge documentation

### HR chain

#### Login → HR Dashboard
- user goal: start the working day
- expected next action: land on a dashboard showing pipeline state
- actual next action: same ✓ (302 → /hr-dashboard/)
- state passed: session; role determines destination
- context preserved: ?next honored on login redirects
- navigation: direct
- feedback: —
- known gaps: lockout message lacks duration (GAP-007)

#### HR Dashboard → Create Job
- user goal: post a new role
- expected next action: prominent "Create job" CTA
- actual next action: same ✓ (page header action)
- state passed: —
- context preserved: —
- navigation: direct
- feedback: —
- known gaps: none

#### Create Job → Rounds Setup
- user goal: configure the interview process for the new role
- expected next action: guided rounds setup immediately after submit
- actual next action: same ✓ (auto-redirect; page copy explains "Define the role first; interview rounds can be configured next")
- state passed: new job pk
- context preserved: job title in page title/breadcrumb
- navigation: forced forward (good)
- feedback: success toast ("Job X created")
- known gaps: auto-reject baseline field lacks visible help text in the form (help_text set in form class but template omits the form-help paragraph — its "requires at least one requirement" constraint surfaces only as a post-submit validation error)

#### Rounds Setup → Job Detail
- user goal: finish setup, see the job
- expected next action: "Done, go to job"
- actual next action: same ✓
- state passed: job pk
- context preserved: breadcrumb Jobs / <title> / Set up rounds
- navigation: direct
- feedback: rounds listed with order
- known gaps: this is the ONLY surface with round reorder (GAP-001)

#### Job Detail → CV Upload
- user goal: get candidates into this job
- expected next action: "Upload CVs" primary button
- actual next action: same ✓ (carries ?job=<pk>)
- state passed: job pk → Position dropdown preselected (verified live)
- context preserved: job context enters the form
- navigation: direct
- feedback: helper copy under the select
- known gaps: none

#### CV Upload → Candidates List
- user goal: see the parsed candidates
- expected next action: land filtered to the job just filled
- actual next action: lands UNFILTERED (GAP-006)
- state passed: toast names the job; job pk dropped
- context preserved: ✗ (job context lost)
- navigation: direct but context-free
- feedback: success toast with created/linked counts
- known gaps: GAP-006

#### Candidates List → Candidate Detail
- user goal: inspect/review a candidate
- expected next action: click row name
- actual next action: same ✓
- state passed: candidate pk
- context preserved: filters preserved in tab links (needs_review etc. carry ?job=); topbar search box does NOT re-populate on back (page-level filter box does)
- navigation: direct
- feedback: —
- known gaps: topbar search box empties after back while the page filter keeps the value (minor inconsistency, P3-level, not ledgered)

#### Candidate Detail → Stage Move (pipeline)
- user goal: advance a candidate
- expected next action: "Move to…" select per application
- actual next action: same ✓; terminal moves confirm via modal; HTMX row swap in place
- state passed: stage value; source=detail
- context preserved: row swapped in place, no reload
- feedback: success = row swap; failure = 5s toast (ephemeral — GAP-008)
- known gaps: GAP-008

#### Kanban Board → Stage Move
- user goal: move candidates visually
- expected next action: drag card between columns
- actual next action: same ✓ (HR only; card not draggable for terminal states)
- state passed: stage; source=board
- context preserved: card stays in source column on failure ("never has to be visually undone")
- feedback: board toast on failure (same 409 message), silent success (card moves)
- known gaps: GAP-008 applies; no keyboard alternative for drag-and-drop (cards are tabindex=0 but no key handler moves them — a11y note, not ledgered as a journey gap yet)

#### Dashboard KPI → filtered list (deep links)
- user goal: act on a KPI
- expected next action: click card → filtered list matching the KPI
- actual next action: same ✓ for most cards (Total Applications, Open Positions, Pending Feedback, Needs Review)
- state passed: query params (job, needs_review, sort, stage)
- context preserved: list honors params; tab links re-preserve them
- navigation: direct
- feedback: —
- known gaps: Total Applications KPI counts closed-job applications against an "Active pipeline" label (GAP-004); Risk/Health AI-card action links mismatch their recommendations (GAP-005)

### Interviewer chain

#### Login → Interviewer Dashboard
- user goal: see my work
- expected next action: assigned candidates + pending feedback
- actual next action: same ✓ (302 → /interviewer-dashboard/)
- state passed: session
- context preserved: —
- navigation: direct
- feedback: availability banner when no windows declared (with "Set your availability now" CTA — good continuation)
- known gaps: none

#### Interviewer Dashboard → Feedback Form
- user goal: submit feedback for an assigned candidate
- expected next action: "Give feedback" button per row needing feedback
- actual next action: same ✓ (carries ?next= back to dashboard)
- state passed: app pk + round pk + next URL
- context preserved: form pre-fills criteria on re-entry (edit mode)
- navigation: direct
- feedback: success toast + redirect to ?next (dashboard context kept)
- known gaps: no edit path for already-submitted feedback from the dashboard (GAP-010)

#### Pending Feedback list → Feedback Form
- user goal: work through my pending evaluations
- expected next action: "Submit Feedback" per row
- actual next action: same ✓ (?next=/feedback/?status=pending preserves the working list)
- state passed: app/round pks + next
- context preserved: ✓
- navigation: direct
- feedback: —
- known gaps: none

#### My Calendar (read-only surface)
- user goal: see booked interviews
- expected next action: click an interview to open the candidate/feedback
- actual next action: entries are NOT links — plain text cards
- state passed: —
- context preserved: —
- navigation: none available
- feedback: —
- known gaps: calendar entries have no click-through to candidate or feedback (minor dead-end; noted, not ledgered this cycle — information is duplicated on the dashboard table which does link)

### Management chain

#### Login → Management Dashboard (read-only)
- user goal: oversight
- expected next action: KPIs, insights, exports
- actual next action: same ✓ (redirects to hr_dashboard; write buttons hidden)
- state passed: session
- context preserved: —
- navigation: direct
- feedback: —
- known gaps: GAP-002 (AI button leak)

#### Management → Reports Export / Retention
- user goal: take data out
- expected next action: CSV download / retention table
- actual next action: same ✓ (CSV attachment; retention links "View candidates →" per closed job)
- state passed: —
- context preserved: —
- navigation: direct
- feedback: browser download
- known gaps: none

#### Job Detail → Close (terminal edge)
- user goal: wind down a filled job
- expected next action: confirm with reason; learn what happened to active candidates
- actual next action: confirm modal → toast; rejection emails sent SILENTLY (GAP-011)
- state passed: closure reason
- context preserved: job detail stays; Reopen affordance appears
- navigation: stays on detail
- feedback: toast lacks email-batch outcome (GAP-011)
- known gaps: GAP-011

#### Candidate Detail → Assign Interviewer → Notification
- user goal: hand a candidate to the right interviewer
- expected next action: pick eligible interviewer → slot preview → assign → interviewer notified
- actual next action: same ✓ (eligibility gate blocks ineligible picks with explanation; notification created; popover click-through to candidate marks it read)
- state passed: app pk, interviewer pk; notification link to candidate
- context preserved: slot preview refreshes on change (HTMX)
- navigation: stays on detail
- feedback: success toast + interviewer notification
- known gaps: none (verified live 2026-09-21 cycle 2)

#### Import → Candidate Detail
- user goal: add a CV-less candidate from pasted text
- expected next action: land on the new candidate's detail with confirmation
- actual next action: same ✓ (toast "Imported X for Y"; redirect to detail)
- state passed: parsed candidate + application
- context preserved: candidate context established immediately
- navigation: direct
- feedback: success toast
- known gaps: none (verified live 2026-09-21 cycle 2)

#### Retention Report → Candidates List (closed job)
- user goal: review a closed job's retained candidates
- expected next action: "View candidates →" lands filtered, dropdown reflects the closed job
- actual next action: same ✓ (GAP-012 fixed: dropdown now lists closed jobs marked "(closed)")
- state passed: job pk
- context preserved: filter reflected in the select
- navigation: direct
- feedback: —
- known gaps: none (verified cycle 2)

#### Job Detail → Talent Pool Add
- user goal: re-engage a strong past candidate for a new role
- expected next action: suggestions section on job detail → "Add to this job" → application created
- actual next action: same ✓ (toast names the candidate; the new application is visible on the job)
- state passed: old application pk → new application on target job
- context preserved: stays on job detail
- navigation: direct
- feedback: success toast
- known gaps: none (verified cycle 2)

#### Availability → Interview Scheduling (HR side)
- user goal: book an interview inside the interviewer's real availability
- expected next action: slot preview shows role match + windows + next free slots; HR picks a slot inside a window
- actual next action: same ✓; server VALIDATES window membership — an out-of-window time is rejected with "not available at that time. Check their availability and pick a slot inside a weekly window."
- state passed: interview_at; eligibility + windows
- context preserved: row-level form
- navigation: stays on detail
- feedback: success toast with the scheduled time; clear rejection copy
- known gaps: none (verified cycle 2)

#### Interview Scheduling → Interviewer Calendar/Dashboard
- user goal: interviewer sees the booked interview
- expected next action: dashboard row shows the time; calendar groups by day; entry clickable
- actual next action: same ✓ (calendar entries are now links to the candidate — 1.2d)
- state passed: interview_at → both surfaces
- context preserved: —
- navigation: calendar → candidate detail
- feedback: —
- known gaps: none (verified cycle 2)

#### Notifications → Mark-all-read / Unread filter
- user goal: manage notification backlog
- expected next action: filter unread; mark all read; badge syncs
- actual next action: same ✓ (badge drops to 0 after mark-all)
- state passed: read state
- context preserved: —
- navigation: —
- feedback: badge count
- known gaps: none (verified cycle 2)

#### Public Apply (E2E submit)
- user goal: apply with a real CV
- expected next action: submit → thanks → parsed candidate in the job's pipeline
- actual next action: same ✓ (consent required; parse extracted name/skills correctly; status new)
- state passed: CV file → parsed fields; fallback contact merges only gaps
- context preserved: —
- navigation: thanks → "Browse other open roles"
- feedback: thanks page
- known gaps: none (verified cycle 2)

#### Small affordances (score reset, reopen, rounds delete)
- score reset: confirm modal with accurate copy ("fall back to their auto-score") → "Score cleared." toast ✓
- job reopen: button appears immediately on closed jobs ✓
- rounds delete: confirm modal with consequence copy ✓
- known gaps: none (verified cycle 2)

### Public chain

#### Careers → Public Apply → Thanks
- user goal: apply to a role
- expected next action: Apply → form → submit → confirmation with next step
- actual next action: same ✓ (thanks page offers "Browse other open roles" — no dead end; back-link to careers on form)
- state passed: job pk; typed fallback contact merged into parse gaps
- context preserved: careers → apply → thanks → careers loop closes
- navigation: direct
- feedback: parse errors surfaced; consent checkbox required
- known gaps: none observed this pass

## Known gaps

See `PRODUCT_GAP_LEDGER.md` — GAP-001 … GAP-010 as of 2026-09-21. Linked per-edge above.

## Test infrastructure (Phase 3)

- `make qa-all` = lint gate + Django suite (467 tests) + 18 Playwright transition specs
- Specs in `tests/feature-transitions/`, seeded by `qa/scripts/e2e_seed.py` (idempotent, `--json` for specs, `--clean` to remove)
- CI: `.github/workflows/qa.yml` — ruff → Django suite → Playwright specs on push/PR; fails if `qa/` session state is staged
- `altrium_tracker/ci_settings.py`: sqlite/MD5-hasher/no-secrets profile for CI
- Auth in specs: programmatic login via the real form (no storage-state dependency)

## Accessibility status (Phase 4 sweep)

axe-core over the five core journey surfaces (HR dashboard, candidate detail,
Kanban board, IV dashboard, public careers): **zero violations** after fixes:
- Light-theme status tokens darkened for WCAG AA small text: pending #a35605→#8a4a04, hired #04815a→#036447, danger #DC2626→#B91C1C
- `.score-ring-mid` now uses the theme-scoped pending tokens (was a fixed orange)
- IV dashboard gained the standard page-header h1; candidate-detail section labels promoted h3→h2 (no level skips)
- Re-scan tooling: `node qa/scripts/axe_journey_scan.js` (add surfaces as journeys grow)

## UI patterns section (from ui-consistency-inventory, first pass)

Shared implementations observed:
- `templates/base.html`: sidebar (role-gated nav groups), topbar search (global → candidates list), notification popover + 30s unread poll, confirm modal (`confirmAction`), toast system (5s auto-dismiss), stage-select guard (`confirmStageMove`), HTMX error → toast handlers
- `templates/includes/theme_toggle.html`: theme switch (both themes)
- `pipeline/_app_row.html`: the canonical application control row (interview details, assign+slot-preview, move-stage, feedback history link) — used on candidate detail; a separate `_list_app_row.html` variant serves the candidates list
- `candidates/_fit_summary.html`: AI fit panel (missing role gate — GAP-002)
- `candidates/_slot_preview.html`: assignment eligibility preview badges
- `feedback/_general_feedback.html`: AI-consolidated cross-round feedback card

Consistency observations (first pass):
- Badge vocabulary is inconsistent: `badge-feedback` doubles for "Feedback Submitted", "Feedback Pending", "Match pending", "N shown", "pending" count, and "No availability" — six meanings, one style; `badge-pending` is used in 2 templates but defined nowhere (GAP-003)
- "Feedback Pending" badge: `badge-feedback` on candidate detail rows vs `badge-pending` on the feedback list — same state, different classes/styles across pages
- Terminology is otherwise strong: "Candidate"/"Position"/"Round" used consistently; destructive actions consistently confirm via modal with explicit consequence copy
