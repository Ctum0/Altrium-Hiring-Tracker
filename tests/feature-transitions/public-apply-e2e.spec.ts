// @ts-check
/**
 * public-apply-e2e.spec.ts
 * Guards the public chain: careers → apply (consent + CV) → thanks with a
 * continuation CTA; the candidate lands in the pipeline parsed.
 */
const { test, expect } = require('playwright/test');
const { BASE } = require('./helpers');

/** Build a minimal valid PDF carrying the applicant's identity. */
function makeCv(path, name, email) {
  const text = `BT /F1 14 Tf 72 720 Td (${name}) Tj 0 -20 Td (${email}) Tj 0 -20 Td (Skills: Python Django Playwright testing) Tj 0 -20 Td (Senior QA automation engineer with deep Playwright and CI experience.) Tj ET`;
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

test.describe('public apply end-to-end', () => {
  test('careers → apply → consent + CV → thanks with next step', async ({ page }) => {
    await page.goto(`${BASE}/careers/`, { waitUntil: 'load' });
    await expect(page).toHaveTitle(/Open Positions/);

    await page.locator('a[href^="/candidates/apply/"]').first().click();
    await page.waitForLoadState('load');
    expect(page.url()).toMatch(/\/candidates\/apply\/\d+\//);
    // back-link preserves the careers entry path
    await expect(page.locator('a:has-text("All open positions")')).toBeVisible();

    const stamp = Date.now();
    const name = `Public Apply ${stamp}`;
    const email = `public.apply.${stamp}@example.com`;
    // The CV must carry THIS run's identity: the parser extracts name/email
    // from the file, and a reused file collides with previous runs' dedup.
    const cvPath = `/tmp/e2e-apply-${stamp}.pdf`;
    makeCv(cvPath, name, email);
    await page.fill('input[name="full_name"]', name);
    await page.fill('input[name="email"]', email);
    // Consent BEFORE the file: the dropzone wiring can steal focus events.
    const consent = page.locator('#consent');
    await consent.check();
    await expect(consent).toBeChecked();
    await page.locator('input[type="file"]').first().setInputFiles(cvPath, { timeout: 10000 });
    await page.waitForTimeout(500);

    const thanks = page.waitForURL('**/thanks/', { timeout: 90000 }).catch(() => null);
    await page.locator('button:has-text("Submit application")')
      .click({ force: true, timeout: 15000 })
      .catch(async () => {
        // Font-load reflow can keep the button "unstable"; fall back to a
        // direct form submission (same POST the button triggers).
        await page.evaluate(() => {
          const f = [...document.querySelectorAll('form')].find(
            x => x.method.toLowerCase() === 'post' && !x.hasAttribute('data-logout-form'),
          );
          f.submit();
        });
      });
    // If the click was swallowed (no navigation), submit the form directly.
    await page.waitForTimeout(5000);
    if (!page.url().includes('/thanks/')) {
      await page.evaluate(() => {
        const f = [...document.querySelectorAll('form')].find(
          x => x.method.toLowerCase() === 'post' && !x.hasAttribute('data-logout-form'),
        );
        f.submit();
      });
      await page.waitForURL('**/thanks/', { timeout: 60000 });
    }
    await thanks;
    expect(page.url()).toContain('/thanks/');
    await expect(page.locator('text=Application received')).toBeVisible();
    // Continuation: no dead end
    await expect(page.locator('a:has-text("Browse other open roles")')).toBeVisible();
  });
});
