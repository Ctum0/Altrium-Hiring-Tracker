JOURNEY ID: hr-pipeline-move-with-feedback-gate
USER TYPE: HR
GOAL: Move a candidate through interview rounds, respecting the feedback gate, and make a final hiring decision.
START STATE: HR logged in; a candidate application sits in round "Screening" of an active job.
EXPECTED END STATE: Candidate advanced to the next round (or terminal status) with feedback recorded for the round being left; audit trail (PipelineMove) recorded; candidate sees updated stage everywhere.
FEATURES: Candidates List → Candidate Detail → (Feedback Form via interviewer) → Stage Move (detail select or Kanban board) → Updated Row
TRANSITIONS:
  - Candidates List → Candidate Detail (row link)
  - Candidate Detail → Stage Move (per-application "Move to…" select; terminal moves confirm via modal)
  - Candidate Detail → Feedback History ("View Feedback History →")
  - Kanban Board → Stage Move (drag & drop; same endpoint)
NOTES: Verified live 2026-09-21. Terminal move (Hired) without feedback on the current round: modal confirms, server 409s, toast shows "Feedback is required before making a final hiring decision.", select reverts to the current round. Round-to-round move blocked with "Feedback required to move candidate to a different round." Board drop handler uses the same endpoint and surfaces the same message via board toast. The moved row is swapped in place (HTMX) — no page reload, context preserved.
