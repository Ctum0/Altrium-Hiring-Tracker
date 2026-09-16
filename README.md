# Altrium Hiring Tracker

> Internal recruitment management and candidate evaluation platform developed for **Altrium**.

---

## 📌 Project Overview

**Altrium Hiring Tracker** is a web application built for Altrium's internal HR team, technical interviewers, and engineering management to track candidates, schedule interviews, and manage feedback in one place.

It is an **internal system only** (candidates do not log in). It replaces a manual process that relied on shared Google Drive folders, lost Slack messages, and unorganized email threads.

---

## 🎯 Business Problem & Context

Before this application, Altrium managed hiring across multiple disconnected tools:

1. **Lost Data & Files**: CVs were uploaded into crowded shared Google Drive folders without any tracking of who reviewed which file or what score was given.
2. **Scattered Feedback**: Interviewers sent notes in Slack channels, where they were easily missed or buried in chat history.
3. **No Central Pipeline View**: HR had to manually message team leads or compile spreadsheets to check application status or see how long candidates were stuck in an interview stage.
4. **Different Roles Needed Different Stages**: Technical roles required coding tests and architecture interviews, while non-technical roles needed portfolio reviews. Shared folders couldn't handle role-specific interview rounds.

---

## 🔄 Workflow Comparison

| Old Manual Workflow | Altrium Hiring Tracker |
| :--- | :--- |
| **Position Setup**: HR created shared Drive folders and Slack channels manually. | **Position Setup**: HR creates job posts with custom interview rounds (e.g. Screening, Tech Interview, Offer). |
| **CV Collection**: CVs piled up in Google Drive folders. | **CV Ingestion**: CVs (PDF/DOCX) are uploaded and parsed into candidate profiles with extracted skills. |
| **Shortlisting**: Reviewers opened PDFs individually with no record of past notes. | **Shortlisting**: Search, filter by skills/score, and view full candidate history in one view. |
| **Feedback**: Notes sent in random Slack threads. | **Feedback**: Evaluation scorecards and AI panel consensus directly linked to the candidate. |
| **Stage Progression**: Candidates moved manually on spreadsheets without checks. | **Stage Progression**: Interactive pipeline board with feedback checks before moving stages. |
| **Reporting**: HR compiled manual Excel sheets for management updates. | **Reporting**: Real-time management dashboard with pipeline metrics and SLA alerts. |

---

## 💡 Key Features & Roles

The system uses Role-Based Access Control (RBAC) to control access:

- **HR Manager (`hr_demo`)**: Full access. Opens job positions, ingests and parses CVs, assigns interviewers, moves candidates across stages, overrides shortlist scores, and can remove candidates.
- **Interviewer (`iv_demo`)**: Role-scoped access. Sees only candidates assigned to them, submits interview scorecards, and uses AI note polishing.
- **Management (`mgmt_demo`)**: Read-only executive access. Views real-time hiring metrics, pipeline health, SLA escalation alerts, and AI panel consensus.

See Test Accounts below for the full list of demo logins and which management command creates each one.

---

## 📈 Development Status & Roadmap

### 🟢 Sprint 1 (Completed Core Platform)
All primary functional requirements solving Altrium's core recruitment operations are fully implemented and operational:

- **Authentication & RBAC**: Custom user model, secure authentication, and role-based view enforcement for HR, Interviewer, and Management roles.
- **Job Creation & Custom Rounds**: HR job posting interface with position-specific interview round configurations.
- **CV Ingestion & Fallback AI Parsing**: Multi-file CV upload (PDF/DOCX) and text paste import with zero-failure local fallback parsing for contact details and skills.
- **CV Deduplication & Categorization**: Automated email deduplication and candidate skill matching against job requirements.
- **Search, Filter & Qualitative Scoring**: Multi-field query search, status filters, and 0–100 shortlist score overrides.
- **Interviewer Assignment & Notifications**: HR interface for assigning interviewers, with in-app notification triggers.
- **Interview Details & Scheduling**: Fast management interface for adding meeting links and interview instructions.
- **Structured Interview Feedback**: Round-specific evaluation scorecards with role-scoped submission validation.
- **AI Feedback Assistant**: AI note-polishing engine converting raw interviewer notes into clean, bulleted summaries.
- **Feedback Edit History**: Immutable audit log preserving prior versions when evaluation notes are edited.
- **AI Panel Consensus & Conflict Resolver**: Engine synthesizing multi-evaluator vote tallies (Hire/Hold/Reject), agreed strengths, and divergence warnings.
- **Position Closure & Management Dashboard**: Executive analytics dashboard with active metrics and job closure controls.

