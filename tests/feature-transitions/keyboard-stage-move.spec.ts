// @ts-check
/**
 * keyboard-stage-move.spec.ts
 * Guards 1.2a: the Kanban board's keyboard move path — Enter on a focused
 * card opens the destination menu; choosing a column performs the same move
 * as a drag; focus returns to the card.
 */
const { test, expect } = require('playwright/test');
const { BASE, loginAs, seedIds } = require('./helpers');

test.describe('kanban keyboard move', () => {
  let ids;
  test.beforeAll(async () => {
    ids = await seedIds();
  });

  test('Enter opens the destination menu; move lands in the chosen column', async ({ page }) => {
    await loginAs(page, 'hr');
    await page.goto(`${BASE}/jobs/${ids.job_pk}/board/`, { waitUntil: 'load' });

    const card = page.locator(`#board-card-${ids.app_pk}`);
    await expect(card).toBeVisible();
    expect(await card.getAttribute('draggable')).toBe('true');

    // Keyboard: focus + Enter
    await card.focus();
    await page.keyboard.press('Enter');
    const dialog = page.locator('dialog.kanban-kb-menu');
    await expect(dialog).toBeVisible();

    // Current column is excluded from the menu
    const options = await page.locator('.kanban-kb-option').allTextContents();
    expect(options).not.toContain('Screening');
    expect(options).toContain('Unrouted');

    // The seeded app has no feedback on its round, so round-to-round moves
    // are gated (by design). Unrouting is not gated: move there first.
    await page.locator('.kanban-kb-option:has-text("Unrouted")').click();
    await page.waitForTimeout(1500);
    let col = await card.evaluate(el => el.closest('.kanban-column-body').dataset.stage);
    expect(col).toBe('unrouted');

    // Focus restored to the card (continuation)
    expect(await card.evaluate(el => document.activeElement === el)).toBe(true);

    // Re-route to Screening via the keyboard (allowed: no round being left)
    await card.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(400);
    await page.locator('.kanban-kb-option:has-text("Screening")').click();
    await page.waitForTimeout(1500);
    col = await card.evaluate(el => el.closest('.kanban-column-body').dataset.stage);
    expect(col).toBe('round:' + (await roundId(page, 'Screening')));
  });

  async function roundId(page, name) {
    return page.evaluate(n => {
      const bodies = [...document.querySelectorAll('.kanban-column-body[data-stage]')];
      const body = bodies.find(b =>
        b.closest('.kanban-column').querySelector('h3').textContent.trim() === n,
      );
      return body.dataset.stage.replace('round:', '');
    }, name);
  }
});
