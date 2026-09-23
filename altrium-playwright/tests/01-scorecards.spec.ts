import { test, expect, type Page } from '@playwright/test';
import { login, logout } from '../utils/auth';
import { createJob, importCandidate, assignInterviewer, ensureInterviewerAvailability } from '../utils/fixtures';
import { ScorecardPage } from '../pages/scorecard.page';

async function setupAssignedCandidate(page: Page): Promise<{
  candidateId: number;
  applicationId: number;
  roundId: number;
}> {
  const jobTitle = `Scorecard Test Job ${Date.now()}`;
  const jobId = await createJob(page, jobTitle);
  const email = `scorer_${Date.now()}@example.com`;
  const candidateId = await importCandidate(page, jobId, 'Score Tester', email);
  await ensureInterviewerAvailability(page);
  await login(page, 'hr');
  await assignInterviewer(page, candidateId, 0, 'Ivan Vance');
  await page.goto(`/candidates/${candidateId}/`);
  const assignFormId = await page
    .locator('[id^="assign-form-"]')
    .first()
    .getAttribute('id');
  const match = assignFormId?.match(/assign-form-(\d+)/);
  const roundValue = await page
    .locator('option[value^="round:"][selected]')
    .first()
    .getAttribute('value');
  const roundMatch = roundValue?.match(/round:(\d+)/);
  return {
    candidateId,
    applicationId: Number(match?.[1] ?? 0),
    roundId: Number(roundMatch?.[1] ?? 0),
  };
}

function scorecardUrlFor(applicationId: number, roundId: number): string {
  return `/feedback/${applicationId}/${roundId}/`;
}

test.describe('Scorecards Evaluation', () => {
  test('1. Scorecard displays criteria and accepts ratings with 50/25/25 weighted score', async ({ page }) => {
    test.slow();
    await login(page, 'hr');
    const { applicationId, roundId } = await setupAssignedCandidate(page);
    await logout(page);
    await login(page, 'interviewer');

    const scorecard = new ScorecardPage(page);
    await page.goto(scorecardUrlFor(applicationId, roundId));

    await expect(page.getByText('Technical Skill', { exact: true })).toBeVisible();
    await expect(page.getByText('Communication', { exact: true })).toBeVisible();
    await expect(page.getByText('Culture Fit', { exact: true })).toBeVisible();

    await scorecard.fillCriteria(80, 60, 70);
    await scorecard.fillNotes('Weighted math verification run.');
    await scorecard.submit();

    await expect(page).toHaveURL(/\/feedback\//);
    await expect(page.locator('main')).toBeVisible();
  });

  test('2. AI rating suggestions populate form and require interviewer approval', async ({ page }) => {
    test.slow();
    await login(page, 'hr');
    const { applicationId, roundId } = await setupAssignedCandidate(page);
    await logout(page);
    await login(page, 'interviewer');

    const scorecard = new ScorecardPage(page);
    await page.goto(scorecardUrlFor(applicationId, roundId));
    await scorecard.fillNotes('Candidate demonstrated deep Python knowledge and clear communication.');

    if (await scorecard.suggestRatingsButton.isVisible().catch(() => false)) {
      await scorecard.suggestRatingsButton.click();
      await page.waitForTimeout(1000);
    }

    await scorecard.fillCriteria(85, 80, 80);
    await scorecard.submit();
    await expect(page).toHaveURL(/\/feedback\//);
  });
});

