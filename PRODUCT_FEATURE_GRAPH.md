# Product Feature Graph

The application as a feature graph. NODE = feature, EDGE = transition between features. This is the persistent mental model for every future agent working on continuity — keep it current.

Status: **SKELETON** — node/edge list derived from URL configuration and product docs at setup time. Edges marked `unverified` have not yet been driven in a browser. The first DISCOVER/MAP cycle fills in per-edge documentation.

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

## Nodes (by Django app)

### Auth / entry (accounts)
- Login (`/login/`)
- Logout (POST-only)
- Home router (`/` — role-based redirect: HR/Management → HR dashboard, Interviewer → interviewer dashboard)
- HR Dashboard (`/hr-dashboard/`) — jobs grid + pipeline metrics
- Interviewer Dashboard (`/` for IV role)
- Management Dashboard (redirects to HR dashboard view, read-only surface)
- Reports export (`/reports/export/`), Retention report (`/reports/retention/`)
- Interviewer roster (`/interviewer/<pk>/`, deactivate), Onboard user (`/onboard/`)
- My availability (`/my-availability/`), My calendar (`/my-calendar/`)

### Jobs
- Jobs list (dashboard is the list), Create job (`/jobs/create/`)
- Job detail (`/jobs/<pk>/`), Kanban board (`/jobs/<pk>/board/`)
- Rounds setup (`/jobs/<pk>/rounds-setup/`), round create/delete/reorder
- Job edit / close / reopen
- Talent pool add (`/jobs/<pk>/talent-pool-add/<application_pk>/`)

### Candidates
- CV upload (`/candidates/upload/`), CV import (`/candidates/import/`)
- Candidate list (paginated, search/filter), Candidate detail (`/candidates/<pk>/`)
- Candidate edit / delete, Review (`/candidates/<pk>/review/`), bulk review (`/candidates/review-all/`)
- Score (`/candidates/<pk>/score/`)
- Application actions: AI fit (`/applications/<pk>/ai-fit/`), assign interviewer (`/applications/<pk>/assign/`), interview details, interviewer slots
- Public apply (`/candidates/apply/<job_pk>/` + thanks) — unauthenticated surface
- Offboarding (`/candidates/offboarding/`)

### Pipeline
- Kanban drag-drop stage movement (per-job board)
- Feedback-enforced progression gates

### Feedback
- Feedback form (`/feedback/<application_pk>/<round_pk>/`)
- Feedback detail (`/feedback/<pk>/`), history (`/feedback/<pk>/history/`)
- AI polish / AI suggest endpoints

### Notifications
- Notification list (`/notifications/`)

### AI
- CV parsing, matching (`ai/matching.py`), panel question generation — background/service layer surfaced through the views above

## Roles

- **HR** — full workflow: jobs, candidates, scoring, assignment, pipeline moves, closing, exports.
- **Interviewer (IV)** — sees only assigned candidates; submits interview feedback; availability/calendar.
- **Management (MGMT)** — read-only oversight: KPIs, pipeline visibility, escalation flags, report export.

## Core edges (expected primary chains — verify in DISCOVER)

### HR chain
```text
Login → HR Dashboard
HR Dashboard → Create Job
Create Job → Job Detail
Job Detail → Rounds Setup
Job Detail → CV Upload / Import
CV Upload → Candidate Review
Candidate Review → Score
Score → Assign Interviewer
Assign → Kanban Board
Kanban Board → Feedback Form
Feedback Form → Feedback Detail
Pipeline Move → (gates) → Hired / Rejected
Rejected → AI Rejection Emails (job close)
Job close → Reports / Export
Dashboard → Notifications
```

### Interviewer chain
```text
Login → Interviewer Dashboard
Dashboard → My Calendar / My Availability
Dashboard → Assigned Candidate
Assigned Candidate → Interview Details
Interview → Feedback Form
Feedback Form → Feedback Detail
```

### Management chain
```text
Login → Management Dashboard (read-only)
Dashboard → Job views (read-only)
Dashboard → Reports Export
Dashboard → Escalation flags
```

### Public chain
```text
Careers list (/careers/) → Public Apply → Thanks
```

## Known gaps

None recorded yet — populate from `PRODUCT_GAP_LEDGER.md` as entries are confirmed, and link GAP-IDs on the affected edges.

## UI patterns section

To be filled by the `ui-consistency-inventory` skill: shared component inventory (templates/includes, base blocks, form/button/table patterns) with occurrence counts and shared-implementation status.
