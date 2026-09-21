# Executive Product Audit — Altrium Hiring Tracker

Method: 5-agent parallel swarm (security, performance, feature-gaps, UX/UI consistency, chaos) + 3 live persona flows (first-time HR, interviewer 30-min crunch, management 30-second check). All findings evidence-grounded (URL, role, probe output, file:line). Full agent reports: `/tmp/sec_audit_out.txt`, `/tmp/sec_summary.txt`, `/tmp/perf_audit_report.md`, `/tmp/uxui_audit_report.md`, GapHunter/ChaosProbe payloads in agent transcripts.

---

## 1. SaaS Readiness Score

| Dimension | Score | Basis |
|---|---|---|
| Workflow completeness | **7/10** | Core loop (job→intake→assign→feedback→move→decision) is complete and feedback-gated. Broken: candidate edit is a 500 (dead feature); no post-hire flow; reminders/escalations exist in code but no scheduler runs them in this deployment |
| UX maturity | **6/10** | Strong empty states and confirm patterns; undermined by 143-control candidate list (P0), missing h1 on 2 pages, undefined badge classes, two confirm paradigms |
| Automation maturity | **6/10** | AI parse/score/polish/consensus all present with circuit breaker; but automation is invisible (no email log), no feedback-complete nudge, no bulk operations, scheduler dormant locally |
| Reliability | **9/10** | Zero 500s in chaos probes; double-submit/races/malformed input all handled; unique constraints held under 6-way races |
| Security | **7/10** | Zero privilege-escalation or IDOR found in full role-matrix probe; solid session/lockout config. Critical: media/ CVs served unauthenticated under DEBUG=True |
| Performance | **7/10** | Steady-state latency healthy (10–40ms); query-count scaling is the risk (candidate detail 14→38 queries for 1→2 apps; export 32 queries) |
| **Overall** | **7.0/10** | Working internal tool → needs the P0/P1 list below to be sellable SaaS |

---

## 2. Top 15 Highest-Impact Improvements