- **Auto-Reject Baseline Score**: Jobs can define a minimum AI match score (0-100, validated); CVs scoring below the baseline are auto-rejected at upload/import time (never auto-resurrected on re-upload). A baseline without requirements is rejected at form level, so the baseline can never silently mass-reject.
- **Intelligent Interviewer Selection**: Assignment enforces role-matching (interviewer specialty vs. job department; blank = generalist) and declared availability windows, in both the dropdown filter and server-side validation. Assign/unassign run through a confirmation dialog; unassign clears the booked interview slot and notifies the former assignee.
- **Availability-Aware Scheduling**: HR picks a slot from a live availability preview (weekly windows + computed next free 1-hour slots) rendered inline when an interviewer is selected. Slots must fall inside the interviewer's windows; double-booking the same interviewer at the same time is blocked.
- **Interviewer Roster Dashboard**: HR/Management view of every interviewer's specialty, weekly availability, live workload (assignee + panel), and pending feedback.
- **Escalation Drill-Down**: Dashboard lists candidates stalled >7 days with job, idle time, and assignee for management follow-up.
- **Honest Analytics**: Pipeline velocity shows measured average days-in-stage (no synthetic formulas); insight cards show real candidate counts and skill frequencies; action links deep-link to filtered candidate lists.
- **Security Hardening**: docker boot no longer wipes/reseeds production data or resets passwords; SECRET_KEY/DEBUG fail closed in production; login rate-limiting via django-axes; signed S3 media URLs; session + upload size caps; tunnel hosts trusted in DEBUG only.

### 🟢 Sprint 2 (Completed)

All Sprint 2 features below are implemented and live in the codebase:

- **Kanban Board**: Per-job board at `/jobs/<pk>/board/` with one column per interview round plus terminal Hired/Rejected/On Hold lanes; native drag-and-drop moves a candidate between stages.
- **CV Self-Upload**: Public, unauthenticated application form at `/candidates/apply/<job_pk>/` that runs the same parsing, dedup, and scoring pipeline as an HR-driven upload.
- **Structured Scorecard with AI-Suggested Ratings**: Fixed-criteria evaluation form (Technical Skill, Communication, Culture Fit) with an AI endpoint that proposes a rating per criterion from raw notes; the interviewer reviews and confirms before submitting.
- **AI General Feedback**: Once a candidate has feedback from two or more rounds, an AI-written narrative consolidates every round's ratings and notes into one summary, regenerated on each new submission.
- **Confirmation, Rejection & Acceptance Emails**: Automatic emails on CV intake (confirmation), on rejection or job closure (AI-drafted rejection), and on a hire decision (acceptance), sent through a shared mail helper with a console fallback in development.
- **Automated Feedback Reminders**: The `send_feedback_reminders` management command emails interviewers with feedback pending more than three days; wired to run daily via cron.
- **7-Day Escalation Dispatch**: The `dispatch_escalations` management command emails HR/Management when a candidate has been stalled in a stage for more than seven days.
- **Talent Pool Rematching Engine**: Scans closed jobs for rejected or on-hold candidates who scored 80+ and offers HR a one-click re-engagement into a new, domain-matching job.
- **CSV Report Export**: One-click CSV download at `/reports/export/` listing job title, department, candidate count, average time-to-hire, and status for every job.
- **Data Retention Report**: Read-only audit at `/reports/retention/` listing every closed job, days since closure, and candidates still on file; confirms no automatic deletion or archival happens.
- **Stage Performance Analytics**: Dashboard card computing the pass/fail rate per interview round from move history and flagging rounds with an abnormally high drop-off.
- **Interviewer Availability Self-Service**: Interviewers set and edit their own recurring weekly availability windows directly in the app.
- **Domain/Seniority Interviewer Matching**: Structured Domain and Seniority fields on jobs and interviewer accounts; assignment requires both a domain match and interviewer seniority at or above the job's required level.
- **Rounds-in-Creation Flow**: HR configures a job's interview rounds inline immediately after creating it, before landing on the job detail page.

