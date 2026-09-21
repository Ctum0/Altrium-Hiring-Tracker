JOURNEY ID: interviewer-assignment-notification
USER TYPE: Interviewer
GOAL: Notice a new candidate assignment and open the candidate to prepare.
START STATE: Interviewer logged in anywhere in the app.
EXPECTED END STATE: Assignment visible via topbar badge + popover; click-through lands on the candidate; notification marked read.
FEATURES: HR Assign (source edge) → Notification badge → Popover → Candidate Detail
TRANSITIONS:
  - (HR) Candidate Detail → Assign → notification created
  - Interviewer popover item → Candidate Detail (click-through + mark-read)
  - Popover → "View all" → Notifications page
NOTES: Verified live 2026-09-21 (cycle 2). Badge count updates via 30s poll; popover lists the assignment with candidate link; click-through navigates and marks read. Eligibility gate on the HR side blocks ineligible picks with explanatory slot-preview badges.
