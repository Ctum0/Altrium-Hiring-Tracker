import { test, expect } from '@playwright/test';
import { login } from '../utils/auth';

test.describe('Role-Based Access Control (RBAC)', () => {
  test('8. HR has full management access while Interviewer is restricted from HR routes', async ({ page }) => {
    await login(page, 'hr');
    await page.goto('/hr-dashboard/');
    await expect(page.getByRole('heading', { name: 'Pipeline Overview' })).toBeVisible();

    await login(page, 'interviewer');
    await page.goto('/jobs/create/');
    await expect(page).not.toHaveURL(/\/jobs\/create\//);
  });

  test('9. Management user has read-only access to dashboard and candidate profiles', async ({ page }) => {
    await login(page, 'management');
    await page.goto('/jobs/create/');
    await expect(page).not.toHaveURL(/\/jobs\/create\//);

    await page.goto('/hr-dashboard/');
    await expect(page.getByRole('heading', { name: 'Pipeline Overview' })).toBeVisible();
  });
});

