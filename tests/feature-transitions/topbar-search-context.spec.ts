// @ts-check
/**
 * topbar-search-context.spec.ts
 * Guards 1.2c: the topbar search box mirrors the page's active search term,
 * surviving detail → back navigation.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');

test.describe('topbar search context preservation', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('search → detail → back keeps the term in both boxes', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });
    await page.fill('#topbar-search-input', 'E2E');
    await page.press('#topbar-search-input', 'Enter');
    await page.waitForLoadState('load');
    expect(page.url()).toContain('q=E2E');

    await page.locator('tbody tr a').first().click();
    await page.waitForLoadState('load');
    await page.goBack();
    await page.waitForLoadState('load');

    await expect(page.locator('#topbar-search-input')).toHaveValue('E2E');
    // page-level filter also retains it
    const pageFilter = await page.locator('input[name="q"]').nth(1).inputValue();
    expect(pageFilter).toBe('E2E');
  });
});
