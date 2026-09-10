# Altrium Hiring Tracker — Full Code Audit

**Scope:** Sprint 1 completeness, Interviewer Assignment & Availability deep-dive, RBAC, data integrity, endpoint inventory, test coverage, technical debt, Sprint 2 readiness.

---

## 1. Codebase Structure Summary

```
altrium-tracker/
├── altrium_tracker/          # Django project (settings, urls, wsgi, asgi)
│   ├── settings.py           # 278 lines, env-driven via decouple
│   ├── urls.py               # 18 lines, 7 app includes + admin + media
│   ├── wsgi.py / asgi.py
├── accounts/                 # User model, auth, dashboards, RBAC
│   ├── models.py             # 105 lines: User(AbstractUser) + InterviewerAvailability
│   ├── views.py              # 489 lines: 7 CBVs (login, dashboards, roster)
│   ├── urls.py               # 23 lines: 7 named patterns
│   ├── backends.py           # 19 lines: AxesTolerantBackend
│   ├── admin.py              # 13 lines
│   ├── tests.py              # 78 lines: 8 tests (auth/role basics)
│   ├── templatetags/accounts_extras.py  # 14 lines: avatar_index
│   └── management/commands/
│       ├── clean_and_seed_db.py  # 341 lines: wipe+reseed
│       ├── seed_users.py         # 53 lines: 3 accounts
│       ├── seed_testdata.py      # 119 lines: jobs+candidates via auto_apply
│       ├── checkdb.py            # 36 lines: deploy pre-hook
│       └── db_status.py          # 32 lines: model counts
├── jobs/                     # Job + InterviewRound models
│   ├── models.py             # 79 lines: Job + InterviewRound
│   ├── views.py              # 194 lines: CRUD + round management
│   ├── forms.py              # 81 lines: JobForm + RoundForm
│   ├── urls.py               # 16 lines: 8 routes
│   ├── signals.py            # 22 lines: post_save creates default rounds
│   ├── tests.py              # 127 lines: 10 tests
│   └── admin.py              # 15 lines: JobAdmin + InterviewRoundInline
├── ai/                       # AI library (NOT in INSTALLED_APPS)
│   ├── services.py           # 211 lines: Groq client + fallback
│   ├── matching.py           # 112 lines: scoring + dedup
│   ├── panel.py              # 206 lines: consensus algorithm
│   ├── cv_parser.py          # 45 lines: PDF/DOCX/text extraction
│   ├── tests.py              # 70 lines: 8 SimpleTestCase
│   └── apps.py               # orphan (never registered)
├── candidates/               # Core pipeline: Candidate + JobApplication
│   ├── models.py             # 253 lines: Candidate + JobApplication
│   ├── views.py              # 823 lines: CRITICAL — all pipeline logic
│   ├── forms.py              # 37 lines: CandidateImportForm
│   ├── urls.py               # 18 lines: 10 routes
│   ├── tests.py              # 959 lines: 19 classes, 55+ methods
│   └── admin.py              # 17 lines
├── pipeline/                 # Stage moves (HTMX endpoint)
│   ├── models.py             # 39 lines: PipelineMove audit
│   ├── views.py              # 90 lines: PipelineMoveView
│   ├── urls.py               # 9 lines: 1 route
│   └── tests.py              # 131 lines: 9 tests
├── feedback/                 # Interview feedback + edit history
│   ├── models.py             # 67 lines: InterviewFeedback + FeedbackEditHistory
│   ├── views.py              # 260 lines: list/form/detail/history/ai_polish
│   ├── forms.py              # 41 lines: FeedbackForm
│   ├── urls.py               # 13 lines: 5 routes
│   ├── tests.py              # 1 line: EMPTY (placeholder)
│   └── admin.py              # 30 lines
├── notifications/            # In-app notifications
│   ├── models.py             # 29 lines: Notification
│   ├── views.py              # 69 lines: list/unread_count/mark_read
│   ├── urls.py               # 12 lines: 4 routes
│   ├── tests.py              # 62 lines: 5 tests
│   ├── templatetags/notification_extras.py  # 20 lines: safe_link
│   └── admin.py              # 7 lines
├── templates/                # All HTML templates
│   ├── base.html             # 492 lines: global shell + all JS
│   ├── auth_base.html        # 41 lines: login shell
│   └── includes/theme_toggle.html  # 5 lines
├── static/css/app.css        # 4648 lines
├── media/cvs/                # uploaded CVs
├── requirements.txt          # 12 packages
├── Dockerfile                # 14 lines
├── compose.yaml              # 23 lines (postgres + django)
├── render.yaml               # 30 lines (production deploy)
├── Procfile                  # 1 line
├── .env.example              # 31 lines
└── db.sqlite3                # dev database
```

---

## 2. Endpoint Inventory

| # | Method | URL Pattern | View | Auth | Purpose |
|---|--------|-------------|------|------|---------|
| 1 | GET/POST | `login/` | LoginView | Public | Authenticate |
| 2 | GET/POST | `logout/` | LogoutView | Public | Session destroy |
| 3 | GET | `/` | HomeView | Login | Role-based redirect to dashboard |
| 4 | GET | `hr-dashboard/` | HRDashboardView | Login+HR/MGMT | Executive dashboard with analytics |
| 5 | GET | `interviewer-dashboard/` | InterviewerDashboardView | Login | Assigned candidates + upcoming |
| 6 | GET | `dashboard/` | ManagementDashboardView | Login | Redirect → hr-dashboard |
| 7 | GET | `interviewer-roster/` | InterviewerRosterView | Login+HR/MGMT | Interviewer list with availability |
| 8 | GET | `jobs/` | JobListView | Login | List jobs (active/closed) |
| 9 | GET/POST | `jobs/create/` | JobCreateView | Login+HR | Create job posting |
| 10 | GET | `jobs/<pk>/` | JobDetailView | Login | Job detail + rounds |
| 11 | GET/POST | `jobs/<pk>/edit/` | JobEditView | Login+HR | Edit job posting |
| 12 | POST | `jobs/<pk>/close/` | JobCloseView | Login+HR | Close job (deactivate) |
| 13 | POST | `jobs/<pk>/reopen/` | JobReopenView | Login+HR | Reopen closed job |
| 14 | GET/POST | `jobs/<job_pk>/rounds/new/` | RoundCreateView | Login+HR | Add interview round |
| 15 | POST | `jobs/rounds/<pk>/delete/` | RoundDeleteView | Login+HR | Delete interview round |
| 16 | GET | `candidates/` | CandidateListView | Login | List candidates (role-scoped) |
| 17 | GET/POST | `candidates/upload/` | CandidateUploadView | Login+HR | Upload CV files |
| 18 | GET/POST | `candidates/import/` | CandidateImportView | Login+HR | Paste-text import |
| 19 | GET | `candidates/<pk>/` | CandidateDetailView | Login | Candidate detail |
| 20 | POST | `candidates/<pk>/delete/` | CandidateDeleteView | Login+HR | Hard delete candidate |
| 21 | POST | `candidates/<pk>/score/` | ScoreUpdateView | Login+HR | Set qualitative score |
| 22 | POST | `candidates/applications/<pk>/ai-fit/` | AiFitSummaryView | Login+HR/IV | Generate AI assessment |
| 23 | POST | `candidates/applications/<pk>/assign/` | AssignApplicationView | Login+HR | Assign/unassign interviewer |
| 24 | POST | `candidates/applications/<pk>/interview-details/` | InterviewDetailsView | Login+HR | Set interview link/schedule |
| 25 | GET | `candidates/applications/<pk>/interviewer-slots/` | InterviewerSlotsView | Login+HR | Slot preview (HTMX) |
| 26 | POST | `pipeline/move/<pk>/` | PipelineMoveView | Login+HR | Stage move (HTMX) |
| 27 | GET | `feedback/` | FeedbackListView | Login | Feedback list (role-scoped) |
| 28 | GET/POST | `feedback/<app_pk>/<round_pk>/` | FeedbackFormView | Login+IV | Submit/edit feedback |
| 29 | GET | `feedback/<pk>/` | FeedbackDetailView | Login | Feedback detail |
| 30 | GET | `feedback/<pk>/history/` | FeedbackHistoryView | Login | Edit history |
| 31 | POST | `feedback/ai-polish/` | AIPolishView | Login+IV | AI note polish (HTMX) |
| 32 | GET | `notifications/` | NotificationListView | Login | Notification list |
| 33 | GET | `notifications/unread-count/` | UnreadCountView | Login | Badge count (HTMX) |
| 34 | POST | `notifications/<pk>/read/` | MarkReadView | Login | Mark read (HTMX) |
| 35 | POST | `notifications/read-all/` | MarkAllReadView | Login | Mark all read |