### 🟡 Future Roadmap (Planned Enhancements)

Every feature originally planned for Sprint 2 has shipped (see Sprint 2 (Completed) above). No further enhancements are currently planned.

---

## 🛠️ Tech Stack

- **Backend**: Django 5 (Python 3.12)
- **Frontend**: HTML5, Vanilla JavaScript, HTMX, Custom Glassmorphism CSS
- **Database**: PostgreSQL (Production) / SQLite (Local dev)
- **AI Services**: Groq LLM API (`llama-3.3-70b-versatile`) + Local Heuristic Fallback Engine
- **Deployment**: Docker, Docker Compose, Gunicorn, Railway

---

## 💻 Local Setup & Quick Start

```bash
# Clone repository
git clone https://github.com/Ctum0/Altrium-Hiring-Tracker.git
cd Altrium-Hiring-Tracker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# DEV ONLY — wipes all data and reseeds demo content. Never run against a
# production database; the Docker/Render boot command does NOT run this.
python manage.py clean_and_seed_db --force
# Seed demo availability windows for interviewer accounts
python manage.py shell -c "from accounts.models import InterviewerAvailability, User; [InterviewerAvailability.objects.get_or_create(interviewer=iv, weekday=wd, start_time='09:00', end_time='12:00') for iv in User.objects.filter(role='IV') for wd in (0, 2)]"

# Start local server
python manage.py runserver
```

Access the app at `http://127.0.0.1:8000`.

---

## 🔑 Test Accounts (Password: `testpass123`)

The three base accounts below are created by `python manage.py seed_users`, the only account seeder wired into a production boot (gated behind `SEED_DEMO_USERS=true`). This is what exists on the Railway deployment linked below. The five additional named accounts are only created locally by `python manage.py clean_and_seed_db --force` (used in the Local Setup steps above) and will not exist on a deployment that only ran `seed_users`.

| Role | Username | Name & Role | Access Level | Seeded By |
| :--- | :--- | :--- | :--- | :--- |
| **HR Manager** | `hr_demo` | Hana Miller (Lead Talent Partner) | Full admin access, job creation, candidate & stage management | `seed_users` |
| **HR Partner** | `hr_sarah` | Sarah Jenkins (Senior Recruiter) | Full admin access, candidate upload & assignment | `clean_and_seed_db --force` only |
| **Interviewer** | `iv_demo` | Ivan Vance (Backend Lead) | Assigned candidates, scorecards & AI note tools | `seed_users` |
| **Interviewer** | `iv_chen` | Dr. Marcus Chen (Frontend Architect) | Assigned candidates & frontend technical scorecards | `clean_and_seed_db --force` only |
| **Interviewer** | `iv_rachel` | Rachel Adams (DevOps Manager) | Assigned candidates & infrastructure evaluation | `clean_and_seed_db --force` only |
| **Interviewer** | `iv_patel` | Vikram Patel (QA Engineering Lead) | Assigned candidates & automation evaluation | `clean_and_seed_db --force` only |
| **Management** | `mgmt_demo` | Mia Thorne (VP of Engineering) | Read-only executive dashboard & SLA alerts | `seed_users` |
| **Management** | `mgmt_davis` | David Ross (Director of Product) | Read-only pipeline metrics & panel consensus | `clean_and_seed_db --force` only |

---

## 🧪 Testing
Railway Deployement: https://altrium-hiring-tracker-production.up.railway.app/ 
(Use this link to access the WebApplication)

Run the Django automated test suite:

```bash
python manage.py test
```

---

## 📄 License & Attribution

University client project developed for **Altrium**. All rights reserved.
