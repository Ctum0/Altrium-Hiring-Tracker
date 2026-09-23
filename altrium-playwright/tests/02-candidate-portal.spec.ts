import { test, expect } from '@playwright/test';

test.describe('Candidate Application Portal', () => {
  test('3. Public Open Positions page lists active jobs and processes candidate application', async ({ page }) => {
    await page.goto('/careers/');
    await expect(page.getByRole('heading', { name: /Open Positions|Careers/i })).toBeVisible();

    const applyLink = page.locator('a[href*="/candidates/apply/"]').first();
    await expect(applyLink).toBeVisible();
    await applyLink.click();
    await page.waitForURL(/\/candidates\/apply\/\d+\//);

    await page.locator('input[name="full_name"], #id_full_name').fill('Portal Applicant');
    await page.locator('input[name="email"], #id_email').fill(`portal_app_${Date.now()}@example.com`);

    const pdfBuffer = Buffer.from(
      '%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n' +
      '3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n' +
      '4 0 obj\n<< /Length 55 >>\nstream\nBT /F1 12 Tf 100 700 Td (Candidate CV Python Django) Tj ET\nendstream\nendobj\n' +
      'xref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000216 00000 n \n' +
      'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n321\n%%EOF'
    );

    await page.locator('input[type="file"]').setInputFiles({
      name: 'resume.pdf',
      mimeType: 'application/pdf',
      buffer: pdfBuffer,
    });

    const consentBox = page.getByRole('checkbox');
    if (await consentBox.isVisible().catch(() => false)) {
      await consentBox.check();
    }

    await page.getByRole('button', { name: /Submit application|Apply/i }).click();
    await expect(page.getByText(/Thank you|submitted|received/i).first()).toBeVisible({ timeout: 15_000 });
  });
});