| # | Problem | Role | Current | Fix | Difficulty | Impact |
|---|---|---|---|---|---|---|
| 1 | **Candidate CVs downloadable with no auth** (media/ served when DEBUG=True; tunnel hosts in ALLOWED_HOSTS) | Everyone | Anonymous GET returns full CV text | Authenticated media view w/ role check; DEBUG=False for any shared instance | S | Critical — PII leak |
| 2 | **Candidate edit page 500s for everyone** (`candidate_edit.html` missing) | HR | Click Edit → 500 | Create the template or repurpose review page; add render test | S | Dead core feature |
| 3 | **Candidate list = 143 controls** (52 identical stage dropdowns) | HR | Scan cost + misfire risk scales with list | Row-click → detail flow; move stage-select to detail only | M | HR's main page unusable at scale |
| 4 | **No visibility into candidate emails** (rejection/acceptance fire to console only) | HR | Can't verify system communicated on its behalf | OutboundEmail log model + "Emails sent" block on candidate detail | M | Trust in automation |
| 5 | **No feedback-complete nudge** | HR | All feedback in → silence until 7-day escalation | Notification to job creator when round's feedback completes; link to Move Stage | S | Kills pipeline stalls |
| 6 | **No bulk shortlist→assign** | HR | One page-load + one control per candidate | Checkbox column + bulk-assign POST reusing AssignApplicationView validation | M | Highest-frequency HR loop |
| 7 | **Per-row property N+1s in _app_row.html** (eligible_interviewers/slot_preview/feedbacks.count/moves.first bypass prefetch; 14→38 queries 1→2 apps) | HR, interviewer | Query count scales with apps × interviewers | Precompute eligibility/slots in view; use prefetch caches in template | M | Detail page stays fast at scale |
| 8 | **Scheduler never runs locally** (reminders/escalations dormant) | HR, interviewer | >3-day reminder, >7-day escalation never fire in this deployment | Procfile worker/cron entry; run management command on schedule | S | Safety nets actually run |
| 9 | **Onboarding→availability chain broken** (onboard form has no availability; assignment error names the fix but links nowhere) | HR, interviewer | Assignment fails with dead-end error | Add availability step to onboarding; link error message to /my-availability/ | S | First-assignment success |
| 10 | **Post-hire dead end** (is_fully_hired computed but consumed by nothing) | HR | Hire → email → silence | "Hired — next steps" card on candidate detail; "openings filled, consider closing" prompt on job | S | Funnel ends abruptly |
| 11 | **Panel consensus badges unstyled** (`badge-success/info/danger` classes don't exist in CSS) | HR, interviewer | "Unanimous: Recommend Hire" renders as bare text | Add the 3 classes or remap panel.py to existing badges | S | Decision-support invisible |
| 12 | **Dangling aria-describedby on all form errors** | Everyone | Screen readers get dead references | Shared form_field partial with matching error ids + role="alert" | M | A11y correctness |
| 13 | **Search→detail→back context loss** (breadcrumb/All-candidates drop filters; POSTs always return to detail) | HR | Every detour strands the user | Carry qs in return URLs / referrer-aware redirect | M | HR flow friction |
| 14 | **Export is global-only, 32 queries, per-job N/A rows** | Management | No per-job/per-candidate export; 0.0-day metrics confuse | ?job= param + candidate-level rows; set-based avg-days query | M | Exec analytics value |
| 15 | **No pagination on jobs list; 9-section dashboard** | Management | Unbounded card grid; 9 undifferentiated sections | Paginate jobs; section-label rhythm on dashboard | S | Executive scan-ability |

---

## 3. Feature Journey Map (current vs ideal)

| Journey | Current flow | Pain points | Ideal flow |
|---|---|---|---|
| HR: job → hire | Create job → rounds → upload/import → review queue → assign → schedule → feedback → move → hire/reject | 52-dropdown list; per-candidate assignment; no bulk; feedback-complete silence; hire dead-ends; no email visibility | Bulk triage → guided assignment → nudge on feedback-complete → one-click move → post-hire checklist |
| Interviewer: 30-min crunch | Login → dashboard (6 assigned, 1 pending, clear "Action needed") → Give feedback (scorecard + AI polish) → submit → back to dashboard | Calendar pull-only; panel members not notified of schedule changes; no reminders fire locally | Push notification on booking; .ics; reminders actually fire |
| Management: 30-second check | Login → same HR dashboard (read-only enforced) → export CSV | 9 undifferentiated sections; export global-only with N/A rows; no drill-down from KPIs | Exec summary card first; per-job export; KPI→filtered-list drill-down |
| First-time HR activation | Login → dashboard with 4 KPIs + AI insights; Create job is sole primary CTA | No onboarding/tour; 702-unread badge overwhelms; AI insight cards talk about test-data jobs; Needs Review queue reachable but resolution loses context | Guided first-run (create job → upload → assign); actionable notification triage; insight cards only when data is real |

---

## 4. UX Improvement Backlog

**Quick wins (<1 day)**
- Add `.badge-success/.badge-info/.badge-danger` CSS (or remap `ai/panel.py`) — consensus visible again
- Add `candidate_edit.html` template (fix the 500)
- Link the "no availability" assignment error to `/my-availability/`
- `aria-current="page"` on pagination; `scope="col"` on table headers
- Feedback-complete → notification to job creator
- "Hired — next steps" card on candidate detail
- Warn on >50k-char import truncation
- Standardize deny responses (one mixin → uniform 403)

**Medium (1–7 days)**
- Shared `page_header.html` partial across 23 templates (fixes h1 drift + CTA wording drift)
- Shared `form_field.html` partial (fixes aria-describedby everywhere)
- Authenticated media view with role-based CV access
- Row-click candidate detail; retire per-row stage dropdowns
- Bulk assign/move endpoints + checkbox column
- Per-job export param + candidate-level export rows
- Return-to-search context (qs carry-through on detail links and POST redirects)
- Procfile/cron wiring so reminders + escalations actually run

**Major (1+ weeks)**
- Postgres migration (+ WAL/busy_timeout stopgap now) for multi-user writes
- Async CV parse pipeline with needs_review staging (bounded AI latency)
- Scheduled executive digest (email/report) for management
- Design-system extraction: token-enforced button/badge vocabulary, single modal pattern

---

## 5. Automation Roadmap

| Current manual process | Automation opportunity | Expected benefit |
|---|---|---|
| HR scans list to decide who advances | AI-ranked shortlist card per job (scores exist; surface top-N with reasons) | Triage time −50% |
| HR checks who hasn't submitted feedback | Feedback-complete nudge + reminder cadence (already coded, needs scheduler) | Zero stalled rounds |
| HR rejects candidates one by one on close | Closure batch already exists; add pre-close review step + email log | Trust + fewer mistakes |
| Management opens dashboard for updates | Scheduled digest email (KPIs + stalled + needs-review) | Exec engagement without login |
| HR manually matches talent pool | Talent-pool card on dashboard when suggestions exist (data already computed per job detail) | Rediscovered feature |
| Interviewer self-schedules around availability | Slot picker already suggests free slots; extend to auto-propose on assignment | Scheduling friction −30% |

---

## 6. Production SaaS Checklist

| Area | Status | Notes |
|---|---|---|
| Onboarding | ❌ | No first-run guidance; empty states are good but no tour/checklist |
| Empty states | ✅ | Every page has title+body+CTA (verified across 13 pages) |
| Error handling | ✅ | Zero 500s in chaos probes; 404s on bad IDs; form errors inline |
| Accessibility | ⚠️ | Skip-link, labels, focus-visible, reduced-motion all good; error-aria + th scope + color-only signals need work |
| Mobile | ⚠️ | Tables/filters/popover adapt; topbar search disappears <1100px with no replacement |
| Security | ⚠️ | Authz matrix clean; media leak under DEBUG + DEBUG=True pattern is the risk |
| Performance | ⚠️ | Fast now; N+1 scaling + SQLite locking = multi-user risk |
| Notifications | ✅ | In-app complete with grouping, unread badge, page-read triage; email surface missing |
| Analytics | ⚠️ | KPIs + AI insights present; export shallow; no drill-down |
| Documentation | ⚠️ | PRODUCT.md/DESIGN.md exist; no user-facing help |
| Backup/retention | ✅ | Retention report + policy explicit |
| Scheduler | ❌ | Reminder/escalation jobs not wired in current deployment |
