import { Page, expect } from '@playwright/test';

/**
 * Role credentials for Altrium Hiring Tracker (seeded by seed_users).
 */
export const USERS = {
  hr: { username: 'hr_demo', password: 'testpass123', fullName: 'Hana' },
  interviewer: { username: 'iv_demo', password: 'testpass123', fullName: 'Ivan' },
  management: { username: 'mgmt_demo', password: 'testpass123', fullName: 'Mia' },
} as const;

export type Role = keyof typeof USERS;

/**
 * Log in through the Django login form as the REQUESTED role.
 *
 * The browser context may already hold a session for a DIFFERENT role
 * (helpers log in/out across roles within one test). A bare /login/ visit
 * then redirects to the dashboard of the stale user — logging in as the
 * wrong role silently breaks every role-gated assertion.
 *
 * Strategy: read the sidebar identity (`.user-name`); if it isn't the
 * requested user, log out via the user menu (or clear cookies) and do a
 * fresh form login.
 */
export async function login(page: Page, role: Role): Promise<void> {
  const { username, password, fullName } = USERS[role];
  await page.goto('/', { waitUntil: 'domcontentloaded' });

  // Already the right user?
  const identity = page.locator('.user-name').first();
  const current = await identity
    .textContent({ timeout: 5_000 })
    .then((t) => t?.trim() ?? '')
    .catch(() => '');

  if (current.startsWith(fullName)) return;

  // Wrong (or no) user — clear the session and log in fresh.
  await page.context().clearCookies();
  await page.goto('/login/', { waitUntil: 'domcontentloaded' });

  const usernameInput = page.getByLabel('Username');
  await usernameInput.waitFor({ state: 'visible', timeout: 30_000 });
  await usernameInput.fill(username);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(/dashboard/, { timeout: 30_000 });

  // Verify the right user is actually signed in.
  await expect
    .poll(async () => (await identity.textContent({ timeout: 5_000 }).catch(() => '')) ?? '')
    .toContain(fullName);
}


/** Log out via the sidebar user menu (details/summary). */
export async function logout(page: Page): Promise<void> {
  // The user menu is a <details>/<summary> — the trigger is a summary with
  // aria-label "Open user menu", which is NOT exposed as a button role.
  await page.locator('summary[aria-label="Open user menu"]').click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await page.waitForURL(/login/, { timeout: 15_000 });
}
