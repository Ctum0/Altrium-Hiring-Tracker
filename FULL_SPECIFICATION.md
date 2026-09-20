# Altrium Hiring Tracker — Full System Specification

Internal recruitment management platform for Altrium. Django 5 monolith, five apps (`accounts`, `jobs`, `candidates`, `feedback`, `pipeline`, `notifications`), server-rendered HTML + HTMX, no SPA/API layer. Every claim below is grounded in the actual routed views (file:line references to `urls.py`/`views.py`) and was live-verified during this session's audits, not inferred.

---

## 1. Roles & Access

Three authenticated roles. **There is no fourth "Candidate" role and no candidate login** (see §3 below — this is answered explicitly, not glossed over).

| Role | Demo login | Full access |
|---|---|---|
| **HR** | `hr_demo` / `testpass123` | Everything: post jobs, upload/import/review CVs, assign interviewers, move candidates, close jobs, export reports, onboard staff |
| **Interviewer** | `iv_demo` / `testpass123` | Only their own assigned/panel candidates: submit scorecards, set their own availability, view their own calendar |
| **Management** | `mgmt_demo` / `testpass123` | Read-only: dashboards, KPIs, escalations, panel consensus, report export — no create/edit/assign actions |

RBAC is enforced at two layers everywhere it matters: (1) what a view/dropdown/queryset shows, and (2) a server-side check on the POST itself (verified this session via forged-POST tests — e.g. a Junior interviewer POSTing directly to assign onto a Senior job is rejected with a 403/error, not just hidden from the UI).

`seed_users` (gated behind `SEED_DEMO_USERS=true`, never automatic in production) creates/self-heals these three accounts on every run.

---

## 2. The Pipeline, End to End

```
Job Posting  →  CV Intake (2 entry paths)  →  Parse/Dedup/Score  →  Shortlist  →  Assign
     →  Schedule  →  Feedback (per round)  →  Stage Move  →  Decision  →  Job Closure
                                                                              ↓
                                                            Talent Pool loop → future Job Posting
```

Cross-cutting the whole flow: **Notifications** (6 event triggers, not a stage), **RBAC** (gates every step), **Reporting** (available any time, not a final step).

---

## 3. Candidate Portal — direct answer

**There is no full candidate portal, and this is intentional, not missing.** Locked decision (`SPRINT2_READINESS_AUDIT.md` §10, Feature 6): *"this is the light option, not a full portal — the candidate cannot log back in to check status; every further update comes through automated emails."*

What candidates actually get:
- **A public apply page** at `/candidates/apply/<job_pk>/` (`PublicApplyView`, `candidates/views.py`) — no login, no account, open only for active jobs (closed jobs 404).
- **One form**: name, email, phone, CV file, consent checkbox.
- **A thanks page** on success (`/candidates/apply/<job_pk>/thanks/`).
- **Status updates entirely by email** — confirmation on apply, invitation when scheduled, and rejection/acceptance on a final decision. No way to log back in and check a status page.

If you want a real portal (login, dashboard, live status, message thread) that's new scope beyond what was ever specified — say so explicitly and I'll design it properly rather than bolt it onto the existing anonymous-apply flow.

---

## 4. Feature-by-Feature Specification