**Note:** No candidates ever log in — this is internal-only (no candidate portal).

---

## 3. Sprint 1 Feature Audit (20 Items)

### 3.1 Authentication & RBAC (HR / Interviewer / Management)

**Status:** Partially working

**Evidence:** `accounts/models.py:6-65` (Role choices, User model, helpers); `accounts/backends.py:13-19` (AxesTolerantBackend); `altrium_tracker/settings.py:77-86` (axes config); `altrium_tracker/settings.py:135-140` (auth user model)

**What it actually does:** Three roles (HR, IV, MGMT) with helper methods (is_hr/is_interviewer/is_management). Login redirects by role to respective dashboards. Django-axes lockout at 5 failures per username+IP with 1-hour cooloff. AxesTolerantBackend allows test client auth without request (falls through to ModelBackend). All views use `LoginRequiredMixin` plus explicit dispatch-level or post-level role checks.

**Gaps:**
- `InterviewerDashboardView` (`accounts/views.py:388`) has **no role gate** — any authenticated role (including HR/Management) renders it successfully with empty data. Cosmetic leak, not a data leak (data is self-scoped by user).
- Default role is HR (`accounts/models.py:13`), so new users created without role kwarg get full HR access.
- No password expiry or forced rotation.
- Test password `testpass123` hardcoded in README and seed commands — published for the demo instance.
- AxesTolerantBackend bypasses lockout monitoring for programmatic/test authentication — intentional but should be documented for any future automation.

**Severity:** Medium — RBAC is functional but the default-role=HR gap means any future user-addition path that doesn't set role explicitly creates an HR user.

### 3.2 Job Creation & Custom Interview Rounds

**Status:** Partially working

**Evidence:** `jobs/models.py:7-79` (Job + InterviewRound); `jobs/views.py:46-61` (create), `145-173` (round create), `176-194` (round delete); `jobs/signals.py:13-22` (post_save creates 3 defaults); `jobs/forms.py:55-68` (auto_reject validation)

**What it actually does:** HR creates a job; a post_save signal auto-creates Screening(1)/Interview(2)/Offer(3) rounds. HR can add/remove custom rounds via inline form on the detail page. Round ordering is by `order` field + `id`. Close/reopen toggles `is_active` without touching applications.

