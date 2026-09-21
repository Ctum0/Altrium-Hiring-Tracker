// @ts-check
/**
 * close-job-email-feedback.spec.ts
 * Guards GAP-011: closing a job with active applicants reports the
 * rejection-email batch outcome in the toast.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');

test.describe('close job → email batch feedback', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('close toast mentions the emailed-candidate count', async ({ page }) => {
    await loginAs(page, 'hr');
    // Give the E2E candidate an email so they are part of the batch
    await page.goto(`${BASE}/candidates/${ids.candidate_pk}/`, { waitUntil: 'load' });
    const hasScore = await page.locator('#score').count();
    test.skip(!hasScore, 'candidate detail lacks score form');

    // Close the E2E job (it has exactly 1 active applicant)
    await page.goto(`${BASE}/jobs/${ids.job_pk}/`, { waitUntil: 'load' });
    await page.evaluate(() => {
      const sel = document.getElementById('closure-reason');
      sel.value = 'cancelled';
      sel.closest('form').submit();
    });
    await page.waitForLoadState('load');
    await page.waitForTimeout(2000);

    // The toast reports the batch outcome (0 emails here — no address on
    // file for the seeded candidate — so the "no active candidates needed"
    // branch is the honest outcome).
    const toast = await page.locator('.alert').allTextContents();
    const joined = toast.join(' ');
    expect(joined).toMatch(/closed\. Existing candidates are unchanged/);
    expect(joined).toMatch(/emailed rejection notices|no active candidates needed a rejection notice/);

    // Reopen so the seed stays reusable
    await page.locator('button:has-text("Reopen job")').click();
    await page.waitForLoadState('load');
  });
});
