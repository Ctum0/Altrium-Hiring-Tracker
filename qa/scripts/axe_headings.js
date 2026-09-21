const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
(async () => {
  const browser = await chromium.launch({ headless: true });
  // candidate detail
  let ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  let state = JSON.parse(require('fs').readFileSync('qa/storage-states/hr.json', 'utf8'));
  await ctx.addCookies(state.cookies);
  let page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8100/candidates/1340/', { waitUntil: 'load' });
  let res = await new AxeBuilder({ page }).analyze();
  for (const v of res.violations) {
    console.log('== detail:', v.id);
    for (const n of v.nodes) console.log('  ', n.html.slice(0, 100), '| preceding:', JSON.stringify(n.any[0]?.data));
  }
  await ctx.close();
  // IV dashboard
  ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  state = JSON.parse(require('fs').readFileSync('qa/storage-states/iv.json', 'utf8'));
  await ctx.addCookies(state.cookies);
  page = await ctx.newPage();
  await page.goto('http://127.0.0.1:8100/interviewer-dashboard/', { waitUntil: 'load' });
  res = await new AxeBuilder({ page }).analyze();
  for (const v of res.violations) {
    console.log('== iv:', v.id);
    for (const n of v.nodes) console.log('  ', n.html.slice(0, 100));
  }
  await ctx.close();
  await browser.close();
})();