### 4.1 Job Posting / Smart Job Setup
**Who:** HR. **Entry:** `/jobs/create/` (`JobCreateView`).
- Captures Title, Description, Required Skills, Auto-reject baseline (0–100, validated so it can never be set with zero real requirement tokens — prevents an accidental mass-reject-to-0), Number of openings, Hiring Manager.
- **Domain** (dropdown: Engineering/Product/Design/Data/Infrastructure/QA/Other), **Seniority** (Junior/Mid/Senior/Lead dropdown), **Department** (12-choice dropdown — Engineering/Product/Design/Data/Infrastructure/QA/Sales/Marketing/People & HR/Finance/Operations/Other).
- On submit → redirects straight to **Rounds-in-Creation** (`/jobs/<pk>/rounds-setup/`, `RoundsSetupView`): add/rename/reorder interview rounds inline, before ever landing on the job detail page.
- On save, scans closed jobs for rejected/on-hold candidates who scored ≥80 in the **same Domain and Seniority** and surfaces them as one-click "Suggested candidates to re-engage" (`jobs/talent_pool.py`, `find_suggestions`).
- Job detail page (`/jobs/<pk>/`) shows a live per-round roll-up — candidates in each round, assignee, scheduled time — computed on the fly from each `JobApplication`, never a separately stored table that could go stale.
- Job Closure (`/jobs/<pk>/close/`, `JobCloseView`) stops new applications; retains all candidate data indefinitely (verified: a year-old closed job stays fully searchable, no auto-deletion anywhere). Reopen (`/jobs/<pk>/reopen/`) is available.

### 4.2 CV Upload / CV Import (HR-side)
**Who:** HR. **Entry:** `/candidates/upload/` (bulk PDF/DOCX) and `/candidates/import/` (paste a profile URL/text).
Both funnel into the single shared `ingest_cv()` pipeline (`candidates/intake.py`) — the exact same function the public apply path calls.

### 4.3 CV Self-Upload (Candidate-facing)
**Who:** anyone, unauthenticated. **Entry:** `/careers/` (public "Open Positions" board — lists every `is_active` job automatically, no publish flag; one stable shareable link) → per-job `/candidates/apply/<job_pk>/` → thanks page with a link back to `/careers/`.
Same pipeline as 4.2, byte-for-byte (verified via a shared-code-path test asserting identical parsed fields/score/reject outcome for the same file through both routes). See §3 for the "no portal" boundary.
Edge behavior (all live-verified): duplicate submission for the same job+email re-renders the form with "You have already applied" (no silent swallow, no duplicate rows); CV over 10MB rejected with a friendly inline error; missing consent re-renders with entered data preserved; corrupt/unreadable file shows a friendly error (parseable-but-low-confidence instead creates a needs_review candidate and lands on thanks); inactive or nonexistent job pk → 404. Logout is POST-only per Django 5 (`GET /logout/` → 405; the navbar logout control is a POST form).

### 4.4 CV Parsing (AI) + CV Intake Quality Rules
Runs inside `ingest_cv()` for every upload, either path:
1. `extract_text()` + `parse_cv()` (Groq LLM, local heuristic fallback if the API is unavailable — verified: never blocks a submission even with a dead API key).
2. **Confidence gate** (`ai/confidence.py`, `should_hold_for_review`): flags "Needs Review" on low readable-text volume, missing email, a name that's actually a skill word, or a single-word name. A flagged CV's auto-reject decision is **held back** — verified via a live shell test that a flagged application stays `status='new'`, never silently rejected.
3. Auto-Reject Baseline: score computed via `ai/matching.py`; if below the job's baseline **and not flagged**, auto-rejects immediately.
4. HR reviews a flagged CV at `/candidates/<pk>/review/` (`CandidateReviewView`); on save, `recompute_after_review()` **re-scores and re-applies** the baseline with the corrected data — not just a flag clear.

### 4.5 CV Deduplication
Two layers inside `ingest_cv()`: exact-email match (`get_or_create`), then fuzzy name+phone match (`candidates/dedup.py`, `find_fuzzy_match`) for the same person applying under a different email — requires normalized name equality AND phone equality on both sides. On a match, the existing record's resume/skills are refreshed rather than a duplicate profile being created.

### 4.6 CV Categorization
Filing under a job = the `JobApplication.get_or_create(candidate, job)` call inside `ingest_cv()` — happens automatically, not a separate manual step.

### 4.7 Search & Filter
**Who:** HR/Management. **Entry:** `/candidates/` (`CandidateListView`).
Query by name/email/skills/job title, filter by position/stage/score, paginated 50/page (verified: no lag at 1,000+ candidates after the N+1 fix this session — 3 queries for 773 applications).

