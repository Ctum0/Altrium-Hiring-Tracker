JOURNEY ID: error-recovery-lockout-and-form-errors
USER TYPE: Any
GOAL: Recover gracefully from failed logins, validation errors, and network failures.
START STATE: Any login/form surface.
EXPECTED END STATE: User always sees a clear, human-readable message and a way to retry; no silent failures; no lost form work where avoidable.
FEATURES: Login → (lockout) → Login; Job Form → validation errors; Stage Move → 409 gate toast; HTMX network failure → toast
TRANSITIONS:
  - Login failure → error alert ("Incorrect username or password. Please try again.")
  - Lockout → 429 page ("Account locked: too many login attempts. Please try again later.")
  - Job form validation → inline form-error paragraphs
  - Stage move 409 → toast with server message + select revert
  - HTMX sendError/timeout → network toast
NOTES: Verified live 2026-09-21 (lockout reproduced with 5 failures; django-axes per username+IP, 1h cooloff). Gaps: (1) lockout message does not say HOW long ("try again later" — cooloff is 1h, undocumented to the user); (2) toast auto-dismisses after 5s — a 409 gate message disappears quickly and the row itself doesn't persist the reason (only the reverted select hints at failure); (3) job form auto-reject baseline has no help text in UI, so its "requires at least one requirement" constraint surfaces only as a validation error after submit.
