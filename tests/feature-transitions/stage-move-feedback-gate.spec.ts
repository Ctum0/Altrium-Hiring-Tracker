// @ts-check
/**
 * stage-move-feedback-gate.spec.ts
 * Guards the core pipeline edge: terminal/round moves without feedback are
 * blocked (409), the toast explains why and PERSISTS (GAP-008), and the
 * select reverts to the candidate's actual round.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');

test.describe('stage move feedback gate', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('terminal move without feedback → modal → confirm → sticky toast + revert', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/candidates/${ids.candidate_pk}/`, { waitUntil: 'load' });

    const row = page.locator(`#app-row-${ids.app_pk}`);
    const select = row.locator('.stage-select');
    const currentRound = await select.evaluate(el =>
      el.options[el.selectedIndex].value,
    );

    // Fire the terminal move via the select (same path a user takes)
    await select.evaluate(el => {
      el.value = 'status:hired';
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const modal = page.locator('#confirm-modal');
    await expect(modal).toHaveAttribute('open', /true|^$/);
    await page.locator('#confirm-ok').click();

    // Sticky toast with the server's gate message (no auto-dismiss)
    const toast = page.locator('.toast');
    await expect(toast).toContainText('Feedback is required before making a final hiring decision.');
    // Still visible after 6s (GAP-008: no 5s auto-dismiss on errors)
    await page.waitForTimeout(6000);
    await expect(toast).toBeVisible();

    // Select reverted to the candidate's actual round
    const reverted = await select.inputValue();
    expect(reverted).toBe(currentRound);
  });
});
