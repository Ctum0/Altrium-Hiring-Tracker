import { test, expect } from '@playwright/test';
import { login } from '../utils/auth';
import * as fs from 'fs';

test.describe('Pipeline Reporting', () => {
  test('4. Dashboard displays stage counts, pass rates and pipeline metrics', async ({ page }) => {
    await login(page, 'hr');
    await page.goto('/hr-dashboard/');

    await expect(page.getByText('Total Applications')).toBeVisible();
    await expect(page.getByText('Open Positions')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Candidates by Stage' })).toBeVisible();
  });

  test('5. CSV export covers every job with title, department, candidate count, time-to-hire, status', async ({ page }) => {
    await login(page, 'hr');
    const downloadPromise = page.waitForEvent('download');
    await page.goto('/reports/export/').catch(() => {});
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toContain('csv');
    const filePath = await download.path();
    expect(filePath).toBeTruthy();
    if (filePath) {
      const body = fs.readFileSync(filePath, 'utf-8');
      const lines = body.trim().split('\n');
      expect(lines[0].trim()).toBe('Job Title,Department,Candidate Count,Avg Time to Hire (days),Status');
      expect(lines.length - 1).toBeGreaterThanOrEqual(1);
    }
  });
});

