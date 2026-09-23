# Altrium Playwright Tests

Automated Playwright test cases for **Altrium Hiring Tracker** — a 1:1
automation of the manual test-case documents:

- **Sprint 02 Functional Features** (Scorecards, Candidate Portal,
  Automated Emails, Pipeline Reporting, Job Closure)
- **Sprint 1 NFR** (RBAC, pagination, retention, feedback validation,
  multiple applications, interview rounds)

Test names match the DOCX Feature rows so automated results map back to
the manual document.

## Prerequisites

1. Django dev server running:
   ```bash
   cd /home/ctum/PPPM
   .venv/bin/python manage.py runserver 127.0.0.1:8100 --noreload
   ```
2. Seeded users exist: `hr_demo`, `iv_demo`, `mgmt_demo` (password
   `testpass123`) and `admin` for the email-log checks.
3. Node 18+ installed.

## Setup (first time)

```bash
cd /home/ctum/Documents/altrium-playwright
npm install
npx playwright install chromium
```

## Running

```bash
npm test                 # all suites (chromium)
npm run test:headed      # watch the browser live
npm run test:ui          # Playwright UI mode (pick tests, watch steps)
npm run test:report      # open the HTML report (screenshots + traces)

# Individual suites (match the DOCX feature groups):
npm run test:scorecards  # Scorecards (9 DOCX cases)
npm run test:portal      # Candidate Application Portal
npm run test:emails      # Automated Emails & Notifications
npm run test:pipeline    # Pipeline Reporting + CSV export
npm run test:closure     # Job Closure + Talent Pool
npm run test:nfr         # Sprint 1 NFR (RBAC + core)
```

## Evidence

Every test captures a **screenshot at the end** (`screenshot: 'on'` in
the config). After a run, open the HTML report:

```bash
npm run test:report
```

Each result shows the screenshot, steps, and any trace — paste these
into the manual DOCX "Actual Outcome" column.

## Structure

```
pages/          Page Objects (login, scorecard, candidate detail, dashboards)
tests/          Spec files — one per DOCX feature group
utils/auth.ts   Role login helpers (hr / interviewer / management)
utils/fixtures.ts  UI-driven test data builders (create job, import candidate)
```

## Notes

- Tests run **serially** (1 worker) because they share the Django DB and
  create data.
- Tests **clean up after themselves** where practical (fresh
  job/candidate per test via timestamped names), so re-runs are safe.
- AI-dependent tests (`test.slow()`) allow up to ~20s for the Groq call;
  the app's circuit breaker falls back to the local heuristic engine if
  the AI is unreachable, so tests still pass offline.
