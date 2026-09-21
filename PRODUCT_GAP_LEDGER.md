# Product Gap Ledger

Every confirmed issue in this product is recorded here. This file is the persistent state of the continuity workflow — read it first in every session, update it last.

Statuses: `OPEN` → `INVESTIGATING` → `FIXING` → `FIXED` → `VERIFIED`, or terminal `WONT-FIX` / `DUPLICATE`.

Entry template:

```text
GAP-ID:
TITLE:
CATEGORY:
SOURCE FEATURE:
DESTINATION FEATURE:
USER GOAL:
EXPECTED EXPERIENCE:
ACTUAL EXPERIENCE:
WHY IT IS A GAP:
REPRODUCTION:
EVIDENCE:
IMPACT:
PRIORITY:
ROOT CAUSE:
PROPOSED FIX:
STATUS:
REGRESSION TEST:
```

Categories in use: `State Handoff`, `Navigation`, `UX`, `Workflow Gap`, `Consistency`, `Accessibility`, `Visual Regression`, `Data`, `Performance`, `Regression`.

Priorities: `P0` blocks a core workflow · `P1` degrades a core workflow · `P2` friction/polish.

---

<!-- Entries below. Newest at top. Keep GAP-IDs stable forever. -->

## GAP-001

TITLE: Job detail offers no way to reorder interview rounds after creation

CATEGORY: Workflow Gap

SOURCE FEATURE: Job Detail

DESTINATION FEATURE: Rounds Setup (unreachable post-creation)

USER GOAL: Fix a mistaken round order (e.g. swap "System Design" before "Interview") discovered while running the pipeline.

EXPECTED EXPERIENCE: From the job detail rounds table, reorder the rounds (the same inline reorder the creation-time setup page offers).

ACTUAL EXPERIENCE: The rounds-setup page (`/jobs/<pk>/rounds-setup/`) with its inline reorder form (`jobs:round_reorder`) is reachable ONLY as the redirect target immediately after job creation. Job detail lists rounds with an "Order" column, an "Add round" form, and per-round "Remove round" buttons — but no reorder controls and no link back to the setup page.

WHY IT IS A GAP: The edge Job Detail → Rounds Setup does not exist, so the reorder capability is orphaned after the creation flow ends. HR must delete and re-add rounds (losing round-linked data/assignments) to change order.

REPRODUCTION: Log in as HR → open any existing job detail (`/jobs/82/`) → observe the Interview rounds table: order column is plain text, no reorder affordance, no link to rounds-setup.

EVIDENCE: `qa/evidence/job-detail-snapshot.yml` (rounds table with static Order cells); `jobs/views.py:379` (RoundReorderView exists but only wired from rounds_setup.html); `jobs/templates/jobs/job_detail.html` (no reorder form).

IMPACT: Wrong round order breaks the pipeline progression semantics (candidates move in `order` sequence); correcting it requires destructive round deletion.

PRIORITY: P1

ROOT CAUSE: `jobs:round_reorder` endpoint exists and works, but is only rendered in `rounds_setup.html`; `job_detail.html` was never given the reorder form.

PROPOSED FIX: Add the inline reorder form (or an "Edit rounds" link to the setup page) to the Interview rounds table in `job_detail.html`, HR-only.

STATUS: VERIFIED

REGRESSION TEST: — (write after fix: `job-detail-to-round-reorder.spec.ts`)

---

## GAP-002

TITLE: "Generate AI assessment" button shown to read-only Management users, fails on click

CATEGORY: UX (affordance/permission mismatch)

SOURCE FEATURE: Candidate Detail (Job fit panel)

DESTINATION FEATURE: AI Fit Summary endpoint (403)

USER GOAL: Management reviewing a candidate wants to understand the AI assessment.

EXPECTED EXPERIENCE: Read-only role sees the assessment (or an explanation that generating is an HR/interviewer action) — no interactive control that cannot work.