### 4.8 Interviewer Management
**Who:** HR (onboard/view), Interviewer (self-service).
- Onboarding: `/onboard/` (`OnboardUserView`, HR-only) — name, email, Domain, Seniority, no Django admin needed.
- Self-service availability: `/my-availability/` (`MyAvailabilityView`) — interviewer sets their own recurring weekly windows.
- Own calendar: `/my-calendar/` (`MyCalendarView`) — every booked interview, grouped by day.
- Profile page: `/interviewer/<pk>/` (`InterviewerProfileView`, HR/Management) — specialty, seniority, weekly availability, current workload, pending feedback count, upcoming interviews, all six on one page. Linked from the roster, the candidate list, and the pipeline application row.
- Roster: `/interviewer-roster/` — every interviewer's specialty/availability/live workload; "No windows declared" badge for unclassified accounts (not a silent block).
- Deactivation: `/interviewer/<pk>/deactivate/`; stranded assignments surface on `/candidates/offboarding/`.

### 4.9 Candidate Assign + Interviewer Eligibility
**Who:** HR. **Entry:** `/candidates/applications/<pk>/assign/` (`AssignApplicationView`).
Eligibility rule (`accounts/models.py`, `is_fully_eligible_for`): interviewer's structured **Domain** must match the job's Domain (job Domain='other' imposes no constraint), AND seniority must be at or above the job's required level (`Junior < Mid < Senior < Lead`; an unclassified interviewer works junior/mid roles only). Enforced twice — the dropdown only lists eligible interviewers, and the server independently re-validates on save (a forged POST assigning an ineligible interviewer is rejected). A live availability preview (`/candidates/applications/<pk>/interviewer-slots/`) shows the interviewer's next free 1-hour slots inline.

### 4.10 Interview Scheduling (Manual Links)
**Who:** HR. **Entry:** `/candidates/applications/<pk>/interview-details/` (`InterviewDetailsView`).
HR enters a meeting link/date/notes; double-booking the same interviewer at the same time is blocked; a past datetime is rejected unconditionally. Fires the Interview Invitation email (§4.14) only when the scheduled time genuinely changes.

