// @ts-check
/**
 * job-detail-round-reorder.spec.ts
 * Guards GAP-001: inline round reorder on job detail (HR-only), complete
 * transition: change order → save → persisted → visible in the table.
 *
 * KNOWN FLAKE: the first attempt intermittently asserts against a stale
 * render (always passes on retry; CI runs with retries=1). The underlying
 * fix is guarded deterministically by the Django test
 * tests.test_gap_regressions.Gap001RoundReorderOnJobDetailTest.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs } = require('./helpers');

test.describe('job detail → round reorder', () => {
  test('HR reorders a round and the new order persists', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });
    // find the E2E job via the jobs list
    await page.goto(`${BASE}/jobs/`, { waitUntil: 'load' });
    await page.locator('a:has-text("E2E Continuity Role")').first().click();
    await page.waitForLoadState('load');
    expect(page.url()).toMatch(/\/jobs\/\d+\//);

    const inputs = page.locator('input[name^="order_"][type="number"]');
    const count = await inputs.count();
    expect(count).toBeGreaterThanOrEqual(2);

    // Swap the first two rounds' orders in one save: every row's form
    // carries the full sequence (hidden inputs for the other rounds).
    const first = await inputs.nth(0).inputValue();
    const second = await inputs.nth(1).inputValue();
    await inputs.nth(0).fill(second);
    await inputs.nth(1).fill(first);
    const save = page.waitForResponse(
      r => r.url().includes('/rounds/reorder/') && r.request().method() === 'POST',
      { timeout: 15000 },
    );
    await page.locator('button:has-text("Save round order")').click();
    const resp = await save;
    expect(resp.status()).toBe(302);   // save persisted before we assert
    await page.waitForURL(/\/jobs\/\d+\//, { timeout: 15000 });
    await expect(page.locator('.alert')).toContainText('Round order updated');

    // Reload: the swap persisted. NOTE the table renders rounds sorted by
    // order, so after a successful swap the ROWS themselves exchange
    // positions — assert the (name, order) pairing, not row positions.
    await page.reload({ waitUntil: 'load' });
    await page.waitForTimeout(500);
    const rows = await page.locator('input[name^="order_"][type="number"]').evaluateAll(
      els => els.map(el => ({
        order: el.value,
        name: el.closest('tr').querySelector('td.strong').textContent.trim(),
      })),
    );
    const byName = Object.fromEntries(rows.map(r => [r.name, r.order]));
    expect(byName['Screening']).toBe(second);
    expect(byName['Interview']).toBe(first);
  });

  test('Management does not see reorder controls', async ({ page }) => {
    await loginAs(page, 'mgmt');
    await page.goto(`${BASE}/jobs/`, { waitUntil: 'load' });
    await page.locator('a:has-text("E2E Continuity Role")').first().click();
    await page.waitForLoadState('load');
    expect(await page.locator('input[name^="order_"]').count()).toBe(0);
  });
});
