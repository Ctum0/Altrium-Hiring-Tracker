# Altrium Hiring Tracker

> **Client-Based Software Engineering Project**  
> Developed for **Altrium** | Recruitment Operations & Candidate Pipeline Platform

---

## 📌 Executive Summary & Client Context

**Altrium Hiring Tracker** is a full-stack recruitment operations and applicant tracking platform engineered to solve real-world hiring bottlenecks for **Altrium**.

### The Client Problem
Prior to this solution, recruitment workflows relied on fragmented tools:
- **CV Overload**: 1,000+ candidate CVs accumulated unstructured in Google Drive folders per role.
- **Lost Feedback**: Interview notes were scattered across Slack channels without historical tracking or scoring criteria.
- **Access & Visibility Deficit**: Lack of role-based access control (RBAC), custom stage gating per role, or real-time KPI metrics (HR manually compiled reports in Excel).

### The Technical Solution
A centralized, high-density Django application providing:
- **Structured Kanban Pipelines**: Custom stage rounds per job posting with stage-gating enforced by interview feedback rules.
- **Role-Based Access Control (RBAC)**: Fine-grained permissions for HR Admins, Interviewers, and Management Oversight.
- **AI-Assisted Operations**: Automated CV text extraction, skill tagging, panel score consensus engine, and note polishing.
- **Real-Time Operational Analytics**: Live KPI metrics, pipeline velocity tracking, and SLA escalation flags (>7 days stalled).

---

## 🚀 Key Features & Capabilities

- 🔐 **Role-Based Access Control (RBAC)**
  - **HR Managers**: Job management, CV ingestion, stage movement, interviewer assignment.
  - **Interviewers**: Scoped view of assigned candidates, structured scorecards, and note polishing.
  - **Management**: Executive KPI dashboards, escalation metrics, and CSV report export.

- 📊 **Interactive Stage-Gated Kanban Board**
  - Per-job custom interview stages (e.g., Screening, Tech Assessment, Panel Interview, Offer).
  - Drag-and-drop movement with automated validation (prevents moving candidates without round feedback).

- 🧠 **AI Intelligence & Panel Consensus Engine**
  - **CV Parsing**: Automated text parsing, contact extraction, and skill tags via Groq LLM integration (`llama-3.3-70b-versatile`).
  - **Panel Consensus Engine**: Weighted multi-interviewer score aggregation, conflict detection, and variance alerts.
  - **Note Polishing & Rejection Emails**: Converts raw notes into professional summaries and generates personalized candidate emails.

- 🎨 **Modern Design System & Accessibility**
  - Dense, frosted-glass UI language (OKLCH color space, CSS custom properties).
  - Built-in Light/Dark mode toggle with persistent preferences.

---

## 🛠️ System Architecture & Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Backend Framework** | Django 5 (Python 3.12) |
| **Frontend / Interactivity** | HTMX, Vanilla JavaScript, CSS Custom Properties (OKLCH tokens) |
| **Database** | SQLite (Development) / PostgreSQL (Production) |
| **Object Storage** | Cloudflare R2 / S3-compatible storage (Resume PDF/Word files) |
| **AI Processing** | Groq API (`llama-3.3-70b-versatile` / `mixtral-8x7b-32768`) |
| **Deployment / Container** | Docker, Docker Compose, Gunicorn, Render / Railway ready |

---

## 💻 Getting Started

### 1. Local Setup (Virtualenv)

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Ctum0/Altrium-Hiring-Tracker.git
   cd Altrium-Hiring-Tracker
   ```

2. **Initialize Environment & Install Dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   ```
   *(Configure `DJANGO_SECRET_KEY` and optional `GROQ_API_KEY` in `.env`)*

4. **Apply Migrations & Seed Demo Accounts**:
   ```bash
   python manage.py migrate
   python manage.py seed_users
   ```

5. **Launch Development Server**:
   ```bash
   python manage.py runserver
   ```
   Access the web app at `http://127.0.0.1:8000`.

---

### 2. Docker Setup

To run the complete web application and PostgreSQL database using Docker Compose:

```bash
docker compose up --build
```

---

## 🔑 Demo User Accounts

The `seed_users` command automatically configures standard accounts for evaluation:

| Role | Username | Password | Operational Access |
| :--- | :--- | :--- | :--- |
| **HR Manager** | `hr_demo` | `testpass123` | Full pipeline, candidate import, interviewer assignment |
| **Interviewer** | `iv_demo` | `testpass123` | Assigned candidate scorecards & note polishing |
| **Management** | `mgmt_demo` | `testpass123` | Executive KPI dashboard, reporting & exports |

---

## 🧪 Testing & Quality Assurance

Run the comprehensive Django unit and integration test suite:

```bash
python manage.py test
```

---

## 📄 License & Attribution

Developed as a client-based project for **Altrium**. All rights reserved.
