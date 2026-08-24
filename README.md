# Altrium Hiring Tracker

> **Enterprise Internal Recruitment Operations & Candidate Pipeline Platform**  
> Developed for **Altrium** | Internal Human Resources & Technical Recruitment Operations

---

## 📌 Executive Summary

**Altrium Hiring Tracker** is a centralized internal recruitment management platform engineered for **Altrium** to streamline candidate evaluations, standardize multi-stage interview workflows, and provide executive visibility over hiring pipelines.

The platform is strictly an **internal-only tool** — candidates do not have access to the system. It replaces a fragmented legacy process of shared Google Drive folders, manual Slack threads, and uncoordinated email communications with a single, role-governed workspace.

---

## 🎯 Business Problem & Client Context

As Altrium scaled hiring across technical and non-technical departments, recruitment operations faced critical bottlenecks:

### 1. Process Fragmentation Across Disparate Tools
- Candidates applied via email or portals, while CVs were uploaded into unorganized shared Google Drive folders (1,000+ files per position).
- Interview feedback was communicated back and forth across ephemeral Slack channels, causing critical evaluator notes to scroll away and get lost.
- Interview scheduling and follow-ups relied on manual memory and uncoordinated Gmail threads.

### 2. Multi-Reviewer Collision & Visibility Deficit
- When multiple interviewers reviewed CVs in shared drives, there was zero visibility into who had reviewed a candidate, what score was given, or why a candidate was shortlisted or passed over.
- HR could not track overall hiring pipeline status, candidate progression rates, or position closure timelines without manually querying team leads and compiling ad-hoc Excel spreadsheets.

### 3. Rigid, One-Size-Fits-All Evaluation Paths
- Different roles require fundamentally different interview workflows (e.g., technical roles require coding assessments and architecture panels; non-technical roles require portfolio reviews and behavioral interviews).
- Shared drive folders and static tracking sheets failed to support role-specific interview stages or enforce stage-completion rules.

### Core Business Challenge
The central business challenge for Altrium was **organizing recruitment communication, candidate evaluation, interview feedback, and hiring progress in one centralized internal system** with full historical auditability.

---

## 🔄 Operational Workflow Transformation

| Legacy Fragmented Workflow | Altrium Hiring Tracker Platform |
| :--- | :--- |
| **Position Setup**: HR manually created shared Drive folders & Slack channels per role. | **Position Setup**: HR initializes jobs in the portal with position-specific, configurable interview rounds. |
| **CV Collection**: CV PDFs piled up in shared folders (1,000+ per position). | **CV Ingestion**: CVs are uploaded, automatically parsed via AI, and candidate profiles are imported with skill tags. |
| **Shortlisting**: Reviewers manually opened PDFs in Drive without seeing prior reviewer notes. | **Shortlisting**: Automated skill scoring, multi-field search/filtering, and centralized candidate profile views. |
| **Feedback Collection**: Notes sent via Slack messages, easily lost or forgotten. | **Feedback Collection**: Structured evaluation scorecards tied directly to specific candidate applications. |
| **Stage Progression**: Candidates manually dragged across loose sheets without feedback validation. | **Stage Progression**: Stage-gated Kanban pipeline enforcing evaluation completion before advancement. |
| **Reporting**: HR manually compiled Excel sheets to answer management status inquiries. | **Reporting**: Real-time management dashboards with pipeline velocity, SLA escalation flags, and live KPIs. |

---

## 💡 The Solution & Core System Capabilities

Altrium Hiring Tracker replaces ad-hoc operations with an enterprise-grade internal platform providing:

1. **Internal-Only Security & Governance**: Strict Role-Based Access Control (RBAC) ensuring internal users see only what their role demands. Candidates have zero system access.
2. **Job-Specific Adaptable Workflows**: Custom interview workflows and multi-round configurations tailored to specific job functions (Technical vs. Non-Technical).
3. **Structured Evaluation & Audit Trails**: Standardized interviewer scorecards, detailed technical evaluation notes, and version-controlled feedback edit histories where edits maintain previous versions.
4. **Centralized Candidate History & Data Retention**: Complete record of candidate applications across multiple positions, maintaining evaluation history even after positions close.
5. **Management Analytics & Oversight**: Executive dashboard with live pipeline metrics, SLA escalation alerts, and recruitment pipeline visibility for leadership.

---

## 👥 Role-Based Access Control (RBAC) Architecture

The application enforces strict internal role boundaries:

| User Role | System Capabilities & Access Scope |
| :--- | :--- |
| **HR Manager** *(Process Owner)* | Full operational authority: opens job positions, configures interview stages, ingests & parses CVs, assigns interviewers, advances/rejects candidates, and closes positions. |
| **Interviewer** *(Evaluator)* | Restricted access: views only candidates explicitly assigned to them, submits structured evaluation scorecards, and utilizes note-polishing tooling for their assignments. |
| **Management / Leadership** *(Oversight)* | Read-only access: live KPI analytics dashboard, pipeline health metrics, 7-day SLA escalation alerts, and report exports. |

---

## 📈 Development Status & Milestone Roadmap

Development is organized in structured milestones. The project is currently at the completion of **Sprint 1**, establishing the core operational foundation.

### 🟢 Sprint 1 (Completed Foundation)
The primary focus of Sprint 1 was establishing the core data architecture, security model, and essential candidate processing pipelines:

