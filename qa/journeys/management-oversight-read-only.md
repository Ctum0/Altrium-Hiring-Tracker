JOURNEY ID: management-oversight-read-only
USER TYPE: Management
GOAL: Oversee live pipeline health and export reports without touching operational data.
START STATE: Management user logged in, redirected to HR dashboard (read-only surface).
EXPECTED END STATE: Management has viewed KPIs, AI insights, escalations, and exported a CSV; no write affordances encountered; all mutation attempts blocked server-side.
FEATURES: Management Dashboard (= HR Dashboard view) → Jobs list → Candidates List → Reports Export → Retention Report → Interviewer Roster
TRANSITIONS:
  - Login → HR Dashboard (role redirect)
  - Dashboard KPI cards → filtered Candidates List / Feedback list (deep links)
  - Dashboard → Export report (CSV download) / Retention report
  - Dashboard → Interviewer Roster (read-only: no Onboard button, no Deactivate)
NOTES: Verified live 2026-09-21. Read-only enforcement is solid at the server (403s on ai_fit/score/assign/move; HR-only template gates hide buttons). One inconsistency found: the "Generate AI assessment" button renders on candidate detail for Management even though the endpoint 403s — clicking it produces an HTMX error toast. UI shows an affordance the role cannot use.