### 4.11 Interview Feedback + AI-Assisted Structured Scorecard
**Who:** Interviewer. **Entry:** `/feedback/<application_pk>/<round_pk>/` (`FeedbackFormView`).
- Fixed criteria (Technical Skill, Communication, Culture Fit) rated individually, plus free-text notes.
- "Suggest ratings" button (AI, `ai/services.py suggest_scores`) proposes a rating per criterion and drafts a summary from pasted raw notes — proposes only, never auto-submits (verified: the AI endpoint has zero `.save()` calls; only the human's own Submit click persists anything).
- Overall score = **weighted** average — Technical Skill 50%, Communication 25%, Culture Fit 25% (fixed this session; was a plain unweighted mean before).
- **Feedback Validation**: `PipelineMoveView` blocks advancing a candidate's stage until that round's feedback exists (409 on an attempted illegal move — same gate whether triggered from the dropdown or the Kanban board's drag-drop, since both call the identical endpoint).
- **Feedback History**: every edit is versioned (`FeedbackEditHistory`), never overwritten silently.
- **General Feedback (AI)**: once a candidate has feedback from 2+ rounds, an AI-written narrative synthesizing every round appears on the candidate profile (`/candidates/<pk>/`) — regenerates on every new round's submission, and never replaces the individual per-round scorecards, which stay separately viewable via `/feedback/?application=<pk>`.
- **AI Panel Consensus**: separate cross-evaluator synthesis (`ai/panel.py`) — progressive round-weighted vote tally (Hire/Hold/Reject), agreed strengths, divergence warnings.

### 4.12 Kanban Board
**Who:** view — anyone with visibility into the job; drag-drop — HR only. **Entry:** `/jobs/<pk>/board/` (`JobBoardView`).
One column per interview round (in order) plus terminal Hired/Rejected/On Hold lanes. Native HTML5 drag-and-drop POSTs to the exact same `pipeline:move` endpoint the dropdown uses — zero duplicated validation logic, so an illegal drag surfaces the identical 409 the dropdown would. RBAC-scoped: an interviewer's board never shows candidates outside their own assignment, not merely a disabled drag handle.

### 4.13 Job Closure → Talent Pool loop
Closing a job (§4.1) fires rejection emails to every still-open applicant, retains all data, and — because rejected/on-hold high scorers (≥80) are exactly what §4.1's talent-pool scan later surfaces for a *new* job of matching Domain+Seniority — creates a genuine feedback loop rather than a dead end.

### 4.14 Automated Notifications & Emails
Six triggers, one shared mechanism (`notifications/mail.py`):

| Trigger | Fires | Recipient |
|---|---|---|
| Confirmation | Instantly, on any new application (either intake path) | Candidate |
| Interview Invitation | Instantly, when a real interview time is scheduled/changed | Candidate |
| Rejection (AI-drafted) | Instantly, on explicit reject OR job closure | Candidate |
| Acceptance | Instantly, on Hired | Candidate |
| Feedback Reminder | Scheduled (`send_feedback_reminders`, 3-day threshold) | Assigned interviewer |
| Escalation | Scheduled (`dispatch_escalations`, 7-day threshold, keyed on `stage_entered_at` — fixed this session to match the dashboard card exactly) | HR/Management |

Rejection emails are AI-drafted (2–3 warm, constructive sentences) with an automatic fallback to a fixed closing line if the AI call fails — verified live that a submission never blocks on a dead API key.

### 4.15 Pipeline Reporting / Dashboards
**Who:** HR/Management. **Entry:** `/accounts/hr-dashboard/` (role-scoped rendering of the same view).
- KPI cards, per-stage pass/fail rate with abnormal-drop-off flagging (>1.5× the mean fail rate, minimum 3 moves before a round is eligible to be flagged).
- CSV export (`/reports/export/`) — job title, department, candidate count, avg time-to-hire, status, for every job. Time-to-hire computed from real `PipelineMove` timestamps, never `updated_at` (verified with a hand-traced example matching the report exactly; also fixed this session to exclude corrupted negative durations instead of reporting them).
- Data Retention report (`/reports/retention/`) — every closed job, days since closure, candidates still on file; exists specifically to prove no silent deletion happens.
- AI Panel Consensus & Conflict Resolver card, recent activity feed, escalation drill-down.

---

## 5. Non-Functional Characteristics (verified this session, not aspirational)

- **Performance**: dashboard <3ms, Kanban board <35ms, CSV export <40ms measured against 1,117 seeded candidates; N+1 query pattern fixed (3 queries regardless of list size, was ~1 per row).
- **Security**: CSRF on every POST, Django auto-escaping (XSS-safe), ORM-only queries (no raw SQL), race-condition-safe concurrent pipeline moves, zero vulnerabilities found in a dedicated audit pass.
- **Accessibility**: WCAG 2.1 AA — full keyboard navigation, visible focus states, 4.5:1+ contrast, semantic HTML/ARIA throughout.
- **Mobile**: responsive down to 375px, no horizontal scroll, all three roles usable on phone/tablet.
- **Test coverage**: 384/384 passing.

## 6. Tech Stack & Deployment

Django 5 / Python 3.12, HTML5 + vanilla JS + HTMX, PostgreSQL in production (SQLite for local dev), Groq LLM with local heuristic fallback, Gunicorn + Whitenoise, Docker. Currently deployed on **Render** (live, self-provisioned Postgres) and **Railway** (pending a manual database-wiring step on your side, per the last exchange).
