# Altrium Hiring Tracker

An enterprise-grade applicant tracking and recruitment operations platform designed for high-density hiring workflows. Replaces fragmented spreadsheets, chat threads, and cloud drive folders with centralized candidate management, automated stage gating, role-based governance, and AI-assisted candidate evaluations.

---

## Key Features

- **Role-Based Governance (RBAC)**: Enforces distinct capabilities for **HR Managers** (pipeline control, job creation, assignment), **Interviewers** (assigned candidate access, feedback submission), and **Management** (read-only KPI monitoring, report exports).
- **Interactive Kanban Pipeline**: Drag-and-drop hiring stages with per-job custom interview rounds and strict stage-gating (prevents advancement without required round feedback).
- **AI-Powered CV Ingestion**: Automated parsing of uploaded CVs/resumes to extract candidate contact details, experience summaries, and skill tag arrays.
- **AI Panel Consensus & Conflict Engine**: Multi-interviewer score aggregation, weighted round scoring, and automated detection of interviewer score variance.
- **Feedback Standardization**: Interviewer note polishing and automated rejection email generator powered by LLM integration.
- **SLA & Escalation Monitoring**: Automated flagging of candidates pending feedback or stalled in pipeline rounds for >7 days.
- **Modern UI & Dual-Theme System**: Dense, glassmorphism visual language built with OKLCH color system, CSS custom properties, and instant theme toggling (Light/Dark mode).

---

## Tech Stack

- **Backend Framework**: Django 5 (Python 3.12)
- **Frontend / Dynamic Interactivity**: HTMX, Vanilla JS, Custom Glassmorphism CSS Design System
- **Database**: SQLite (Local Dev) / PostgreSQL (Production)
- **Object Storage**: Cloudflare R2 / S3-compatible storage (for CV storage)
- **AI Integration**: Groq API (`llama-3.3-70b-versatile` / `mixtral-8x7b-32768`)
- **Deployment**: Docker, Render / Railway ready (`render.yaml`, `Procfile`)

---

## Getting Started

### Local Setup (Python / Virtualenv)

1. **Clone Repository**:
   ```bash
   git clone https://github.com/Ctum0/Altrium-Hiring-Tracker.git
   cd Altrium-Hiring-Tracker
   ```

2. **Set Up Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   ```
   *(Edit `.env` to set your `DJANGO_SECRET_KEY` and optional `GROQ_API_KEY`)*

4. **Run Migrations & Seed Initial Demo Accounts**:
   ```bash
   python manage.py migrate
   python manage.py seed_users
   ```

5. **Start Development Server**:
   ```bash
   python manage.py runserver
   ```
   Navigate to `http://127.0.0.1:8000` in your browser.

---

### Docker Compose Setup

Run the full web and PostgreSQL stack locally using Docker:

```bash
docker compose up --build
```

---

## Demo Accounts

The `seed_users` management command sets up demo accounts for testing all three system roles:

| Role | Username | Password | Access Level |
| :--- | :--- | :--- | :--- |
| **HR Manager** | `hr_demo` | `testpass123` | Full administrative & pipeline control |
| **Interviewer** | `iv_demo` | `testpass123` | Assigned candidates & feedback entry |
| **Management** | `mgmt_demo` | `testpass123` | Executive KPI dashboard & reporting |

---

## Testing & Quality Assurance

Run the automated Django test suite:

```bash
python manage.py test
```

---

## License

Copyright © Altrium. All rights reserved.
