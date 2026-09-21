const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const state = JSON.parse(require('fs').readFileSync('qa/storage-states/hr.json', 'utf8'));
  await ctx.addCookies(state.cookies);
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8100/candidates/1340/', { waitUntil: 'load' });
  const res = await new AxeBuilder({ page }).analyze();
  for (const v of res.violations) {
    console.log('==', v.id, v.impact);
    for (const n of v.nodes.slice(0, 3)) {
      console.log('  target:', n.target[0]);
      console.log('  html:', n.html.slice(0, 160));
      for (const f of n.any) console.log('  check:', f.id, JSON.stringify(f.data).slice(0, 200));
    }
  }
  await browser.close();
})();
