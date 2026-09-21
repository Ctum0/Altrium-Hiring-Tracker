// @ts-check
/**
 * upload-to-filtered-list.spec.ts
 * Guards GAP-006: upload success lands on the job-filtered candidates list
 * with the toast intact.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');
const { execSync } = require('node:child_process');

/** Build a minimal valid PDF for the parse pipeline. */
function makeCv(path, name, email, skills) {
  const text = `BT /F1 14 Tf 72 720 Td (${name}) Tj 0 -20 Td (${email}) Tj 0 -20 Td (Skills: ${skills}) Tj 0 -20 Td (Experienced engineer with production experience.) Tj ET`;
  const pdf = `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length ${text.length} >> stream
${text}
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Root 1 0 R >>
%%EOF`;
  require('node:fs').writeFileSync(path, pdf, 'binary');
}

test.describe('upload → filtered list', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('upload lands on the job-filtered list with a success toast', async ({ page }) => {
    await loginAs(page, 'hr');
    const cvPath = '/tmp/e2e-upload-cv.pdf';
    makeCv(cvPath, 'Uploady McTest', `uploady.${Date.now()}@example.com`, 'Python Django Playwright');

    await page.goto(`${BASE}/candidates/upload/?job=${ids.job_pk}`, { waitUntil: 'load' });
    // Position preselected from the ?job= param (state handoff at entry)
    await expect(page.locator('#job')).toHaveValue(String(ids.job_pk));
    await page.locator('input[type="file"]').first().setInputFiles(cvPath, { timeout: 10000 });
    await page.waitForTimeout(500);

    await page.locator('#upload-form').evaluate(f => f.requestSubmit());
    await page.waitForURL('**/candidates/**', { timeout: 60000 });
    await page.waitForTimeout(2500);

    // GAP-006: URL carries the job filter and the select reflects it
    expect(page.url()).toContain(`job=${ids.job_pk}`);
    await expect(page.locator('select[name="job"]')).toHaveValue(String(ids.job_pk));
    // Toast names the job
    await expect(page.locator('.alert').first()).toContainText('linked to');
  });
});
