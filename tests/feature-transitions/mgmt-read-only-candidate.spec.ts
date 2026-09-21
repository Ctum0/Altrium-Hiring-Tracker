// @ts-check
/**
 * mgmt-read-only-candidate.spec.ts
 * Guards GAP-002: Management sees no AI assessment buttons and gets an
 * explanation instead; other write controls are absent.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs } = require('./helpers');

test.describe('management read-only candidate surface', () => {
  test('no Generate AI assessment button; explanation shown', async ({ page }) => {
    await loginAs(page, 'mgmt');
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });
    await page.goto(`${BASE}/candidates/`, { waitUntil: 'load' });
    await page.locator('tbody tr a').first().click();
    await page.waitForLoadState('load');

    await expect(page.locator('button:has-text("Generate AI assessment")')).toHaveCount(0);
    await expect(page.locator('button:has-text("Regenerate")')).toHaveCount(0);
    // The empty-fit panels explain who CAN generate
    await expect(page.locator('text=HR or the assigned interviewer can generate one').first()).toBeVisible();
    // Other write controls absent
    await expect(page.locator('button:has-text("Remove Candidate")')).toHaveCount(0);
    await expect(page.locator('button:has-text("Save score")')).toHaveCount(0);
  });
});
