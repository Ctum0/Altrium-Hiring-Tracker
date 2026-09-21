// @ts-check
/**
 * login-to-dashboard.spec.ts
 * Guards the auth entry edges: role-based redirects and the lockout message.
 * (GAP-007 verified the cooloff duration; this spec pins the redirect map.)
 */
const { test, expect } = require('playwright/test');
const { BASE, USERS, loginAs } = require('./helpers');

test.describe('login → dashboard role routing', () => {
  test('HR lands on the HR dashboard', async ({ page }) => {
    const url = await loginAs(page, 'hr');
    expect(url).toContain('/hr-dashboard/');
    await expect(page).toHaveTitle(/HR Dashboard/);
  });

  test('Interviewer lands on the interviewer dashboard', async ({ page }) => {
    const url = await loginAs(page, 'iv');
    expect(url).toContain('/interviewer-dashboard/');
  });

  test('Management lands on the (read-only) HR dashboard', async ({ page }) => {
    const url = await loginAs(page, 'mgmt');
    expect(url).toContain('/hr-dashboard/');
  });

  test('wrong password shows the error alert and stays on login', async ({ page }) => {
    await page.goto(`${BASE}/login/`, { waitUntil: 'load' });
    await page.fill('#id_username', USERS.hr.username);
    await page.fill('#id_password', 'definitely-wrong');
    await page.click('button[type="submit"], .btn-auth-cta');
    await page.waitForLoadState('load');
    expect(page.url()).toContain('/login/');
    await expect(page.locator('.alert-error')).toContainText('Incorrect username or password');
  });

  test('unauthenticated access redirects to login', async ({ page }) => {
    await page.goto(`${BASE}/hr-dashboard/`, { waitUntil: 'load' });
    expect(page.url()).toContain('/login/');
  });
});