- **Authentication & RBAC**: Custom user model, secure authentication, and role-based view enforcement for HR, Interviewer, and Management roles.
- **Job Creation & Configurable Stages**: Ability for HR to create job listings and define custom multi-round interview stages (e.g., Screening, Tech Assessment, Panel Interview, Offer).
- **CV Upload & Raw Text Extraction**: File upload pipeline supporting PDF/Docx CV files with raw text extraction.
- **AI CV Parsing**: Groq LLM integration (`llama-3.3-70b-versatile`) extracting candidate contact details, summary, and skill arrays.
- **Candidate Profile Importing**: Centralized candidate profile creation from parsed CV data.
- **Automated Skill Scoring**: Automated scoring rules evaluating candidate skill sets against job requirements.
- **Candidate Search, Filtering & Management**: Multi-field search, status filtering, and paginated candidate listings.
- **Interviewer Assignment**: HR management interface for assigning specific interviewers to candidate applications.
- **In-App Notifications**: Notification engine informing interviewers of new assignments and HR of feedback submissions.
- **Candidate Pipeline Management**: Application tracking models linking candidates, jobs, stages, and assignments.
- **Kanban-Based Recruitment Workflow**: Interactive board for visualizing and managing candidate applications across hiring stages.

---

### 🟡 Sprint 2 & Future Roadmap (Planned Enhancements)

> [!NOTE]
> While the Sprint 1 foundation is operational, the Kanban board and pipeline automation tools are currently in a foundational state and planned for further enhancement in Sprint 2. Future sprints will continue improving recruitment automation, reporting, communication, and operational efficiency.

#### Planned Sprint 2 Work:
- **Enhanced Interactive Kanban Board**: Fluid drag-and-drop mechanics with instant HTMX state updates and live round counters.
- **Interview Scheduling Integration**: Embedded scheduling links and calendar integration directly within candidate application details.
- **Feedback Edit Version History**: Audit logging for feedback edits that preserves full prior version history for quality and compliance.
- **Automated Position Closure & Rejection Emails**: AI-generated personalized rejection email dispatch upon position closure.
- **Executive Analytics & Export**: Live 7-day escalation flags for stalled candidates and CSV/Excel report exporter for leadership review.

---

## 🎯 Featured Sprint 2 Functional Highlight

To deliver immediate business value beyond cosmetic UI updates, Sprint 2 prioritizes a high-impact operational feature:

### 🌟 Business Feature: Feedback-Gated Stage Progression & 7-Day SLA Escalation Engine

#### Business Problem Addressed:
In the legacy workflow, candidates were frequently advanced to subsequent interview rounds before previous interviewers submitted their feedback, or candidates remained stalled in an interview stage for weeks because no one followed up on missing feedback. This wasted candidate and interviewer time and created severe HR tracking debt.

#### High-Value Business Solution:
1. **Feedback-Enforced Stage Gating**: The system blocks candidate progression to the next interview round unless at least one completed evaluation scorecard exists for the current round (returning HTTP 409 Conflict if feedback is missing).
2. **Automated 7-Day SLA Escalation Flags**: The pipeline engine automatically flags any candidate application that has remained in an active stage without feedback for >7 days, alerting HR and Management on the executive dashboard to eliminate recruitment bottlenecks.

**Business Value Delivered**:
- **Reduces Manual HR Chasing**: Eliminates manual Slack messages from HR asking interviewers if feedback was completed.
- **Guarantees Evaluation Rigor**: Prevents candidates from reaching final rounds without documented evaluation notes.
- **Improves Hiring Velocity**: Directly reduces time-to-hire by highlighting stalled candidates in real time.

---

## 🛠️ Tech Stack & System Architecture

| Layer | Technology |
| :--- | :--- |
| **Backend Framework** | Django 5 (Python 3.12) |
| **Frontend / Interactivity** | HTMX, Vanilla JavaScript, Custom OKLCH CSS Design System |
| **Database** | SQLite (Development) / PostgreSQL (Production ready) |
| **Object Storage** | Cloudflare R2 / S3-compatible storage (for candidate CV files) |
| **AI Services** | Groq LLM API (`llama-3.3-70b-versatile` / `mixtral-8x7b-32768`) |
| **Deployment** | Docker, Docker Compose, Gunicorn, Render/Railway configuration |

---

## 💻 Local Setup & Quick Start

### 1. Virtual Environment Setup

```bash
# Clone the repository
git clone https://github.com/Ctum0/Altrium-Hiring-Tracker.git
cd Altrium-Hiring-Tracker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env

# Run database migrations & seed test accounts
python manage.py migrate
python manage.py seed_users

# Start development server
python manage.py runserver
```

Access the application at `http://127.0.0.1:8000`.

---

### 2. Docker Setup

Run the full web application and PostgreSQL database stack using Docker Compose:

```bash
docker compose up --build
```

---

## 🔑 Demo User Accounts

The `seed_users` management command automatically populates test accounts for evaluation:

| Role | Username | Password | Operational Access Level |
| :--- | :--- | :--- | :--- |
| **HR Manager** | `hr_demo` | `testpass123` | Full administrative pipeline, job creation, candidate import & assignment |
| **Interviewer** | `iv_demo` | `testpass123` | Assigned candidates, scorecards & note-polishing tools |
| **Management** | `mgmt_demo` | `testpass123` | Executive KPI dashboard, SLA escalation flags & reporting |

---

## 🧪 Testing & Quality Assurance

Run the comprehensive Django automated test suite:

```bash
python manage.py test
```

---

## 📄 License & Client Attribution

Developed as a client-based internal software engineering project for **Altrium**. All rights reserved.
