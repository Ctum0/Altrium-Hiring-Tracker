JOURNEY ID: public-candidate-apply
USER TYPE: Public candidate (unauthenticated)
GOAL: Find an open role and apply with my CV.
START STATE: Anonymous visitor opens /careers/.
EXPECTED END STATE: Application submitted, CV parsed, confirmation page shown with a path to keep browsing.
FEATURES: Careers List → Public Apply Form → Thanks Page
TRANSITIONS:
  - Careers → Apply ("Apply →" per job card)
  - Apply → Thanks (successful POST)
  - Thanks → Careers ("Browse other open roles")
NOTES: Verified live 2026-09-21. Careers page lists all active jobs with department/domain/seniority and description. Apply form: CV upload primary, optional name/email/phone fallbacks, consent checkbox required. Thanks page confirms and offers "Browse other open roles" — no dead end. Back-link "← All open positions" on the apply form preserves the careers entry path. Name fallback merge: typed full_name only fills gaps the parse missed.