**Gaps:**
- **Duplicate round name = HTTP 500.** `RoundForm` never calls `validate_unique()` (`jobs/views.py:162-165`); the `UniqueConstraint` on `(job, name)` (`jobs/models.py:71-76`) raises `IntegrityError` at DB level. `RoundForm` has no `clean_name` override. This is an unhandled crash — verified: POSTing `name=Interview&order=5` to an existing job that has "Interview" produces a 500.
- **RoundDeleteView has no `is_active` check** (`jobs/views.py:180-185`) while RoundCreateView does (`jobs/views.py:157-159`) — asymmetric. Rounds are deletable on closed jobs.
- **RoundDeleteView has no `template_name`** (`jobs/views.py:176-178`) — GET requests render Django's default DeleteView confirmation template (plain text), not the app's styled template. Only POST (from the detail page's confirm dialog) is exercised.
- **Round ordering: manual `order` field with no default auto-increment.** The `order` field is `PositiveIntegerField(default=0)` (`jobs/models.py:63`), `blank=False`. Empty submission silently fails HTML5 validation but the UX has no visible error feedback; the round just doesn't appear.
- **Round deletion CASCADE destroys feedback history.** `InterviewFeedback.round` is `on_delete=models.CASCADE` (`feedback/models.py:13`); `FeedbackEditHistory.feedback` is also `CASCADE` (`feedback/models.py:48`). Deleting a round silently wipes all interviewer scores, notes, and edit history for that round. Data retention claim is violated.
- **Hiring manager dropdown shows all 19 users** including test accounts (`accounts/templates/accounts/login.html` quick-fill), but `Job.hiring_manager` is `SET_NULL` with no role restriction — interviewers and management users can be set as hiring managers.
- **`is_final` flag** (`jobs/models.py:64`) exists in the model but is never used in any logic — it's purely cosmetic.

**Severity:** High — duplicate round name 500 is a live crash; cascade delete destroys audit trail.

### 3.3 CV Ingestion & Fallback AI Parsing (PDF/DOCX + paste, local fallback)

**Status:** Partially working

**Evidence:** `ai/cv_parser.py:8-45` (text extraction); `ai/services.py:57-167` (parse_cv + fallback); `candidates/views.py:157-314` (upload), `317-406` (import)

**What it actually does:** Upload path reads files, extracts text via pdfminer (PDF) or python-docx (DOCX), sends to Groq for structured JSON extraction, falls back to local regex parsing on any Groq failure. Name heuristic scans first 6 non-blank lines for 1-3 alpha words (skipping email/resume/URL lines). Skills matched against 57-entry whitelist via word-boundary regex. Email dedup via `Candidate.objects.get_or_create(email=...)`. Re-upload refreshes `resume_file`, `resume_text`, and `skills` on existing candidates. Paste-import uses the same parse+dedup pipeline with the `CandidateImportForm`.

**Gaps:**
- **Groq model `llama-3.3-70b-versatile` returns 404** on every call (server logs show it constantly) — confirmed by the live audit. Every AI parse falls to the local regex fallback. All "AI" features are actually heuristic.
- **Name parsing frequently fails.** The fallback grabs the first line with 1-3 alpha words from the top 6 lines (`ai/services.py:102-112`). If a candidate's name is on line 7+ or their CV starts with a header/skills block, the name is extracted incorrectly (e.g., "Docker" was extracted as a candidate first name during the live audit). There's no way to edit parsed fields post-import.
- **DOCX extraction silently fails on legacy `.doc` files** — falls to UTF-8 decode (`ai/cv_parser.py:16-20`) which produces garbage characters but no error.
- **Binary files disguised as `.pdf`** silently produce empty candidate records — a PNG named `.pdf` passes the extension gate, produces empty text, creates a candidate with empty fields (`ai/cv_parser.py:19-20`).
- **No file size limit at the extraction level** — `cv_parser.py:11` does `uploaded_file.read()` loading entire file into memory. The upload cap (2/5 MiB) is at Django middleware level but no cap within the parser.
- **Two different skill-matching semantics coexist:** `ai/matching.py:15-18` uses whole-word lookaround regex; `ai/services.py:197-201` (fit_summary fallback) uses exact list membership after lowercasing. Results differ.

**Severity:** High — name misparse with no edit path creates garbage candidate records in production; Groq dead means zero actual AI runs.

### 3.4 CV Deduplication & Categorization

**Status:** Working

**Evidence:** `candidates/views.py:226-258` (upload dedup), `330-360` (import dedup); `candidates/models.py:10` (unique email)

**What it actually does:** Dedup key is email (lowercased). `Candidate.objects.get_or_create(email=email)` — new candidates get their profile; existing candidates get `resume_file`, `resume_text`, and `skills` refreshed (if parsed skills are non-empty). `JobApplication.objects.get_or_create(candidate=candidate, job=job)` creates one application per candidate per job (unique constraint at `candidates/models.py:171`). Email-less candidates bypass dedup entirely (get `email=None`; multiple None-email candidates can exist).

**Gaps:**
- No dedup without email — candidates without extracted emails create duplicate profiles on every import.
- No candidate name similarity matching or fuzzy dedup.
- `email=None` candidates accumulate silently and are hard to reconcile.
- When `email` is extracted but is empty string `''`, `.strip().lower()` produces `''` — this is falsy, so the `if email:` check at `views.py:226` sends it to the `else` branch creating an `email=None` candidate. An email of `''` in the database is unlikely but not impossible (if `get_or_create(email='')` ever ran).

**Severity:** Low — dedup is functional for the primary path (email present); edge case is `email=None` accumulation.

### 3.5 Search, Filter & Qualitative Scoring (0–100 shortlist override)

**Status:** Working

**Evidence:** `candidates/views.py:42-116` (search/filter/sort); `candidates/views.py:440-468` (score update)

**What it actually does:** Multi-field search (first_name, last_name, email, skills, job title) via `Q` objects with `icontains`. Filters by position, stage, min score. Default excludes hired/rejected unless `?all=1` or filtering by terminal status. HR-only score override (0–100) with reset. Pagination at 50 per page with out-of-range clamping.

**Gaps:**
- **`min_score` filter uses `candidate__score`** (`candidates/views.py:67`) not `JobApplication.shortlist_score` — a candidate with `shortlist_score=100` but `score=None` won't appear. The dashboard's "Avg. Shortlist Score" also reads `Candidate.score` (verified: 81.3 = avg of all candidate scores), not per-job shortlist scores. Two scoring systems with the same name.
- Search excludes terminal-status candidates silently — no hint to try `?all=1`.
- No bulk actions, export, or comparison views.

**Severity:** Medium — scoring confusion will mislead HR users; search miss on terminal-status candidates is a UX trap.

### 3.6 Interviewer Assignment & Notifications

**Status:** Partially working

**Evidence:** `candidates/views.py:471-640` (AssignApplicationView — 170 lines); `accounts/models.py:30-65` (eligibility/availability helpers); `notifications/models.py:5-29`

**What it actually does:** HR selects from an eligible-interviewer dropdown (role-match filtered). Two-click confirm dialog. Server re-validates: role eligibility (`is_eligible_interviewer_for`), availability existence (`has_availability`), reassignment reconciliation (`_reconcile_inherited_slot` checks `is_available_at` + clash query). Unassign via `__unassign__` sentinel clears `assigned_to` + `interview_at` + panel membership. Notifications created for assign/unassign/reassign/schedule events.

**Gaps:** See Deep-Dive Section (Section 4) — this is the most gap-dense area.

**Severity:** High — see Deep-Dive.

### 3.7 Interview Details & Scheduling (meeting links/instructions)

**Status:** Partially working

**Evidence:** `candidates/views.py:643-738` (InterviewDetailsView)

**What it actually does:** HR posts `interview_details` (text) and `interview_at` (datetime-local). Server parses with `datetime.fromisoformat`, makes aware in UTC if naive. Validates: interviewer availability (`is_available_at`), same-interviewer double-booking (exact-time clash query). Saves fields, notifies assigned interviewer.

**Gaps:**
- **Availability + double-booking checks are skipped entirely when no interviewer is assigned** (`views.py:682-683` — `if interviewer:` guard). HR can schedule any time without constraints.
- **Clash check is exact-equality** (`interview_at=scheduled`, `views.py:692-695`) — a booking at 09:00 and another at 09:30 don't conflict even though they overlap within a 60-minute window. Two interviewers could be double-booked with overlapping but non-identical times.
- **`datetime.fromisoformat` accepts date-only strings** (e.g., `2026-09-10` → midnight) — books a midnight interview.
- **No transaction wrapping** — crash between `app.save()` and `Notification.objects.create()` leaves inconsistent state.
- **The "scheduled at ... UTC" flash message** (`views.py:707-708`) always says UTC regardless of whether the input was in another timezone.

**Severity:** High — scheduling without an assigned interviewer bypasses all constraints; 09:00/09:30 overlap is not caught.

### 3.8 Structured Interview Feedback (round-specific scorecards, role-scoped submission)

**Status:** Working

**Evidence:** `feedback/views.py:89-217` (FeedbackFormView); `feedback/models.py:5-40` (InterviewFeedback); `feedback/forms.py:6-41`

**What it actually does:** Per-round feedback form with score (0–100 validated), polished notes, raw notes. Role gate: must be interviewer, must be assignee or panel member, round must belong to the job, not after hired/rejected. One feedback per (application, round, interviewer) triple. IntegrityError fallback converts concurrent duplicates into updates. `feedback_submitted` flag set only when `round == current_round` (`feedback/views.py:195-197`). Notification to job creator on submission.

**Gaps:**
- **Panel members can submit feedback** (view-level check at `feedback/views.py:103-107`) but the **feedback list template shows "Submit Feedback" button only for `assigned_to == user`** (`feedback/templates/feedback/feedback_list.html:69-70`) — panel-only interviewers see "View Candidate" instead. Functional but UX-inconsistent.
- **IntegrityError fallback skips FeedbackEditHistory** (`feedback/views.py:182-191`) — the edit audit trail is incomplete for double-submit races.
- **Score scale confusion:** model help_text says "e.g. 8/10" (`feedback/models.py:20`); form label says "(0-100)" (`feedback/forms.py:30`); template help says "e.g. 8 out of 10" (`feedback_form.html:27`). Three different messages about the same field.
- **No structured scorecards** — just freeform score + text fields per round.
- **No test coverage for feedback views** (`feedback/tests.py:1` — placeholder only).

**Severity:** Medium — functional but scoring scale confusion and zero test coverage are risks.

### 3.9 AI Feedback Assistant (raw notes → polished bullet summary)

**Status:** Partially working

**Evidence:** `ai/services.py:170-182` (polish_notes); `feedback/views.py:243-260` (AIPolishView); `feedback/templates/feedback/feedback_form.html:36-43` (polish button)

**What it actually does:** HTMX POST endpoint sends raw_notes to Groq with SYSTEM_POLISH prompt; on failure, local fallback strips bullet prefixes and capitalizes each line. Returns plain text swapped into the notes textarea via innerHTML.

**Gaps:**
- **Groq is dead (404)** — all polish is local fallback which prepends "- " and capitalizes the first letter of each line. This is not a "summary" — it's minor formatting.
- `polish_notes` calls `.capitalize()` which lowercases the rest of the string (`ai/services.py:182`) — "MySQL Rocks" becomes "Mysql rocks".
- The 503 path in `AIPolishView` (`feedback/views.py:255-258`) is effectively unreachable because `polish_notes` always returns text for non-empty input (the local fallback always produces output).

**Severity:** Low — it works (produces text output), but the "AI" label is misleading.

### 3.10 Feedback Edit History (immutable audit log on edit)

**Status:** Working

**Evidence:** `feedback/views.py:163-174` (edit snapshot); `feedback/models.py:44-66` (FeedbackEditHistory); `feedback/views.py:229-240` (history view)

**What it actually does:** On edit, the view re-fetches the pristine `InterviewFeedback` row before the form mutates it in place (`feedback/views.py:166`), writes a `FeedbackEditHistory` snapshot with old_score/old_notes/old_raw_notes/edited_by, then saves the updated row. History view shows all revisions. Immutable: no update/delete on history rows.

**Gaps:**
- **IntegrityError fallback path skips history** (`feedback/views.py:182-191`) — the edit audit trail is incomplete.
- **No test for the history view** itself (only `FeedbackHistorySnapshotTests` at `candidates/tests.py:824-853` tests the write path).
- **Round deletion CASCADE deletes history** (`FeedbackEditHistory.feedback → CASCADE` at `feedback/models.py:48`).

**Severity:** Low — the core mechanism works; gaps are edge cases.

### 3.11 AI Panel Consensus & Conflict Resolver

**Status:** Partially working

**Evidence:** `ai/panel.py:7-206` (synthesize_panel_consensus); `candidates/models.py:185-187` (panel_consensus property); `pipeline/templates/pipeline/_panel_consensus.html`

**What it actually does:** Deterministic algorithm (NOT an LLM call despite the "AI" label): scores normalized >10 → /10; round weights 1.0/1.5/2.0; votes ≥7=Hire, ≥5=Hold, else Reject; divergence if mixed Hire+Reject or spread≥3.0; 7-state status taxonomy; keyword-bucket strengths from combined notes; per-evaluator conflict points; 5-branch HR recommendation. Cached lazily via the `panel_consensus` property.

**Gaps:**
- **Panel members have no UI to be added.** The M2M `panel_interviewers` exists, consensus works, panel members CAN submit feedback — but the only way to add a second evaluator is Django admin or shell. The feature is architecturally complete but operationally inaccessible.
- **The "agreed_strengths"** (`ai/panel.py:121-135`) are keyword ANY-matches across all notes — not actual cross-evaluator agreement. The name is misleading.
- **Score normalization ambiguity:** raw scores 1-10 are treated as already-on-10-scale (`ai/panel.py:34`). A feedback score of 8 (intended as 8/100) counts as 8/10, heavily skewing the consensus.
- **The `is_final` flag** on `InterviewRound` is not used for weighting — weights are based on `order` position only.
- **"Unanimous" wording appears even in majority (not unanimous) branches** (`ai/panel.py:170-175`).

**Severity:** High — the panel consensus engine is well-built but unreachable through the UI; scoring ambiguity corrupts results.

### 3.12 Candidate Pipeline & Kanban Board (stage moves, un-reject, remove)

**Status:** Partially working

**Evidence:** `pipeline/views.py:12-90` (PipelineMoveView); `candidates/views.py:808-822` (CandidateDeleteView); `pipeline/models.py:5-38` (PipelineMove audit)

**What it actually does:** Single HTMX endpoint (`pipeline/move/<pk>/`) handles all stage transitions. Two formats: `round:<id>` (forces status=IN_PROGRESS) and `status:<code>` (clears round). Feedback gate: `if from_round and from_round != to_round` → requires feedback on the round being left → 409. No-op guard: same round AND same status → 204 (no save). Audit: every real move writes PipelineMove. Un-reject: terminal status moves clear `current_round`; from that state, re-entry to any round has no gate (round is None). Delete: hard delete with CASCADE.

**Gaps:**
- **No Kanban board exists.** README claims "Interactive board tracking applications across stages, supporting stage moves" — the implementation is a flat table with dropdown selects, not a board. No drag-drop, no columnar layout, no per-round views.
- **Terminal status moves (hired/rejected/on_hold) bypass the feedback gate entirely** — `pipeline/views.py:59-61` never reaches the feedback check at lines 49-55. HR can hire/reject without any feedback on the final round.
- **Un-reject from rejected with no feedback works via on_hold detour** — rejected→on_hold clears round; on_hold→round re-enters without gate. The "feedback-enforced progression" is only half-true.
- **`PipelineMove` audit trail doesn't record statuses** — only `from_round`/`to_round`/`moved_by`. A status-only move logs "round→None" with no context of which terminal status was applied.
- **Candidate delete is hard delete** — CASCADE wipes applications, feedback, edit history, and PipelineMove audit trail. No soft delete, no confirmation of impact beyond a confirm dialog.

**Severity:** High — the Kanban board doesn't exist; feedback gate is bypassable; audit trail is incomplete.

### 3.13 Position Closure & Management Dashboard

**Status:** Working

**Evidence:** `jobs/views.py:86-124` (close/reopen); `accounts/views.py:49-385` (HRDashboardView — 336 lines of analytics)

**What it actually does:** Close toggles `is_active=False` + sets `closed_at`; applications are untouched. Reopen reverses. Dashboard shows: stage distribution, score distribution, apps-per-job, top positions (grouped by title), feedback status, recent activity, 4 AI insight cards (Hiring Demand, Candidate Matching, Pipeline Health, Risk Monitor), stalled candidates >7 days, pipeline velocity (avg days-in-stage). Management sees the same dashboard via redirect.

**Gaps:**
- **"Pipeline Health 70/100"** is just `(active/total)*100` — a ratio, not a health assessment. The narrative text is hardcoded, not computed from metrics.
- **Velocity uses `updated_at`** (`accounts/views.py:371-375`), not stage-entry time. Any save resets the clock.
- **Feedback completion count** (`accounts/views.py:144-156`) excludes applications without `current_round` — denominator changes silently.
- **Dashboard is 336 lines of get_context_data** — a maintainability concern.
- **Management dashboard is just a redirect to HR dashboard** (`accounts/views.py:426-432`) — no role-appropriate filtering or management-specific views.
- **No CSV/Excel export** (Sprint 2 claim, not yet built).

**Severity:** Medium — dashboard is comprehensive but metrics are sometimes misleading (velocity, health score).

### 3.14 Auto-Reject Baseline Score

**Status:** Working

**Evidence:** `jobs/models.py:30-38` (field + validators); `jobs/forms.py:55-68` (form validation); `candidates/views.py:268-285` (upload logic), `382-392` (import logic)

**What it actually does:** Job defines optional `auto_reject_score` (0-100). Form validation blocks setting a baseline without requirements (prevents mass-reject). On upload/import of a NEW application: if baseline set + status==NEW + shortlist_score < baseline → status=REJECTED. Only fires on newly created applications — re-uploads never resurrect rejected apps. Verified in tests: `candidates/tests.py:486-503`.

**Gaps:**
- **Auto-reject only works on new applications** — if baseline is set AFTER a candidate was already linked as NEW, they're not retroactively rejected. No background sweep.
- **`shortlist_score` is only set when both `job.requirements` and `candidate.skills` are non-empty** (`views.py:273`). If either is blank, score stays None and auto-reject is skipped (even if baseline is set). This is correct (can't score without requirements) but not documented.
- **Duplicate validators**: `JobForm.__init__` re-adds `MinValueValidator(0)` and `MaxValueValidator(100)` (`jobs/forms.py:43-45`) that already exist on the model field (`jobs/models.py:33`). Redundant but not harmful.

**Severity:** Low — core logic is sound and well-tested.

### 3.15 Intelligent Interviewer Selection (role-matching, availability, assign/unassign)

**Status:** Partially working

**Evidence:** `accounts/models.py:51-65` (eligibility logic); `candidates/views.py:471-640` (AssignApplicationView); `candidates/models.py:190-205` (eligible_interviewers property)

**What it actually does:** `is_eligible_interviewer_for(job)` at `accounts/models.py:51-65`: non-interviewers rejected; blank specialty or blank department → generalist (passes); else bidirectional substring containment (case-insensitive). Dropdown filtered server-side via `eligible_interviewers` property (list comprehension over all interviewers). Server re-validates on POST via same `is_eligible_interviewer_for`. Availability check: must have at least one `InterviewerAvailability` window (`has_availability()`). Reassignment reconciles inherited slot against new interviewer's windows and clashes.

**Gaps:** See Deep-Dive Section (Section 4).

**Severity:** High — see Deep-Dive.

### 3.16 Availability-Aware Scheduling (live preview, slot computation, double-booking block)

**Status:** Partially working

**Evidence:** `candidates/views.py:742-803` (InterviewerSlotsView); `candidates/models.py:207-245` (slot_preview_context); `accounts/models.py:34-49` (is_available_at); `candidates/views.py:681-698` (InterviewDetailsView scheduling checks)

**What it actually does:** Slot preview computed server-side: walks each weekly window over 14 days, 60-minute steps, skips booked times and past. Rendered as clickable buttons that fill the `interview_at` input. Scheduling validates: `is_available_at(scheduled)` + exact-time double-booking query.

**Gaps:** See Deep-Dive Section (Section 4).

**Severity:** High — see Deep-Dive.

### 3.17 Interviewer Roster Dashboard

**Status:** Working

**Evidence:** `accounts/views.py:435-489` (InterviewerRosterView); `accounts/templates/accounts/interviewer_roster.html`

**What it actually does:** HR/Management view listing every interviewer with specialty, weekly availability windows, active workload (count of assigned/panel apps excluding hired/rejected/on_hold), and pending feedback count. Dispatch-gated to HR/MGMT only.

**Gaps:**
- **N+1 query on workload** (`accounts/views.py:470-474`) — one `distinct().count()` per interviewer for the active-load dict. Fine for small teams but scales poorly.
- **Pending feedback count** (`accounts/views.py:475-485`) queries all applications with `assigned_to__isnull=False, feedback_submitted=False`, then aggregates by `assigned_to_id`. This counts ALL pending across ALL rounds, not just the current round — potentially misleading.
- **No management UI to set interviewer specialties** — specialties are editable only via Django admin or shell. The `UserAdmin` fieldsets (`accounts/admin.py:9-11`) include only `role`, not `specialty`.

**Severity:** Low — roster is functional; specialty management is admin-only.

### 3.18 Escalation Drill-Down (stalled >7 days)

**Status:** Working

**Evidence:** `accounts/views.py:318-358` (stalled logic in HRDashboardView)

**What it actually does:** Queries applications where `updated_at < now - 7 days`, excluding hired/rejected. Shows first 5 with job, idle time, assignee, status. Risk level computed: ≥3 stalled → HIGH, ≥1 → MEDIUM, else LOW. Rendered in the dashboard's escalation card.

**Gaps:**
- **`updated_at`-based stall detection** — any save resets the clock. A quick note edit restarts the 7-day timer. A true "stalled" detection would use `PipelineMove.moved_at` for the last move into the current stage.
- **No deep-link to filtered candidate list** — the escalation card shows names but clicking goes to the general candidate list, not a filtered view of stalled candidates.
- **Hard limit of 5 shown** (`views.py:330`) — more than 5 stalled candidates are hidden.

**Severity:** Medium — detection mechanism is unreliable (any save resets timer).

### 3.19 Honest Analytics (measured days-in-stage, real counts, deep-linking)

**Status:** Partially working

**Evidence:** `accounts/views.py:362-383` (velocity computation); `accounts/views.py:172-225` (AI insight cards)

**What it actually does:** Velocity is computed as the average of `(timezone.now() - updated_at).total_seconds() / 86400` for all applications in a given status. Real counts from database aggregation. Insight cards deep-link to filtered candidate lists via `?job=` and `?stage=` params.

**Gaps:**
- **"Days in current stage" is actually "days since last save"** — the comment at `views.py:362-364` says "days since its last state change (updated_at)" but the label is "avg days in current stage." These are different things.
- **"AI Detection" strings are hardcoded** (`views.py:191-192`, `219`, `275-280`, `323-327`) — not computed from data despite the "AI" label. "Strong candidate progression velocity" is the text for health_score ≥70.
- **Top-position grouping** (`views.py:122-141`) uses title matching for dedup — positions with identical titles but different departments are merged. The "Other roles" bucket in the distribution uses a count of remaining roles, not their names.

**Severity:** Medium — analytics are real data but labels are misleading.

### 3.20 Security Hardening

**Status:** Working

**Evidence:** `altrium_tracker/settings.py:21-32` (fail-closed SECRET_KEY/DEBUG); `settings.py:77-86` (axes); `settings.py:204-222` (S3 signed URLs); `settings.py:231-240` (session/upload caps); `settings.py:258-268` (prod security); Dockerfile CMD (no reseed)

**What it actually does:** Fail-closed: empty SECRET_KEY in prod raises `ImproperlyConfigured`. DEBUG defaults False. Axes lockout: 5 failures/IP/username → 1 hour. S3 config: private bucket with 600s signed URLs (when configured). Session: 8h + expire-on-close. Upload: 2MiB memory + 5MiB body. Prod: SSL redirect, HSTS, nosniff, DENY framing, same-origin referrer. Docker boot: `collectstatic + migrate + seed_users` only (no clean_and_seed_db).

**Gaps:**
- **S3 URL signing is broken in the current .env config.** `S3_PUBLIC_DOMAIN` is set to the r2.dev public domain; `custom_domain` in django-storages bypasses presigned URL generation and returns an unsigned public URL. The r2.dev bucket doesn't have public access enabled → every "View original resume" link 403s. The settings comment says "serve via short-lived signed URLs" but the config defeats this.
- **Live secrets in .env** — Groq API key + R2 access keys sit in plaintext. Gitignored but present in the working tree. If the repo was ever shared, these are exposed.
- **Duplicate security block** — `settings.py:226-229` and `settings.py:258-268` both set `SECURE_SSL_REDIRECT` and `SESSION_COOKIE_SECURE`. The second block is the complete one; the first is a subset that runs redundantly.
- **LogoutView.get() is dead code** (`accounts/views.py:30-32`) — Django 5's LogoutView sets `http_method_names = ['post', 'options']`, blocking GET before the custom `get()` method runs. The override is unreachable.
- **No CSP headers** configured.
- **No rate limiting on API endpoints** (only login via axes).

**Severity:** Critical — CV links are broken in production; secrets in working tree.

---

## 4. Interviewer Assignment & Availability Deep-Dive

### 4.1 Availability Data Model

**Definition:** `InterviewerAvailability` at `accounts/models.py:69-105`.

- **Fields:** `interviewer` (FK CASCADE, limited to role=IV), `weekday` (IntegerChoices 0-6), `start_time` (TimeField), `end_time` (TimeField).
- **Constraints:** `CheckConstraint(start_time < end_time)` at `accounts/models.py:97-102`.
- **NO `unique_together` or `UniqueConstraint`** on `(interviewer, weekday, start_time)` — overlapping or duplicate windows for the same interviewer are permitted at the DB level despite the docstring claiming they shouldn't be.
- **Weekly recurring only.** No one-off exceptions, no date-specific overrides, no timezone field.
- **No timezone field anywhere in the model chain.** All times are naive; `is_available_at()` assumes UTC.

### 4.2 "Next Free Slot" Computation

The algorithm is in **two identical copies**: `InterviewerSlotsView.get()` at `candidates/views.py:742-803` and `JobApplication.slot_preview_context` at `candidates/models.py:207-245`.

**Algorithm:**
1. Query the interviewer's `availability_windows` (all weekdays).
2. Query all `JobApplication` records where `assigned_to=interviewer` and `interview_at` is not null, excluding the current app → collect booked datetimes into a `set()`.
3. For each of the next 14 days from `now`:
   - For each window whose weekday matches that day:
     - Create a naive `datetime.combine(day_date, window.start_time)`, make aware via `timezone.make_aware(..., utc)`.
     - Step through 60-minute slots from `start` to `end - 60min`.
     - If `slot >= now` and `slot not in booked` → add to free slots.
4. Stop after collecting 6+ slots (early exit).
5. Return the first 6.

**Critical flaw: `make_aware` is called without specifying a timezone** (`candidates/views.py:777` and `models.py:231`). In Django with `USE_TZ=True`, `timezone.make_aware(naive_dt)` defaults to the current `timezone.utc` — which happens to be correct only because the system is UTC. If the server's `TIME_ZONE` setting were changed, this would silently produce wrong results. The call should explicitly pass `dt_timezone.utc`.

### 4.3 Race Condition: Check-Then-Act

**No atomicity between slot computation and booking.**

The flow is:
1. `InterviewerSlotsView.get()` computes free slots (read-only, `GET`).
2. HR picks a slot, which fills the `interview_at` input via JavaScript.
3. HR clicks "Save" → `InterviewDetailsView.post()` (a separate `POST` request).
4. At step 4, the availability check (`is_available_at`) and clash check (`filter(interview_at=scheduled).exists()`) are done within a single POST, but **not inside a `transaction.atomic()` block or with `select_for_update()`**.

**Window for race:** Two HR users viewing the same interviewer's slot preview simultaneously. User A sees slot X is free, User B sees slot X is free. Both POST to schedule. If User B's POST commits first, User A's clash check reads the DB before User B's commit → both succeed → double-booking.

**Probability:** Low in practice (single HR user typical), but architecturally unsound. The clash check at `views.py:692-695` and the availability check at `views.py:683-691` form a TOCTOU (time-of-check-time-of-use) pattern.

### 4.4 Availability Changes After Booking

**No cascade or notification.** If an interviewer modifies their availability windows (via admin or shell) after being booked:
- The existing booking remains untouched.
- The slot preview will show the new windows, but the booked slot won't be flagged as invalid.
- `InterviewerSlotsView` recomputes free slots from current windows and booked slots — the old booking correctly appears in `booked` set, so it won't be double-offered.
- However, the booked time might now fall outside the interviewer's new windows, with no warning to either HR or the interviewer.

### 4.5 Interviewer Deactivation/Offboarding

**No handling.** `InterviewerAvailability` has `on_delete=models.CASCADE` on the interviewer FK (`accounts/models.py:85-90`). Deactivating (not deleting) a user (`is_active=False`) would:
- Remove them from the `eligible_interviewers` dropdown (which filters `role='IV'` — active status not checked).
- But existing `assigned_to` FK references remain (`SET_NULL` on delete, but deactivation doesn't trigger `on_delete`).
- The interviewer's dashboard still shows assigned candidates (data is self-scoped by `assigned_to=user`, not by `is_active`).
- **Deactivated interviewers still appear in the roster** — `InterviewerRosterView` filters by `role=Role.INTERVIEWER` (`accounts/views.py:453`) without checking `is_active`.

### 4.6 Server-Side Role-Match Enforcement

**YES — enforced server-side, not just in the dropdown.**

- **Dropdown filter:** `JobApplication.eligible_interviewers` property at `candidates/models.py:190-205` filters `User.objects.filter(role='IV')` through `is_eligible_interviewer_for(job)`.
- **Server-side on POST:** `AssignApplicationView.post()` at `candidates/views.py:536-543` calls `interviewer.is_eligible_interviewer_for(app.job)` and returns an error if not eligible. The `get_object_or_404(User, pk=interviewer_id, role='IV')` at line 510 also restricts to interviewers only.
- **BUT:** `get_object_or_404(User, pk=<client_string>)` will raise `ValueError` on non-numeric input (not `Http404`). This is a 500 crash, not a 404. The same issue exists in `InterviewerSlotsView` at `views.py:762`.

### 4.7 Timezone Correctness

- **Storage:** `interview_at` is `DateTimeField(null=True)` with `USE_TZ=True` → stored as UTC in the database.
- **is_available_at:** `accounts/models.py:34-49` converts aware inputs to UTC, then compares `.weekday()` and `.time()` against the window. Since windows are stored as `TimeField` (no timezone), and all datetimes are UTC, this works correctly — **but only because the system runs in UTC.** If the system timezone or interviewer's local time differs, the half-open interval comparison (`start_time <= when.time() < end_time`) operates on the UTC time, not the interviewer's local time.
- **Slot preview:** `make_aware` defaults to UTC (`views.py:777`). Again correct only because `TIME_ZONE='UTC'` in settings.
- **Flash messages** (`views.py:707-708`) always say "UTC" regardless of actual timezone context — misleading if a future change makes the system non-UTC.
- **`datetime.fromisoformat`** at `views.py:664` accepts date-only strings (e.g., `2026-09-10`) which parse as midnight — books a midnight interview with no warning.

### 4.8 Unassign: History Preservation

**Partial — data is cleared, not preserved.**

- `AssignApplicationView.post()` at `candidates/views.py:489-501`: unassign sets `assigned_to=None` and `interview_at=None`. A `Notification` is created for the former assignee. The `panel_interviewers.remove(previous)` at line 489 removes them from the panel.
- **What's preserved:** The `PipelineMove` audit trail (if any moves happened), `InterviewFeedback` records (not deleted by unassign), and the `Notification` record documenting the unassignment.
- **What's lost:** The specific `interview_at` value (cleared to None), `interview_details` (NOT cleared — the meeting link stays), and panel membership. There is no "unassignment log" beyond the notification — the only way to know an interviewer was previously assigned is to check the notification text.
- **Feedback submissions from the unassigned interviewer are retained** — they remain in `InterviewFeedback` with the interviewer FK intact. The `PanelConsensus` engine can still see them.

### 4.9 UI Hides Options the Server Would Accept

**Yes — one confirmed case:**

- **UI:** The `eligible_interviewers` dropdown (`pipeline/_app_row.html:59-69`) only shows interviewers passing `is_eligible_interviewer_for(job)`. Non-matching specialists and non-interviewers are hidden.
- **Server:** `AssignApplicationView.post()` at `candidates/views.py:510` does `get_object_or_404(User, pk=interviewer_id, role='IV')` — it restricts to IV role but does NOT re-validate eligibility beyond `is_eligible_interviewer_for` at line 536. So the server DOES re-check eligibility.
- **However:** The `__unassign__` sentinel is accepted without any checks — any HR user can unassign any candidate regardless of the interviewer's state. This is correct behavior.
- **InterviewDetailsView** (`candidates/views.py:681-683`) skips availability checks entirely when no interviewer is assigned — HR can schedule any time for an unassigned candidate. The UI doesn't prevent this (the schedule input is always visible).

---

## 5. RBAC Audit

### Server-Side Permission Checks by Endpoint

| Endpoint | Check Location | Method | Blocks |
|----------|---------------|--------|--------|
| LoginView | Django default | form | Public |
| LogoutView | Django default | POST | Public |
| HomeView | views.py:40-46 | dispatch | Unauthenticated → login |
| HRDashboardView | views.py:58-59 | dispatch | Non-HR/MGMT → redirect home |
| InterviewerDashboardView | **NONE** | - | **Any role can access** |
| ManagementDashboardView | Django default | RedirectView | Login only |
| InterviewerRosterView | views.py:447-448 | dispatch | Non-HR/MGMT → redirect home |
| JobListView | LoginRequiredMixin | - | Login |
| JobCreateView | views.py:54-55 | dispatch | Non-HR → redirect list |
| JobDetailView | LoginRequiredMixin | - | Login |
| JobEditView | views.py:72-73 | dispatch | Non-HR → redirect list |
| JobCloseView | views.py:91-93 | post | Non-HR → error + redirect |
| JobReopenView | views.py:113-115 | post | Non-HR → error + redirect |
| RoundCreateView | views.py:154-155 | dispatch | Non-HR → redirect list |
| RoundDeleteView | views.py:183-184 | dispatch | Non-HR → redirect list |
| CandidateListView | LoginRequiredMixin | - | Login |
| CandidateUploadView | views.py:165 | dispatch | Non-HR → redirect list |
| CandidateImportView | views.py:323 | dispatch | Non-HR → redirect list |
| CandidateDetailView | views.py:124-133 | dispatch | Interviewer not assigned → 403 |
| CandidateDeleteView | views.py:813-815 | post | Non-HR → 403/redirect |
| ScoreUpdateView | views.py:445-449 | post | MGMT → 403; non-HR → redirect |
| AiFitSummaryView | views.py:415-421 | post | MGMT → 403; non-HR/IV → 403; IV not assigned → 403 |
| AssignApplicationView | views.py:476-479 | post | MGMT → 403; non-HR → redirect |
| InterviewDetailsView | views.py:649-651 | post | MGMT → 403; non-HR → redirect |
| InterviewerSlotsView | views.py:755-756 | get | Non-HR → 403 |
| PipelineMoveView | views.py:20-22 | post | Non-HR → 403 |
| FeedbackListView | LoginRequiredMixin | - | Login |
| FeedbackFormView | views.py:97-119 | dispatch | Non-IV → redirect; IV not assigned/panel → 403; wrong job → 403; hired/rejected → 403 |
| FeedbackDetailView | LoginRequiredMixin | - | Login (scoped queryset) |
| FeedbackHistoryView | LoginRequiredMixin | - | Login (scoped queryset) |
| AIPolishView | views.py:247-248 | post | Non-IV → 403 |
| NotificationListView | LoginRequiredMixin | - | Login (recipient-scoped) |
| UnreadCountView | LoginRequiredMixin | - | Login (recipient-scoped) |
| MarkReadView | LoginRequiredMixin | - | Login (recipient-scoped) |
| MarkAllReadView | LoginRequiredMixin | - | Login (recipient-scoped) |

### Summary of RBAC Gaps

1. **`InterviewerDashboardView` has no role gate** (`accounts/views.py:388-423`) — HR/Management can render it. Data is self-scoped (empty for non-interviewers) so no data leak, but it's a UI inconsistency.
2. **`InterviewerDashboardView` is the only view without a role dispatch check** — every other view with role restrictions has them.
3. **All checks are server-side** (dispatch/post methods) — template-level gating is defense-in-depth only, not the security boundary.

---

## 6. Data Integrity Audit

### Missing Constraints / Indexes

1. **`InterviewerAvailability` has no unique constraint on `(interviewer, weekday, start_time)`** (`accounts/models.py:95-102`) — overlapping/duplicate windows are permitted at DB level. Only `CheckConstraint(start_time < end_time)`.
2. **`Candidate.email` is `unique=True, null=True`** (`candidates/models.py:10`) — SQLite/PostgreSQL allow multiple NULL values (unique constraint doesn't apply to NULLs), so multiple `email=None` candidates can exist. This is intentional (candidates without email bypass dedup) but should be documented.
3. **`InterviewRound` has `UniqueConstraint(fields=['job', 'name'])`** (`jobs/models.py:71-76`) — correct, but the form doesn't call `validate_unique()` → crashes with `IntegrityError` instead of showing a form error.
4. **No index on `JobApplication.assigned_to`** — queried in `InterviewDetailsView` clash check, roster workload, and interviewer dashboard. Missing index causes sequential scans on large datasets.
5. **No index on `JobApplication.interview_at`** — queried in slot computation and clash checks.

### Cascade Delete Behavior

| Parent | Child | on_delete | Effect |
|--------|-------|-----------|--------|
| Candidate | JobApplication | CASCADE | Delete candidate → all applications gone |
| Job | JobApplication | CASCADE | Delete job → all applications gone |
| Job | InterviewRound | CASCADE | Delete job → all rounds gone |
| InterviewRound | InterviewFeedback | CASCADE | **Delete round → all feedback + edit history for that round GONE** |
| JobApplication | InterviewFeedback | CASCADE | Delete application → all feedback gone |
| InterviewFeedback | FeedbackEditHistory | CASCADE | Delete feedback → all edit history gone |
| JobApplication | PipelineMove | CASCADE | Delete application → all audit trail gone |
| InterviewRound | PipelineMove (from_round) | SET_NULL | Delete round → null ref, row kept |
| InterviewRound | PipelineMove (to_round) | SET_NULL | Delete round → null ref, row kept |
| InterviewerAvailability | (user) | CASCADE | Delete user → all availability gone |
| User | Notification | CASCADE | Delete user → all notifications gone |

**Critical:** Round deletion (`jobs/views.py:189`) destroys feedback and audit trail via cascading CASCADEs. This is the most dangerous cascade in the system.

### Migration / Model Drift

- All migrations are applied (`[X]` on every migration in `showmigrations`).
- **`auto_reject_score` was removed (0005) and re-added (0006-0007)** — the field exists but the migration chain is noisy. No drift.
- **Data migration 0009** fixed invalid `status='interview'` values written by early seeds → mapped to `'in_progress'`. No reverse migration (intentional).
- **No pending migrations** (`migrate --check` would pass).

---

## 7. Test Coverage Audit

### Summary

| App | Test File | Lines | Classes | Methods | Coverage Focus |
|-----|-----------|-------|---------|---------|----------------|
| accounts | accounts/tests.py | 78 | 3 | 8 | Login, role helpers, home redirect |
| jobs | jobs/tests.py | 127 | 3 | 10 | Create, rounds, close |
| candidates | candidates/tests.py | 959 | 19 | 55+ | Visibility, scoring, assignment, upload, import, search, RBAC, auto-reject, slot preview, unassign, matcher, reassignment |
| pipeline | pipeline/tests.py | 131 | 1 | 9 | Moves, feedback gate, audit, delete resilience |
| feedback | feedback/tests.py | 1 | 0 | 0 | **EMPTY — zero feedback tests** |
| notifications | notifications/tests.py | 62 | 1 | 5 | Unread count, mark read, cross-user |
| ai | ai/tests.py | 70 | 1 | 8 | Groq mock tests, fallback, polish |
| **Total** | | **1428** | **28** | **95+** | |

### What's Actually Tested

**Well-tested:**
- Assignment flow: specialty match, availability gate, unassign, notification, reassignment slot reconciliation (4 tests at `candidates/tests.py:879-959`)
- Auto-reject: below baseline, at baseline, no baseline, no requirements, re-upload non-resurrection (`candidates/tests.py:422-503`)
- Upload: creation, dedup, unsupported extension, binary file, missing job/files, HR-only (`candidates/tests.py:194-277`)
- RBAC: interviewer visibility, score block, management block, pipeline move block, assign block (`candidates/tests.py:382-420`, `pipeline/tests.py:81-89`)
- Feedback gate: 409 when moving without feedback (`pipeline/tests.py:124-131`)
- Matcher: whole-word regex, exact match, multi-word (`candidates/tests.py:747-771`)
- Reconciliation: inherited slot cleared/kept based on new interviewer's windows; clash detection (`candidates/tests.py:879-959`)

**NOT tested (critical gaps):**
1. **All feedback views** (`feedback/tests.py:1` — placeholder) — form submission, edit, history, AI polish, role gating, panel member submission, IntegrityError path.
2. **InterviewDetailsView** — scheduling validation, availability check, double-booking, fromisoformat parsing. The existing test `test_scheduling_accepts_slot_inside_window` (`candidates/tests.py:592`) never assigns an interviewer, so the availability check at `views.py:682-683` is skipped entirely — the test passes trivially.
3. **InterviewerDashboardView** role access (no role gate = any role renders it).
4. **Duplicate round name** crash (`jobs/tests.py:93-100` catches `IntegrityError` but doesn't test the view's response).
5. **Dashboard analytics** — velocity computation, stalled detection, AI insight cards.
6. **Concurrent scheduling** — no test for the TOCTOU race between slot computation and booking.
7. **Management commands** — `clean_and_seed_db`, `seed_users`, `seed_testdata` have no tests.
8. **Notifications integration** — assignment notification content, schedule notification, unassign notification.

---

## 8. Technical Debt

### Grepped Patterns

**TODO/FIXME/HACK:** None found in any `.py` file. The codebase is clean of explicit markers.

**`pass` statements:**
- `ai/tests.py:13` — `raise_for_status(self): pass` in mock (intentional)
- `candidates/migrations/0009_fix_interview_status.py:18` — reverse migration stub (intentional)

**Broad exception catches:**
- `ai/cv_parser.py:19` — `except Exception: return ''` (decode fallback)
- `ai/cv_parser.py:27` — `except Exception as exc: ... return ''` (PDF failure)
- `ai/cv_parser.py:43` — `except Exception as exc: ... return ''` (DOCX failure)
- `ai/services.py:81` — `except Exception as exc: ... return ''` (Groq failure — intentional graceful degradation)
- `candidates/views.py:89` — `except Exception: self.kwargs['page'] = 'last'` (pagination fallback — swallows genuine paginator bugs too)
- `candidates/views.py:221` — `except Exception: failed.append(...)` (CV parse failure — reported in flash)
- `accounts/management/commands/checkdb.py:21` — `except Exception as exc: raise CommandError(...)` (re-raises correctly)

**Hardcoded credentials:**
- `testpass123` in `clean_and_seed_db.py:65-72` and `seed_users.py:19` — demo accounts, intentional.
- `testpass123` in login quick-fill buttons (`login.html:25-29`) — gated by `{% if debug %}`, hidden in prod.
- R2 access keys and Groq key in `.env` (gitignored but present in working tree).
- `compose.yaml:19-21` — Postgres password `altrium_pass` (dev only).

**Orphan code:**
- `LogoutView.get()` at `accounts/views.py:30-32` — unreachable due to Django 5's `http_method_names` override.
- `auto_apply()` docstring at `ai/matching.py:73` says "store it on the application" but the function returns a score and writes nothing.
- `ai/matching.py:66` — dead variable `haystack` computed but never used.
- `ai/apps.py` — the `ai` app has an `apps.py` and migrations but is never registered in `INSTALLED_APPS`.
- Unused import: `from django.contrib.auth import get_user_model` at `pipeline/views.py:85-86`.

**Other technical debt:**
- Duplicate security block in `settings.py:226-229` vs `258-268`.
- `REDIS_URL` evaluated twice (`settings.py:243` and `247`).
- Duplicate validators: `JobForm.__init__` re-adds `MinValueValidator(0)` and `MaxValueValidator(100)` already on the model.
- Free-slot algorithm duplicated between `InterviewerSlotsView` (`views.py:777-792`) and `JobApplication.slot_preview_context` (`models.py:226-238`).
- Score scale ambiguity: model help_text says 8/10, form says 0-100, template says 8 out of 10.
- Two different skill-matching implementations: regex-based (`ai/matching.py`) vs list-membership (`ai/services.py:200-201`).

---

## 9. Sprint 2 Readiness Check

### 9.1 AI Rejection Email Dispatch

**Existing foundations:** `JobApplication` has `status` field with REJECTED choice. `Notification` model exists for in-app notifications. `Candidate` has `email` field. `Job` has `title`. Flash messages exist for HR feedback.

**Missing:**
- No email sending infrastructure configured (no `EMAIL_BACKEND` in settings, no SMTP config).
- No email templates.
- No management command or cron job to trigger sends.
- No `django.core.mail` import anywhere in the codebase.
- No `celery` or any task queue installed.
- **Recommendation:** Add `django.core.mail` backend + email templates + trigger on status change in `PipelineMoveView`.

### 9.2 CSV/Excel Pipeline Export

**Existing foundations:** `JobApplication` queryset infrastructure (`visible_applications` at `candidates/views.py:28-39`). All data fields exist on models.

**Missing:**
- No export library installed (`openpyxl`, `xlsxwriter`, `csv` module usage).
- No export view or endpoint.
- No report generation logic.
- **Recommendation:** Add a simple CSV export using `django.http.HttpResponse` with `csv` module (stdlib). No new dependencies needed for CSV; `openpyxl` for Excel.

### 9.3 Automated Feedback Reminders

**Existing foundations:** `feedback_submitted` flag on `JobApplication`. `current_round` tracks pending work. `Notification` model exists.

**Missing:**
- No cron/scheduler infrastructure (no `celery`, no `django-celery-beat`, no `apscheduler`, no `croniter` runtime — only `types-croniter` type stubs).
- No email sending (same as 9.1).
- No reminder template.
- No management command to find overdue feedback.
- **Recommendation:** Add a management command `send_feedback_reminders` + cron it via Render's cron or external scheduler. Or install `django-celery-beat`.

### 9.4 Automated 7-Day SLA Escalation Dispatcher

**Existing foundations:** Stalled candidate detection already exists at `accounts/views.py:318-328` (queries `updated_at < now - 7 days`). `Notification` model exists. Dashboard escalation card shows stalled candidates.

**Missing:**
- No automated dispatch — the escalation is purely visual (dashboard card).
- No email/Slack integration.
- No per-candidate escalation state tracking (just a query on `updated_at`).
- **Recommendation:** Add a management command `dispatch_escalations` that sends notifications (and optionally emails) for stalled candidates. Can reuse the existing query from the dashboard.

### 9.5 Talent Pool Re-Matching Engine

**Existing foundations:** `JobApplication.shortlist_score` (per-job auto-match score). `Candidate` model with skills. `ai.matching.compute_score`. `Job.requirements`. `Job.is_active` + `closed_at`.

**Missing:**
- No cross-job candidate search (all queries are job-scoped).
- No "silver medalist" concept in the data model (no hired/not-hired distinction in the way needed — need to find past candidates who scored ≥80 but weren't hired for ANY job).
- No automatic surfacing mechanism.
- No UI for re-engagement.
- **Recommendation:** Query `JobApplication.objects.filter(shortlist_score__gte=80).exclude(status='hired')` grouped by candidate. Build a view + template. This is a pure data query + UI feature — no new infrastructure needed.

---

## 10. Top 10 Critical Risks

1. **S3/CV link breakage** (Section 3.20) — Every "View original resume" link 403s in the current config because `custom_domain` bypasses presigned URL generation. CVs are stored but unrecoverable through the UI.

2. **Duplicate round name = 500 crash** (Section 3.2) — `RoundForm` doesn't call `validate_unique()`. Any HR user creating a round with a duplicate name triggers an unhandled `IntegrityError` → HTTP 500 with full traceback.

3. **Round deletion destroys audit trail** (Section 3.2/6) — `InterviewFeedback.round` is `CASCADE`; deleting a round silently wipes all feedback scores, notes, edit history, and the implicit audit trail. The README claims "full data retention."

4. **Assignment scheduling bypasses all constraints when unassigned** (Section 3.7/4) — `InterviewDetailsView` skips availability + double-booking checks when `assigned_to` is null. HR can schedule any time for an unassigned candidate, creating a slot that can't be validated later.

5. **TOCTOU race in slot booking** (Section 4.3) — Slot computation (`GET`) and booking (`POST`) are separate requests with no `select_for_update()` or `transaction.atomic()`. Two HR users can double-book the same interviewer at the same time.

6. **Panel consensus unreachable through UI** (Section 3.11) — The M2M `panel_interviewers` has no management interface. Multi-evaluator consensus requires Django admin or shell access. The feature is architecturally complete but operationally unusable.

7. **Score scale ambiguity corrupts panel consensus** (Section 3.8/3.11) — Model help_text says "8/10", form says "0-100", template says "8 out of 10". `panel.py:34` treats scores ≤10 as already-on-10-scale. A feedback score of 8 (meant as 8/100) is weighted as 8/10 — massively skewing consensus.

8. **No Kanban board exists** (Section 3.12) — README claims "Interactive board tracking applications across stages, supporting stage moves." The implementation is a flat table with dropdown selects. No columnar layout, no drag-drop, no per-round views.

9. **Feedback views have zero test coverage** (Section 7) — `feedback/tests.py` is a placeholder. The entire feedback lifecycle (submit, edit, history, AI polish, panel member access, IntegrityError race, role gating) is untested. Any regression in this area is invisible to the test suite.

10. **Interviewer deactivation leaves stale assignments** (Section 4.5) — Deactivated interviewers retain `assigned_to` references, still appear in the roster, and their assigned candidates remain in limbo. No offboarding workflow exists.