ACTUAL EXPERIENCE: The "Generate AI assessment" button renders for Management (`_fit_summary.html` has no role gate). Clicking it POSTs to `candidates:ai_fit`, which returns 403 "Management has read-only access." — surfaced only as a generic HTMX error toast.

WHY IT IS A GAP: UI promises an action the role is not allowed to take; the failure feedback is an error, not guidance.

REPRODUCTION: Log in as Management QA account → open any candidate with a job-fit panel and no AI summary (`/candidates/216/`) → click "Generate AI assessment" → error toast.

EVIDENCE: `qa/evidence/mgmt-candidate-snapshot.yml` (button present, lines 91-106); `candidates/views.py:593` (403 for management); `candidates/templates/candidates/_fit_summary.html` (no role condition).

IMPACT: Every Management user hits a dead button on most candidate profiles; erodes trust in read-only contract.

PRIORITY: P1

ROOT CAUSE: `candidates/templates/candidates/_fit_summary.html` renders the action button unconditionally; the role check lives only in the view.

PROPOSED FIX: Gate the button in `_fit_summary.html` on `user.is_hr or user.is_interviewer` (management sees "No AI assessment yet." text only), or pass an `is_management` context flag from `CandidateDetailView` (it already provides `is_management`).

STATUS: VERIFIED

REGRESSION TEST: — (write after fix: `mgmt-candidate-detail-no-ai-button.spec.ts`)

---

## GAP-003

TITLE: "Needs Review" flag badge on candidate detail is unstyled and shows raw snake_case reason codes

CATEGORY: Consistency (+ minor UX)

SOURCE FEATURE: Candidate Detail

DESTINATION FEATURE: Candidate Review

USER GOAL: HR triaging flagged candidates sees at a glance why a candidate was flagged.

EXPECTED EXPERIENCE: A visually distinct status badge (like every other badge in the app) with a human-readable reason.

ACTUAL EXPERIENCE: The badge uses class `badge-pending`, which has NO CSS rule in `app.css` (grep: 0 definitions), so it renders as unstyled text; and it prints the raw reason code ("Needs Review: low_text_volume") while the review page humanizes the same codes ("Very little text was extracted. The file may be corrupted or image-based.").

WHY IT IS A GAP: Two consistency breaks — (1) undefined CSS class = visual inconsistency with the app's badge system; (2) same concept, two vocabularies across two connected screens (terminology consistency, 14-point edge check #12).

REPRODUCTION: Log in as HR → open a flagged candidate (`/candidates/1337/`) → observe the "Needs Review: low_text_volume" link near the page actions.

EVIDENCE: `qa/screenshots/needs-review-badge.png` (vision-verified: unstyled plain text, contrasted with styled badges nearby); `candidates/templates/candidates/candidate_detail.html:24`; `static/css/app.css` (no `.badge-pending` rule); `candidates/templates/candidates/candidate_review.html:19-21` (humanized labels exist).

IMPACT: Flagged candidates are less scannable; reason codes leak internal vocabulary to HR users.

PRIORITY: P2

ROOT CAUSE: `badge-pending` class was never defined in CSS; reason codes rendered raw instead of reusing the review page's label map.

