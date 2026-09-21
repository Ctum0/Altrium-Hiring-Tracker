JOURNEY ID: hr-triage-needs-review-candidates
USER TYPE: HR
GOAL: Find CVs the parser flagged and resolve them.
START STATE: HR logged in; dashboard shows "Needs Review" KPI > 0.
EXPECTED END STATE: Flagged candidates reviewed; flags cleared (individually or bulk); KPI reflects the new count.
FEATURES: HR Dashboard → Needs Review KPI → Candidates List (filtered) → Candidate Review → Candidate Detail
TRANSITIONS:
  - Dashboard KPI → Candidates List (?needs_review=1 deep link)
  - List → Candidate Detail (flag badge "Needs Review: <reason>" on detail)
  - Detail → Review page (badge link; human-readable reason explanations)
  - Review → Detail (redirect; toast summary of re-scores)
  - List → Bulk "Mark all reviewed" (HR-only, confirm dialog)
NOTES: Verified live 2026-09-21. The review page humanizes the raw reason codes (low_text_volume → "Very little text was extracted..."). GAP FOUND: the detail-page flag badge renders the raw snake_case reason ("Needs Review: low_text_volume") and has no badge styling (class badge-pending has no CSS rule) — inconsistent with the review page and with every other badge on the page. Bulk review counts ALL flagged candidates, not just the filtered job's.
