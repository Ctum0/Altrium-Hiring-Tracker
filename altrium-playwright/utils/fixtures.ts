import { Page, Locator } from '@playwright/test';

/**
 * Shared helpers to create test data through the UI/API before running
 * test assertions. Tests stay self-contained: they build the exact
 * fixture the DOCX test case describes.
 */
import { login } from '../utils/auth';

/**
 * Create a fresh job (as HR) and return its id from the rounds-setup URL.
 */
export async function createJob(
  page: Page,
  title: string,
): Promise<number> {
  await login(page, 'hr');
  await page.goto('/jobs/create/');
  await page.waitForLoadState('domcontentloaded');
  await page.getByLabel('Title').fill(title);
  await page.getByLabel('Description').fill('Automated test job for scorecard flows.');
  await page.getByLabel('Required skills').fill('Python, Django, Testing');
  await page.getByRole('button', { name: 'Create job' }).click();
  // Redirects to /jobs/<pk>/rounds-setup/
  await page.waitForURL(/\/rounds-setup\//);
  const url = page.url();
  const match = url.match(/\/jobs\/(\d+)\//);
  if (!match) throw new Error(`Could not parse job id from ${url}`);
  return Number(match[1]);
}

/**
 * Create a candidate by paste-import (as HR) and return the candidate id
 * parsed from the resulting detail page.
 */
export async function importCandidate(
  page: Page,
  jobId: number,
  fullName: string,
  email: string,
): Promise<number> {
  await page.goto('/candidates/import/');
  await page.locator('select[name="job"]').selectOption(String(jobId));
  await page.locator('textarea[name="profile_text"]').fill(
    `${fullName}\n${email}\nSkills: Python, Django, Testing\n` +
      'Experienced engineer with strong production background and testing focus.',
  );
  await page.getByRole('button', { name: 'Import candidate' }).click();
  await page.waitForURL(/\/candidates\/\d+\//);
  const match = page.url().match(/\/candidates\/(\d+)\//);
  if (!match) throw new Error(`Could not parse candidate id from ${page.url()}`);
  return Number(match[1]);
}

/**
 * Declare a weekly availability window for the interviewer (as the
 * interviewer). The assign gate (AssignApplicationView) blocks
 * assignment for interviewers with no availability on file, so scorecard
 * flows must ensure iv_demo has a window before assigning.
 */
export async function ensureInterviewerAvailability(
  page: Page,
  role: 'interviewer' = 'interviewer',
): Promise<void> {
  await login(page, role);
  await page.goto('/my-availability/');
  await page.waitForLoadState('domcontentloaded');
  // Skip if a window already exists (idempotent across tests)
  if (await page.getByRole('button', { name: 'Remove' }).first().isVisible().catch(() => false)) {
    return;
  }
  await page.locator('#id_weekday').selectOption({ index: 1 }); // Monday
  await page.locator('#id_start_time').fill('09:00');
  await page.locator('#id_end_time').fill('17:00');
  await page.getByRole('button', { name: 'Add window' }).click();
  await page.waitForLoadState('networkidle');
}

/**
 * Assign an application to an interviewer (as HR) via the candidate
 * detail page's assign form.
 */
export async function assignInterviewer(
  page: Page,
  candidateId: number,
  applicationIndex: number,
  interviewerLabel: string,
): Promise<void> {
  await page.goto(`/candidates/${candidateId}/`);
  await page.waitForLoadState('domcontentloaded');
  const card = page.locator('.app-card').nth(applicationIndex);
  await card.waitFor({ state: 'visible', timeout: 30_000 });
  // Expand the collapsed row unless already open
  const details = card.locator('details.app-disclosure');
  if (!(await details.getAttribute('open').catch(() => null))) {
    await card.locator('summary').click();
  }
  // Option labels are dynamic, e.g. "Ivan (no availability yet) (1 active)" —
  // match on the first token of the requested name and select by value.
  const nameToken = interviewerLabel.split(/\s+/)[0];
  const select = card.locator('select[name="interviewer"]');
  const optionValue = await select
    .locator('option', { hasText: nameToken })
    .first()
    .getAttribute('value');
  if (!optionValue) {
    throw new Error(`No interviewer option matching "${interviewerLabel}"`);
  }
  await select.selectOption(optionValue);
  // Assign opens a two-click confirm dialog on first press.
  await card.getByRole('button', { name: 'Assign', exact: true }).click();
  const ok = page.locator('#confirm-ok');
  if (await ok.isVisible().catch(() => false)) {
    await ok.click();
  }
  await page.waitForLoadState('networkidle');
  // The assign gate (availability/eligibility/seniority) can silently
  // reject with an error message — fail fast with the real reason. A
  // success toast ("Assigned ... to ...") is not a rejection.
  const gateError = page.locator('.alert-error, [role="alert"]').first();
  if (await gateError.isVisible().catch(() => false)) {
    const text = (await gateError.textContent())?.trim() ?? '';
    if (!/Assigned .* to /i.test(text)) {
      throw new Error(`Assignment rejected: ${text}`);
    }
  }
}