PROPOSED FIX: Add a `.badge-pending` rule (amber, matching the pending status token used elsewhere), and humanize reasons in `candidate_detail.html` (shared template filter or reuse the review page's mapping — shared-first rule applies).

STATUS: VERIFIED

REGRESSION TEST: — (write after fix: visual assertion that the badge has the pending styling)

---

## GAP-004

TITLE: Dashboard "Total Applications" KPI counts applications on closed jobs, contradicting its "Active pipeline" subtitle

CATEGORY: Data (KPI semantics)

SOURCE FEATURE: HR Dashboard (KPI cards)

DESTINATION FEATURE: Candidates List (deep link)

USER GOAL: Understand how many candidates are actively in the pipeline.

EXPECTED EXPERIENCE: "Total Applications — Active pipeline" reflects applications on active jobs (or is labeled to say it counts everything, including closed jobs).

ACTUAL EXPERIENCE: The KPI sums ALL applications regardless of job status (1121 total, of which only 461 sit on active jobs; 4 closed jobs hold the rest). The subtitle says "Active pipeline". The adjacent "Candidates by Stage" chart uses the same all-jobs dataset.

WHY IT IS A GAP: The number and its label disagree; HR comparing the KPI to the filtered candidate list sees an unexplainable 660-candidate discrepancy.

REPRODUCTION: HR dashboard → read "Total Applications 1120 / Active pipeline" → click it (lands on unfiltered list) → filter to active jobs → count ≈ 461.

EVIDENCE: `accounts/views.py:195-223` (stage_counts over all JobApplication, no job-status filter); live snapshot `qa/evidence/hr-dashboard-snapshot.yml` lines 59-66; DB counts verified 2026-09-21 (1121 vs 461).

IMPACT: Management/HR misread pipeline size in the primary dashboard surface; decisions (capacity, escalation) keyed to an inflated number.

PRIORITY: P1

ROOT CAUSE: `stage_counts` query in `HRDashboardView.get_context_data` lacks a `job__is_active=True` filter while the label promises "active pipeline".

PROPOSED FIX: Either scope the KPI + stage chart to active jobs (matching the subtitle), or relabel to "Total Applications — all time". Decide intent first (shared KPI used by Management too).

STATUS: VERIFIED

REGRESSION TEST: — (write after fix: dashboard KPI vs DB count consistency test)

---

## GAP-005

TITLE: Dashboard AI insight action links point to surfaces that don't match their recommendations

CATEGORY: State Handoff (intent mismatch)

SOURCE FEATURE: HR Dashboard (AI Insights cards)

DESTINATION FEATURE: Feedback List / Candidates List

USER GOAL: Act on the AI recommendation with one click.

EXPECTED EXPERIENCE: "Review pending candidate evaluations" leads to the pending evaluations; "Schedule overdue interviewer evaluations" leads to scheduling or the stalled-candidates list.

ACTUAL EXPERIENCE: Both the Pipeline Health card and the Risk Monitor card link to `feedback:list?status=pending` regardless of their recommendation text. The Health card's "Review pending candidate evaluations" is arguably correct, but Risk's "Schedule overdue interviewer evaluations" lands on a feedback list that shows only 2 pending rows owned by OTHER interviewers — not the 751 stalled candidates the card describes. The stalled candidates themselves ARE listed in the adjacent Escalations panel with links, but the card's own action link doesn't lead to them.

WHY IT IS A GAP: Action link target does not deliver the promised next step (14-point edge check #2/#4); user clicks "Schedule overdue evaluations" and finds a list of 2 rows that are not theirs to schedule.

REPRODUCTION: HR dashboard → Risk Monitor card (HIGH, 751 stalled) → click "Schedule overdue interviewer evaluations →" → lands on Pending Feedback list (2 rows, other interviewers' work).

EVIDENCE: `accounts/templates/accounts/hr_dashboard.html:348,384` (both cards hardcode `feedback:list?status=pending`); `accounts/views.py:488` (recommendation text); `qa/evidence/hr-dashboard-snapshot.yml` lines 326-327.

IMPACT: Broken action affordance on the highest-urgency dashboard card; user must manually navigate to find the 751 candidates.

PRIORITY: P1

ROOT CAUSE: Template hardcodes one URL for all risk-card recommendations instead of an `action_url` per insight.

PROPOSED FIX: Add an `action_url` field to each insight dict in `accounts/views.py` and render `{{ insight.action_url }}` in the template (health → pending feedback only when the recommendation is about feedback; risk → candidates list filtered to stalled, e.g. a `?stalled=1` param or the escalations data source).

STATUS: VERIFIED

REGRESSION TEST: — (write after fix: insight action URL matches recommendation test)

---

## GAP-006

TITLE: Upload-CV success loses job context: lands on unfiltered candidates list

CATEGORY: State Handoff

SOURCE FEATURE: CV Upload (entered with ?job=<pk> preselect)

DESTINATION FEATURE: Candidates List

USER GOAL: After uploading CVs for a specific job, see those candidates in that job's pipeline.

EXPECTED EXPERIENCE: Land on the candidates list already filtered to the job just filled (or the job detail/board), so the fresh cohort is immediately visible.

ACTUAL EXPERIENCE: Upload succeeds (toast: "N candidate(s) created, M linked to "<Job>"."), then redirect to `/candidates/` with NO job filter — an unfiltered 1120-row list. The just-uploaded candidates are on page 1 (sorted by -updated_at) but mixed with every other job's candidates.

WHY IT IS A GAP: The upload page received `?job=89` and the form preselected it — the state exists at entry and is dropped at exit (context loss after creation, dead-end detection category). The toast names the job but doesn't link it.

REPRODUCTION: Job detail → "Upload CVs" → upload a CV → observe landing on unfiltered list; the Position filter is empty.

EVIDENCE: Server log 2026-09-21 (`POST /candidates/upload/?job=89` 302 → `GET /candidates/` 200); `candidates/views.py:307` (`return redirect('candidates:list')`); live run observation (Jane visible in list, filter empty).

IMPACT: Extra navigation for the most common post-upload action (verify the parse); risk of misfiling perception when many jobs are active.

PRIORITY: P2

ROOT CAUSE: Success redirect hardcodes `candidates:list` without propagating the job pk.

PROPOSED FIX: Redirect to `candidates:list?job=<pk>` when a job was selected (the list already honors `?job=`), keeping the toast.

STATUS: VERIFIED

REGRESSION TEST: upload redirect verified live (POST 302 -> /candidates/?job=82, filter applied); transition spec pending UI upload harness

---

## GAP-007

TITLE: Account lockout message omits the cooldown duration

CATEGORY: UX (error clarity)

SOURCE FEATURE: Login

DESTINATION FEATURE: Login (retry)

USER GOAL: Know when I can try again after being locked out.

EXPECTED EXPERIENCE: "Account locked: too many login attempts. Try again in about an hour." (matches the configured 1h cooloff).

ACTUAL EXPERIENCE: 429 response shows "Account locked: too many login attempts. Please try again later." — no duration.

WHY IT IS A GAP: The system knows the cooloff (AXES_COOLOFF_TIME = 1 hour) but doesn't share it; a locked-out HR user cannot tell whether to wait 5 minutes or a day.

REPRODUCTION: Fail login 5 times for one username → 6th attempt shows the generic "later" message.

EVIDENCE: Live reproduction 2026-09-21 (5 failures → 429; visible text captured); `altrium_tracker/settings.py:82-84`.

IMPACT: Support burden and user anxiety during lockouts; low frequency event.

PRIORITY: P2

ROOT CAUSE: django-axes lockout response uses its default message; no custom lockout template/callable configured.

PROPOSED FIX: Set `AXES_LOCKOUT_CALLABLE` (or a lockout template) that renders the configured cooloff duration.

STATUS: VERIFIED

REGRESSION TEST: message text verified live; no dedicated test (config constant)

---

## GAP-008

TITLE: Feedback gate rejection (409) feedback is ephemeral — toast only, no persistent state in the row

CATEGORY: UX (feedback/recovery)

SOURCE FEATURE: Candidate Detail (Move Stage select) / Kanban Board

DESTINATION FEATURE: Pipeline Move endpoint (409)

USER GOAL: Move a candidate to the next round; understand why it failed when blocked.

EXPECTED EXPERIENCE: The blocked move is explained at the point of action, persistently enough to act on (e.g. inline message near the select: "Feedback for Screening required first — [request it / view candidate]").

ACTUAL EXPERIENCE: A toast shows the server message for 5 seconds, then disappears. The row shows only the reverted select. The user must remember the reason or re-trigger the failure to see it again. Same on the Kanban board (board toast).

WHY IT IS A GAP: Recovery information evaporates; the gate is a designed business rule that deserves persistent explanation (Feedback dimension of the edge evaluation).

REPRODUCTION: As HR, move a candidate in a round without feedback to another round (or terminal) → observe toast → wait 5s → reason gone.

EVIDENCE: Live run 2026-09-21 (toast "Feedback is required before making a final hiring decision.×", then gone; select reverted to `round:284`); `templates/base.html:382` (5s auto-dismiss); `pipeline/views.py:107-111`.

IMPACT: Repeated confusion on a core workflow rule; users may re-attempt and re-fail.

PRIORITY: P2

ROOT CAUSE: Global toast system auto-dismisses all messages at 5s; HTMX row swap doesn't include error state.

PROPOSED FIX: For 409 responses on stage-select/board moves, render an inline error region in the swapped row (or extend toast duration for error-class messages).

STATUS: VERIFIED

REGRESSION TEST: toast persistence verified live (visible after 6s); no dedicated test (JS timing)

---

## GAP-009

TITLE: favicon.ico 404 on every page load

CATEGORY: UX (minor) / console noise

SOURCE FEATURE: All pages

DESTINATION FEATURE: —

USER GOAL: —

EXPECTED EXPERIENCE: No failed requests in console.

ACTUAL EXPERIENCE: Every page logs `Failed to load resource: 404 @ /favicon.ico`. The app declares `<link rel="icon" href="/static/img/logo.png">` (which loads fine), but browsers still request /favicon.ico when no explicit icon is resolved for certain contexts.

WHY IT IS A GAP: Console noise pollutes every debugging/evidence-collection session; trivially fixable.

REPRODUCTION: Open any page → console shows the 404.

EVIDENCE: `qa/evidence/console-*.log` during validation; `curl /favicon.ico` → 404; `templates/base.html:9`.

IMPACT: Cosmetic; pollutes error monitoring.

PRIORITY: P2

ROOT CAUSE: No favicon.ico served at root; the link-tag icon satisfies modern browsers but not the legacy default request.

PROPOSED FIX: Add a favicon.ico (can be the logo) at `static/` plus a root redirect/route, or serve `static/img/logo.png` as `favicon.ico`.

STATUS: VERIFIED

REGRESSION TEST: favicon 200 verified live; covered by console assertions in future specs

---

## GAP-010

TITLE: Interviewer dashboard lacks an edit path for already-submitted feedback

CATEGORY: Workflow Gap (minor)

SOURCE FEATURE: Interviewer Dashboard (assigned candidates table)

DESTINATION FEATURE: Feedback Form (edit mode)

USER GOAL: Fix a typo in feedback I submitted minutes ago.

EXPECTED EXPERIENCE: From the dashboard row showing "Submitted", an obvious way to view/edit my feedback.

ACTUAL EXPERIENCE: The row shows a "Submitted" badge with no action. Editing requires navigating: Feedback (sidebar) → find the row → Feedback Detail → "Edit" button. The dashboard "Give feedback" button disappears once feedback_submitted=True.

WHY IT IS A GAP: Continuation after completion is missing on the primary working surface; the edit path exists but requires unrelated navigation (dead-end detection: "feature requiring unrelated navigation to continue").

REPRODUCTION: Log in as an interviewer with submitted feedback → dashboard → row shows "Submitted" only → to edit, must go Feedback list → detail → Edit.

EVIDENCE: `accounts/templates/accounts/interviewer_dashboard.html:109-115` (binary submitted/give-feedback); `feedback/templates/feedback/feedback_detail.html:17` (Edit exists on detail).

IMPACT: Friction for a common correction task.

PRIORITY: P2

ROOT CAUSE: Dashboard row template doesn't render a "View/Edit" link for submitted feedback.

PROPOSED FIX: Add a ghost "View feedback" link in the Feedback cell when `app.feedback_submitted` (linking to the interviewer's own feedback detail, which already offers Edit).

STATUS: VERIFIED

REGRESSION TEST: tests/test_gap_regressions.py::Gap010InterviewerFeedbackLinkTest

---

## Resolved / duplicate tracking

(none yet)

---

## GAP-011

TITLE: Job close performs a silent mass-rejection-email side effect with no outcome feedback

CATEGORY: UX (feedback on consequential action)

SOURCE FEATURE: Job Detail (Close job)

DESTINATION FEATURE: Candidate email batch (side effect)

USER GOAL: Close a filled job and know that the losing candidates were informed.

EXPECTED EXPERIENCE: The confirmation toast reports the batch outcome ("Closed. 3 active candidates were emailed rejection notices.") and ideally links to the affected candidates; failures are surfaced, not swallowed.

ACTUAL EXPERIENCE: The toast says only "Job X closed. Existing candidates are unchanged." The rejection-email loop (jobs/views.py:136-158) sends one email per active applicant synchronously and swallows every failure into a logger.exception — the UI never mentions that emails were sent or that any failed.

WHY IT IS A GAP: A consequential, user-triggered side effect (outbound email to real people) is invisible. HR cannot tell whether the notifications went out; a mail outage is silent.

REPRODUCTION: Close any active job with active applicants → toast mentions nothing about emails; check server logs for the per-candidate outcome.

EVIDENCE: Live walk 2026-09-21 (job 82 closed with reason "Position filled"; toast captured; no email count); `jobs/views.py:124-158`.

IMPACT: Low-frequency but high-consequence action; missing feedback undermines trust in the closure flow.

PRIORITY: P2

ROOT CAUSE: The close view performs the email batch but never aggregates the outcome into the success message.

PROPOSED FIX: Count emailed/failed in the loop and append to the toast: "…; N active candidates were emailed rejection notices." (+ warning if failures > 0). STATUS: OPEN.

STATUS: VERIFIED

REGRESSION TEST: tests/test_gap_regressions.py::Gap011CloseEmailBatchFeedbackTest (3 tests: count, failure surfacing, none-needed)

---

## GAP-012

TITLE: Position dropdown omits closed jobs, hiding deep-linked closed-job filters

CATEGORY: State Handoff

SOURCE FEATURE: Retention Report ("View candidates →") / any closed-job context

DESTINATION FEATURE: Candidates List (job filter)

USER GOAL: From a closed job's context, see and re-filter its retained candidates.

EXPECTED EXPERIENCE: The Position dropdown reflects the incoming closed-job filter and lets the user pick closed jobs manually (closed-job data is searchable by design per the retention policy).

ACTUAL EXPERIENCE: The dropdown listed only active jobs, so a `?job=<closed_pk>` deep link produced a filtered list with an unmarked, apparently-unfiltered select; closed jobs were unselectable.

WHY IT IS A GAP: The filter state exists in the URL but is not reflected in the control (state handoff failure), and a documented capability (searching closed-job data) has no UI entry point.

REPRODUCTION: Retention report → "View candidates →" on a closed job → observe the Position select shows "All positions" while the list is filtered.

EVIDENCE: Live walk 2026-09-21 cycle 2 (`/candidates/?job=94&all=1`, select value ""); `candidates/views.py:157` (active-only dropdown).

IMPACT: Closed-job candidate review requires manual URL editing.

PRIORITY: P2

ROOT CAUSE: `CandidateListView.get_context_data` scoped the dropdown queryset to active jobs.

PROPOSED FIX: Include closed jobs in the dropdown, ordered active-first, with a "(closed)" marker.

STATUS: VERIFIED

REGRESSION TEST: tests/test_gap_regressions.py::Gap012ClosedJobsInPositionFilterTest
