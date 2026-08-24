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

- **HR Manager (`hr_demo`, `hr_sarah`)**: Full access. Opens job positions, ingests and parses CVs, assigns interviewers, moves candidates across stages, overrides shortlist scores, and can remove candidates.
- **Interviewer (`iv_demo`, `iv_chen`, `iv_rachel`, `iv_patel`)**: Role-scoped access. Sees only candidates assigned to them, submits interview scorecards, and uses AI note polishing.
- **Management (`mgmt_demo`, `mgmt_davis`)**: Read-only executive access. Views real-time hiring metrics, pipeline health, SLA escalation alerts, and AI panel consensus.

---

## 📈 Development Status & Roadmap

### 🟢 Sprint 1 (Completed Foundation)
- User authentication and role-based views (HR, Interviewer, Management).
- Job creation with configurable interview rounds.
- CV file upload (PDF/DOCX) and text extraction.
- CV parsing engine with zero-failure local fallback parser for contacts & skills.
- Candidate profile management, scoring rules, and multi-field search.
- Interviewer assignment and in-app notifications.
- Interactive candidate pipeline board and stage tracking.

### 🟡 Sprint 2 & Future Roadmap
- **Feedback-Gated Stage Progression**: Prevents advancing a candidate to the next round unless feedback exists for the current round.
- **7-Day SLA Escalation Alerts**: Flags candidates stuck in an active stage without feedback for over 7 days directly on the management dashboard.
- **Enhanced AI Panel Consensus**: Distinguishes single-evaluator summaries from multi-interviewer panel consensus, highlighting vote tallies (Hire/Hold/Reject) and flagging panel divergence.
- **Feedback Version History**: Immutable audit log preserving prior versions when interview notes are edited.
- **Interview Details & Scheduling**: Fast management interface for adding meeting links and interview instructions.

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

# Run migrations and seed clean enterprise test data
python manage.py migrate
python manage.py clean_and_seed_db --force

# Start local server
python manage.py runserver
```

Access the app at `http://127.0.0.1:8000`.

---

## 🔑 Test Accounts (Password: `testpass123`)

| Role | Username | Name & Role | Access Level |
| :--- | :--- | :--- | :--- |
| **HR Manager** | `hr_demo` | Hana Miller (Lead Talent Partner) | Full admin access, job creation, candidate & stage management |
| **HR Partner** | `hr_sarah` | Sarah Jenkins (Senior Recruiter) | Full admin access, candidate upload & assignment |
| **Interviewer** | `iv_demo` | Ivan Vance (Backend Lead) | Assigned candidates, scorecards & AI note tools |
| **Interviewer** | `iv_chen` | Dr. Marcus Chen (Frontend Architect) | Assigned candidates & frontend technical scorecards |
| **Interviewer** | `iv_rachel` | Rachel Adams (DevOps Manager) | Assigned candidates & infrastructure evaluation |
| **Interviewer** | `iv_patel` | Vikram Patel (QA Engineering Lead) | Assigned candidates & automation evaluation |
| **Management** | `mgmt_demo` | Mia Thorne (VP of Engineering) | Read-only executive dashboard & SLA alerts |
| **Management** | `mgmt_davis` | David Ross (Director of Product) | Read-only pipeline metrics & panel consensus |

---

## 🧪 Testing

Run the Django automated test suite:

```bash
python manage.py test
```

---

## 📄 License & Attribution

University client project developed for **Altrium**. All rights reserved.
