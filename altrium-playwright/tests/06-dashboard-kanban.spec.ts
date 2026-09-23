import { test, expect } from '@playwright/test';
import { login } from '../utils/auth';

test.describe('Dashboard & Candidate List', () => {
  test('10. Candidate list pagination and Interviewer dashboard render cleanly', async ({ page }) => {
    await login(page, 'hr');
    await page.goto('/candidates/');
    await expect(page.getByRole('heading', { name: /Candidates/i })).toBeVisible();

    await page.goto('/candidates/?page=1');
    await expect(page.locator('main')).toBeVisible();

    await page.goto('/candidates/?page=9999');
    await expect(page.locator('main')).toBeVisible();

    await login(page, 'interviewer');
    await page.goto('/interviewer-dashboard/');
    await expect(page.locator('main')).toBeVisible();
  });
});

