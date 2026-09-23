import { test, expect } from '@playwright/test';
import { login } from '../utils/auth';
import { createJob } from '../utils/fixtures';

test.describe('Job Closure Workflow', () => {
  test('6. Close job with reason removes it from active list and retains candidate data', async ({ page }) => {
    await login(page, 'hr');
    const jobTitle = `Closure Test Job ${Date.now()}`;
    const jobId = await createJob(page, jobTitle);

    await page.goto(`/jobs/${jobId}/`);
    await page.locator('select[name="closure_reason"]').selectOption('cancelled');
    await page.getByRole('button', { name: 'Close job' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();

    await expect(page.getByText(/Closed/i).first()).toBeVisible();

    await page.goto('/jobs/');
    const card = page.locator('.job-card-premium').filter({ hasText: jobTitle });
    await expect(card).toHaveCount(0);

    await page.getByRole('link', { name: 'Show closed' }).click();
    await expect(card.first()).toBeVisible();
  });

  test('7. Closed job can be reopened back to Active status', async ({ page }) => {
    await login(page, 'hr');
    const jobId = await createJob(page, `Reopen Test Job ${Date.now()}`);

    await page.goto(`/jobs/${jobId}/`);
    await page.locator('select[name="closure_reason"]').selectOption('on_hold');
    await page.getByRole('button', { name: 'Close job' }).click();
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByText(/Closed/i).first()).toBeVisible();

    await page.getByRole('button', { name: 'Reopen job' }).click();
    await expect(page.getByText('Active').first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Close job' })).toBeVisible();
  });
});

