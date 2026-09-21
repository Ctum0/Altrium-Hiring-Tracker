JOURNEY ID: hr-post-job-receive-cvs
USER TYPE: HR
GOAL: Post a new job and start receiving candidates into its pipeline.
START STATE: HR logged in, on HR Dashboard, no job created yet for this role.
EXPECTED END STATE: Job exists with interview rounds configured; at least one candidate CV is uploaded/parsed and visible under that job; HR can see the candidate on the job's pipeline.
FEATURES: HR Dashboard → Create Job → Rounds Setup → Job Detail → CV Upload → Candidates List → Candidate Detail
TRANSITIONS:
  - Dashboard → Create Job (CTA "Create job", page header)
  - Create Job → Rounds Setup (auto-redirect after submit; "Define the role first; interview rounds can be configured next")
  - Rounds Setup → Job Detail ("Done, go to job")
  - Job Detail → CV Upload ("Upload CVs" button, ?job=<pk> preselects the Position dropdown)
  - CV Upload → Candidates List (post-success redirect; toast names the job)
  - Candidates List → Candidate Detail (row link)
NOTES: Verified live 2026-09-21. Upload success lands on the UNFILTERED candidates list — the just-uploaded cohort is findable only via the toast text or manually re-filtering by the job. Rounds reorder exists ONLY on the rounds-setup page; job detail offers add/remove rounds but no reorder after creation. Auto-reject baseline field has no visible help text in the form (help_text defined in form class but template omits the form-help paragraph).
