import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for Altrium Hiring Tracker automated test cases.
 *
 * Maps 1:1 to the manual test-case documents:
 *   - Sprint 02 Functional Features (Scorecards, Candidate Portal,
 *     Automated Emails, Pipeline Reporting, Job Closure)
 *   - Sprint 1 NFR (RBAC, pagination, retention, feedback validation, rounds)
 *
 * Requires the local Django dev server running at http://127.0.0.1:8100
 * (start with: .venv/bin/python manage.py runserver 127.0.0.1:8100 --noreload)
 */
export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  /* Tests share the DB and create data — run serially for stability. */
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 60 * 1000,
  expect: {
    timeout: 10_000,
  },
  use: {
    /* Local Django dev server */
    baseURL: 'http://127.0.0.1:8100',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  /* Auto-start Django dev server so VSCode Test Explorer runs don't hit
     ERR_CONNECTION_REFUSED. Reuses the already-running server if present. */
  webServer: {
    command: '.venv/bin/python manage.py runserver 127.0.0.1:8100 --noreload',
    url: 'http://127.0.0.1:8100/login/',
    reuseExistingServer: true,
    timeout: 120_000,
    cwd: '/home/ctum/PPPM',
  },
});
