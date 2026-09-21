# Altrium Hiring Tracker

An internal recruitment management platform: job postings with custom
interview rounds, CV ingestion with AI-assisted parsing, a Kanban hiring
pipeline with feedback-enforced progression, structured interviewer
scorecards, and role-scoped dashboards for HR, interviewers, and management.

Built with Django 5, server-rendered templates + HTMX, and a Groq-backed AI
layer (parsing, note polishing, panel consensus) that degrades gracefully to
local heuristics when the AI service is unavailable.

---

## Features

### Roles & access

Strict role-based access control, enforced in both the UI and on every
endpoint server-side:

| Role | Access |
| :--- | :--- |
| **HR** | Full workflow: create jobs with custom interview rounds, ingest CVs (upload or paste-import), score and assign candidates, move the pipeline, close jobs with automated candidate notifications, export reports |
| **Interviewer** | Role-scoped: sees only candidates assigned to them (or their panel), submits structured scorecards, manages their weekly availability and calendar |
| **Management** | Read-only oversight: live KPIs, pipeline analytics, escalation flags, CSV export — every write endpoint rejects the role with a 403 |

### Hiring workflow

- **Jobs with custom rounds** — HR defines the interview stages per position
  (Screening, System Design, Offer…), reorderable at any time.
- **CV ingestion** — multi-file PDF/DOCX upload and paste-import; an AI
  parsing layer extracts name, contact details, and skills, with a
  zero-failure local fallback; deduplication by email plus fuzzy
  name+phone matching; optional per-job auto-reject baseline score.
- **Kanban pipeline** — one board per job, one column per round plus
  Hired/Rejected/On-Hold lanes; drag-and-drop or keyboard moves; stage
  progression is blocked until the round being left has feedback.
- **Structured scorecards** — fixed-criteria evaluation (Technical Skill,
  Communication, Culture Fit) with AI-suggested ratings the interviewer
  reviews before submitting; edit history is preserved.
- **AI panel consensus** — with two or more evaluations, the engine
  synthesizes vote tallies, agreed strengths, and divergence warnings.
- **Availability-aware scheduling** — interviewers declare weekly windows;
  HR picks from computed free slots, and the server rejects any time
  outside a declared window or a double-booking.
- **Candidate-facing application page** — a public, unauthenticated form
  per job that runs the same parsing/dedup/scoring pipeline.
- **Automated emails** — confirmation on intake, AI-drafted rejection
  notes, acceptance on hire, feedback reminders after three days, and
  7-day escalation dispatches.
- **Talent pool** — closed jobs' strong rejected candidates are
  resurfaced for one-click re-engagement in a domain-matching role.
- **Reporting** — live dashboard (stage distribution, pipeline velocity,
  feedback completion, stage pass rates), CSV export, and a data-retention
  audit view.

### Quality system

The repository ships a self-sustaining QA system built around *product
continuity* — finding gaps **between** features rather than within pages:

- `make qa-all` runs the full guard suite: lint gate → 467 Django tests →
  19 Playwright feature-transition specs against a seeded dev server.
- `tests/feature-transitions/` — browser specs organized around
  feature-to-feature transitions (login routing, KPI deep links, stage
  moves with the feedback gate, assignment → notification → click-through,
  public apply end-to-end, …).
- CI (`.github/workflows/qa.yml`) runs the same suite on every push and
  fails if QA session state is ever staged.
- A persistent gap ledger and feature graph drive the audit workflow; see
  `qa/journeys/` for the documented user journeys.

---

## Tech stack

| Layer | Choice |
| :--- | :--- |
| Backend | Django 5 (Python 3.13), Django templates + HTMX |
| Database | PostgreSQL (production) / SQLite (local dev, CI) |
| AI | Groq LLM API (`llama-3.3-70b-versatile`) + local heuristic fallback |
| Auth | Django auth + django-axes login rate-limiting |
| Storage | S3-compatible object storage for CVs (signed URLs) |
| Deploy | Docker / Compose / Gunicorn / Render |
| Testing | Django test suite (467 tests) + Playwright (19 browser specs) + axe-core accessibility scans |

---

## Local setup

```bash
git clone https://github.com/Ctum0/Altrium-Hiring-Tracker.git
cd Altrium-Hiring-Tracker

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # fill in DJANGO_SECRET_KEY (optional in DEBUG)
python manage.py migrate

# Seed demo accounts + demo data (DEV ONLY — wipes existing data; the
# Docker/Render boot command does NOT run this):
python manage.py clean_and_seed_db --force

python manage.py runserver    # http://127.0.0.1:8000
```

### Demo accounts (local dev only)

Created by `clean_and_seed_db --force` (or `seed_users` for the three base
accounts). These exist only in a locally seeded database — they are not
valid on any deployed instance unless an operator explicitly opted in via
`SEED_DEMO_USERS=true`.

| Role | Username | Notes |
| :--- | :--- | :--- |
| HR Manager | `hr_demo` | Full workflow access |
| Interviewer | `iv_demo` | Assigned candidates + scorecards |
| Management | `mgmt_demo` | Read-only oversight |

Password for all demo accounts: `testpass123` (documented in
`accounts/management/commands/seed_users.py`).

### Environment variables

See `.env.example`. Required in production: `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`; optional: `DATABASE_URL` (Postgres), `REDIS_URL`
(shared rate-limit store), `GROQ_API_KEY` (AI features degrade gracefully
without it), S3 credentials for CV storage.

---

## Testing

```bash
make qa-all      # lint + Django suite + Playwright transition specs
make qa-unit     # Django suite only
make qa-e2e      # browser specs only (starts the dev server first)
make qa-lint     # ruff gate
```

The Playwright specs seed their own namespaced data
(`qa/scripts/e2e_seed.py`) and authenticate through the real login form,
so they run in CI without pre-provisioned accounts.

---

## Project structure

```
accounts/      custom user model, roles, availability, roster, dashboards
jobs/          job postings, interview rounds, Kanban board, talent pool
candidates/    CV ingestion, parsing, scoring, search, public apply
pipeline/      stage moves, feedback gates, move audit trail
feedback/      scorecards, AI polish/suggest, edit history
notifications/ in-app notifications + email dispatch helpers
ai/            CV parsing, matching, panel consensus, confidence flags
templates/     server-rendered UI (base layout + per-app templates)
qa/            QA scripts, Playwright config, journey docs
tests/         feature-transition regression tests
```

---

## License

University client project developed for Altrium. All rights reserved.
