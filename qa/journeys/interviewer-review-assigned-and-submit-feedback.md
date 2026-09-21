JOURNEY ID: interviewer-review-assigned-and-submit-feedback
USER TYPE: Interviewer
GOAL: See my assigned candidates and submit structured interview feedback for the current round.
START STATE: Interviewer logged in, Interviewer Dashboard, at least one application assigned with feedback_submitted=False.
EXPECTED END STATE: Feedback submitted for the current round; dashboard row flips to "Submitted"; HR receives a notification; candidate's pipeline progression is unblocked.
FEATURES: Interviewer Dashboard → Candidate Detail → Feedback Form → Feedback Detail → (Dashboard refresh)
TRANSITIONS:
  - Dashboard row → Feedback Form ("Give feedback" button, ?next= back to dashboard)
  - Feedback Form → Feedback Detail (after submit; toast confirms)
  - Feedback Detail → History ("View history")
  - Candidate Detail → Feedback Form (via pending feedback list "Submit Feedback")
NOTES: Verified 2026-09-21 (live walk + template audit). The dashboard "Give feedback" button renders ONLY when feedback_submitted=False; with feedback already submitted the row shows "Submitted" with no edit affordance on the dashboard — editing requires going through Feedback list → detail → Edit. Pending Feedback tab scopes to the interviewer's own actionable rows. Availability warning: interviewers with no weekly windows see a prominent "Set your availability now" banner on the dashboard — good continuation design. Form pre-fills criteria scores on re-entry (edit mode).
