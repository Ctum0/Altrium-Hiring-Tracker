JOURNEY ID: hr-close-job-with-rejection-batch
USER TYPE: HR
GOAL: Close a filled job and ensure losing candidates are informed.
START STATE: HR logged in; an active job with active applications.
EXPECTED END STATE: Job closed with a reason; active applicants emailed rejection notices; HR knows the batch outcome; reopening remains possible.
FEATURES: Job Detail → Close (reason modal) → Job Detail (closed state) → Reopen (if needed) → Retention Report
TRANSITIONS:
  - Job Detail → Close (reason select + confirm modal)
  - Close → Job Detail (toast; Closed badge; Reopen button appears)
  - Closed job → Retention Report ("Show closed" on jobs list → retention)
NOTES: Verified live 2026-09-21. The close works and the toast confirms; Reopen appears immediately. GAP-011: the rejection-email batch outcome is silent (no count, no failure surfacing).
