# Altrium Tracker

## Product
Internal recruitment and hiring tracker for Altrium. Replaces Slack + Google Drive + Gmail for hiring: CVs, interview feedback, pipeline movement, and reporting all live in one place with strict role-based access.

## Users
- **HR** - owns the process: creates jobs, ingests CVs, scores, assigns interviewers, moves candidates, closes jobs.
- **Interviewers** - see only their assigned candidates, submit interview feedback.
- **Management** - read-only oversight: live KPIs, pipeline visibility, escalation flags, report export.

## Problem
CVs pile in one Drive folder (1000+ per role), feedback scrolls away in Slack, no role visibility, no per-role interview stages, no live reporting (manual Excel by HR).

## Solution
Centralized Django web app: Kanban pipeline with per-job custom stages, AI CV parsing, AI feedback polishing, AI rejection emails, feedback-enforced progression, full data retention, live dashboard.

## Scope (Sprint 1)
Auth + RBAC, job creation with custom rounds, CV upload/parse/import, paginated candidate list, search/filter, scoring, assignment, notifications, drag-drop Kanban.

## Scope (Sprint 2)
Interview scheduling links, scored feedback with edit history, feedback validation on move, AI note polishing, job closure with AI rejection emails, retention, KPI dashboard, 7-day escalation flags, CSV/Excel export.

## Register
Product / internal tool. Design serves the task: restrained, calm, dense-where-needed. Users are in flow; the tool disappears into the work.
