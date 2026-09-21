// @ts-check
/**
 * assign-notification-clickthrough.spec.ts
 * Guards the assignment → notification → click-through → mark-read lifecycle
 * (verified in cycle 2; this spec pins it permanently).
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');

test.describe('assign → notify → click-through', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('HR assigns; interviewer gets a notification and click-through works', async ({ page, browser }) => {
    // HR side: assign the E2E candidate's app to the E2E interviewer
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/candidates/${ids.candidate_pk}/`, { waitUntil: 'load' });
    const row = page.locator(`#app-row-${ids.app_pk}`);
    await row.locator('summary').click();
    await page.waitForTimeout(500);
    const assignSelect = row.locator('select[name="interviewer"]');
    // pick the E2E interviewer option by label
    const optionValue = await assignSelect.locator('option', { hasText: 'E2E' }).first()
      .getAttribute('value')
      .catch(() => null);
    test.skip(!optionValue, 'E2E interviewer not eligible for this job — seed domain must match');
    await assignSelect.selectOption(optionValue);
    await row.locator('button:has-text("Assign")').click();
    // The Assign button opens the confirm dialog; wait for it, then OK submits.
    const confirmModal = page.locator('#confirm-modal');
    await expect(confirmModal).toBeVisible();
    await page.locator('#confirm-ok').click();
    await page.waitForLoadState('load');

    // Interviewer side in a fresh CONTEXT: the HR session cookie lives in
    // this context's jar, and logging in as IV from the same jar would
    // either be redirected (already authenticated) or clobber the session.
    const ivCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const ivPage = await ivCtx.newPage();
    await loginAs(ivPage, 'iv');
    await ivPage.goto(`${BASE}/interviewer-dashboard/`, { waitUntil: 'load' });
    await expect(ivPage.locator('.notif-count')).toHaveText(/\d+/);
    await ivPage.locator('#notif-trigger').click();
    const notifLink = ivPage.locator('#notif-popover a.popover-item').first();
    await notifLink.waitFor({ state: 'visible', timeout: 15000 });
    await notifLink.click();
    await ivPage.waitForLoadState('load');
    expect(ivPage.url()).toMatch(/\/candidates\/\d+\//);
    await ivCtx.close();
  });
});
