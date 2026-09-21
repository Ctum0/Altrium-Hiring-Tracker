/**
 * Shared helpers for the feature-transition specs.
 *
 * Auth: programmatic login via the UI login form (works in CI without
 * pre-generated storage states). Each suite logs in with the e2e_ accounts
 * created by qa/scripts/e2e_seed.py.
 */
// @ts-check
const BASE = process.env.QA_BASE_URL || 'http://127.0.0.1:8100';

const USERS = {
  hr: { username: 'e2e_hr', password: 'e2epass123' },
  iv: { username: 'e2e_iv', password: 'e2epass123' },
  mgmt: { username: 'e2e_mgmt', password: 'e2epass123' },
};

/** Log in through the real login form (tests the auth edge itself). */
async function loginAs(page, role) {
  const user = USERS[role];
  await page.goto(`${BASE}/login/`, { waitUntil: 'load' });
  await page.fill('#id_username', user.username);
  await page.fill('#id_password', user.password);
  await page.click('button[type="submit"][class*="btn-auth-cta"]');
  await page.waitForLoadState('load');
  return page.url();
}

/** Read the E2E seed ids from the JSON produced by e2e_seed.py --json. */
async function seedIds() {
  const { execSync } = require('node:child_process');
  const out = execSync(
    '.venv/bin/python qa/scripts/e2e_seed.py --json',
    { cwd: process.cwd(), encoding: 'utf8' },
  );
  return JSON.parse(out);
}

module.exports = { BASE, USERS, loginAs, seedIds };
