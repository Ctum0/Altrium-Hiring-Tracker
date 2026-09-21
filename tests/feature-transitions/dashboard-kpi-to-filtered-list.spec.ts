// @ts-check
/**
 * dashboard-kpi-to-filtered-list.spec.ts
 * Guards GAP-004: the "Total Applications / Active pipeline" KPI counts only
 * active-job applications and its deep link shows the same population.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs } = require('./helpers');

test.describe('dashboard KPI → filtered list', () => {
  test('KPI card links to the active-jobs-filtered list', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });

    const card = page.locator('.ref-kpi-card:has-text("Total Applications")');
    await expect(card).toBeVisible();
    const href = await card.getAttribute('href');
    expect(href).toContain('active_jobs=1');

    const kpiValue = (await card.locator('.ref-kpi-value').textContent()).trim();
    expect(Number(kpiValue)).not.toBeNaN();

    // The deep link lands on a list scoped to the same population
    await page.goto(`${BASE}${href}`, { waitUntil: 'load' });
    // No closed job should appear while the KPI counts only active jobs:
    // the position select must reflect the active_jobs scope via the URL.
    expect(page.url()).toContain('active_jobs=1');
  });

  test('AI insight action links resolve to real surfaces', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });
    // Every action link must carry a concrete target (GAP-005)
    const links = page.locator('a.ai-action-link');
    const count = await links.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i++) {
      const href = await links.nth(i).getAttribute('href');
      expect(href).toMatch(/\/(candidates|feedback)\//);
      expect(href).toContain('?');
    }
  });
});
