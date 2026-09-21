JOURNEY ID: hr-onboard-interviewer-and-assign
USER TYPE: HR
GOAL: Add a new interviewer to the roster and assign them a candidate whose profile matches.
START STATE: HR logged in; a candidate application is unassigned in a round.
EXPECTED END STATE: Interviewer account created with matching fields; candidate assigned; interviewer notified; slot preview shows availability.
FEATURES: Interviewer Roster → Onboard Account → Roster → Candidate Detail → Assign Interviewer → Slot Preview → Notification
TRANSITIONS:
  - Roster → Onboard ("Onboard account", HR-only)
  - Onboard → Roster (redirect after create; toast names the person)
  - Candidate Detail → Assign (per-application select; HTMX slot preview on change)
  - Assignment → Interviewer Notification ("New candidate assigned to you")
NOTES: Verified 2026-09-21 (live + code). Eligibility rules gate the dropdown: structured domain must match job domain (or be blank), seniority at-or-above requirement, availability windows required — slot preview badges explain blocks ("Not a match", "No availability"). Deactivation warns about reassignment; the Offboarding tab (candidates list) collects applications of deactivated interviewers with a Reassign CTA into candidate detail. Onboarding password is set by HR and shared out-of-band (documented in help text).
