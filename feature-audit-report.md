# Feature Audit Report — New Features (Workstream 1)

**Scope:** Edge-case testing + UX/layout evaluation for all new features. Not the dashboard.

---

## Test Results Summary

| Feature | Edge Cases Tested | Bugs Found | UX Issues | Status |
|---------|-------------------|------------|-----------|--------|
| 1.1 Confidence-Gated Review | 4 confidence signals, binary rejection, review flow, dedup | 1 | 2 | Working, needs polish |
| 1.2 Workload Assignment | Dropdown display, zero-load case, reassignment | 0 | 1 | Working |
| 1.3 Assign-Before-Schedule | Disabled state, enable after assign, separate forms | 0 | 0 | Working |
| 1.4 Offboarding | Empty state, list rendering | 0 | 1 | Working |
| Multiple Openings | Create with num_openings=3, job list display | 0 | 1 | Working |
| Terminal Move Gate | Hire without feedback → 409, hire with feedback → success | 0 | 0 | Working |
| Score Scale | Consistent 0-100 across form/help/panel | 0 | 0 | Working |

---

## Feature 1.1: Confidence-Gated CV Review

### What works
- All 4 confidence signals fire correctly: no_email, low_text_volume, name_is_skill_word, single_word_name
- Flagged candidates appear with yellow "⚠ Review" badge in list
- "⚠ Needs Review" tab appears with count badge (only when count > 0)
- Review page is a clean, focused separate page with editable fields + raw text
- "Save & Mark Reviewed" clears the flag and records reviewer/timestamp
- High-confidence parses flow through untouched (tested: good PDFs not flagged)
- Binary validation rejects <10 char extractions before candidate creation

### Edge case: Binary rejection vs. confidence flag
**Bug:** When a file has <10 chars extracted text (e.g., `bad_parse.pdf`), it's rejected entirely ("unreadable or corrupted") — no candidate is created, no needs_review flag. This is correct behavior but **not documented**. The flash message says "unreadable or corrupted" which is accurate but the user might expect to see it in the review queue.

**UX issue 1: No link from review badge to the review page on the detail page.**
The candidate detail page shows a yellow "⚠ Needs Review" badge but it's a link to the review page. However, the link styling looks identical to plain text — it's a small yellow badge. A more prominent "Review Now" button would be clearer.

**UX issue 2: Review page has no indication of which job this candidate was uploaded for.**
The review page shows first_name/last_name/email/phone/skills but doesn't show which job they were uploaded to. HR may need this context. The review page should show the job title.

### Recommendation
- Add job title to the review page template
- Make the review badge on detail page more prominent (button-style, not just badge)

---

## Feature 1.2: Workload-Aware Assignment

### What works
- Dropdown shows "(N active)" next to each interviewer name
- Counts are accurate (verified: Vikram Patel shows "1 active" with Nadia assigned)
- Zero-load interviewers show "(0 active)"
- Non-blocking — HR can assign anyone regardless of load
- Data is pre-computed in the view context (no N+1)

### UX issue 1: No visual warning for above-average load
The audit spec says "If HR assigns someone whose load is well above the team average, a non-blocking inline warning appears." This is NOT implemented — the dropdown shows counts but there's no warning text or visual differentiation for overloaded interviewers.

**Recommendation:** Add a CSS class or inline style to highlight workload counts above average (e.g., amber text for >2x average).

---

## Feature 1.3: Assign-Before-Schedule

### What works
- `interview_at` input is `disabled` when no interviewer is assigned
- Tooltip "Assign an interviewer first to enable scheduling" shows on hover
- After assignment is submitted, the page re-renders with `assigned_to` set, enabling the input
- Separate forms for assign and schedule enforce the sequence

### No issues found. Clean implementation.

---

## Feature 1.4: Offboarding / Needs Reassignment

### What works
- "🔄 Offboarding" link appears in candidate list tabs (HR-only)
- Empty state renders correctly: "All clear — No active candidates are assigned to deactivated interviewers."
- Page loads without errors

### UX issue 1: No way to deactivate a user from the UI
The offboarding page shows candidates needing reassignment, but there's no action to actually deactivate a user — that requires Django admin access. For a production system, HR should have a "Deactivate" action on the interviewer roster page.

**Recommendation:** Add a "Deactivate" button to the interviewer roster page (with confirm dialog). This triggers `is_active=False` on the user account.

---

## Feature: Multiple Openings (num_openings)

### What works
- Job form has "Number of openings" field with help text
- Default value is 1
- Job list shows "(0/3 hired)" when num_openings > 1
- `hires_made` property correctly counts hired applications
- `is_fully_hired` property works

### UX issue 1: No display of num_openings on job detail page
The job detail page shows "Candidates: 0" but doesn't show "Openings: 3" or "0/3 filled". HR needs to see this at a glance.

**Recommendation:** Add "Openings: X (Y filled)" to the Details section of job_detail.html.

---

## Feature: Terminal Move Gate

### What works
- Hiring/rejecting a candidate without feedback on the current round → 409 "Feedback is required before making a final hiring decision."
- Toast message appears and select reverts
- Hiring succeeds after feedback is submitted
- Moves from terminal states (on_hold → round) work without feedback (correct: re-entry)

### No issues found. Solid implementation.

---

## Feature: Score Scale Unification

### What works
- Form help text: "Score from 0 to 100 (e.g. 75)"
- Panel consensus: all scores normalized via `/10.0` (no ambiguous ≤10 branch)
- Feedback list displays raw scores correctly

### No issues found.

---

## Cross-cutting UX observations

1. **The review page is a separate page, not a modal.** This is correct — reviewing a flagged candidate requires focused attention and editing multiple fields. A modal would be too cramped.

2. **The offboarding page is also a separate page.** Correct — it's a list view, not a single-action item.

3. **The workload count in the dropdown is text, not a visual indicator.** For v1 this is fine. A future iteration could use color-coded bars (green/amber/red) but text is sufficient for the stated requirement.

4. **The "Needs Review" tab uses a warning color (amber) that's consistent with the badge.** Good visual language.

5. **The schedule-disable tooltip is clear and positioned correctly.** No accessibility issues.

6. **The num_openings field defaults to 1 with a clear help text.** No confusion risk.

---

## Priority fix list

| Priority | Issue | Fix | Effort |
|----------|-------|-----|--------|
| P1 | Review page doesn't show job context | Add job title to candidate_review.html | S |
| P1 | No "Deactivate" action on interviewer roster | Add deactivate button + confirm dialog | M |
| P1 | No visual warning for above-average workload | Add amber highlight for >2x average in dropdown | S |
| P2 | Num_openings not shown on job detail | Add "Openings: X (Y filled)" to job_detail.html | S |
| P2 | Review badge on detail is plain-looking | Style as button/link with clear affordance | S |
| P3 | No bulk review action (review all flagged at once) | Add "Mark all reviewed" for quick triage | M |
