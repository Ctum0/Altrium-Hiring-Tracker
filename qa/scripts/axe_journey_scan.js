const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  async function scan(ctx, url, label) {
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'load', timeout: 20000 });
    const res = await new AxeBuilder({ page }).analyze();
    results.push({ label, violations: res.violations.map(v => ({
      id: v.id, impact: v.impact, nodes: v.nodes.length,
      sample: (v.nodes[0]?.target?.[0] || '').slice(0, 80),
    })) });
    await page.close();
  }
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const state = JSON.parse(fs.readFileSync('qa/storage-states/hr.json', 'utf8'));
    await ctx.addCookies(state.cookies);
    await scan(ctx, 'http://127.0.0.1:8100/hr-dashboard/', 'HR Dashboard');
    await scan(ctx, 'http://127.0.0.1:8100/candidates/1340/', 'HR Candidate Detail');
    await scan(ctx, 'http://127.0.0.1:8100/jobs/96/board/', 'HR Kanban Board');
    await ctx.close();
  }
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const state = JSON.parse(fs.readFileSync('qa/storage-states/iv.json', 'utf8'));
    await ctx.addCookies(state.cookies);
    await scan(ctx, 'http://127.0.0.1:8100/interviewer-dashboard/', 'IV Dashboard');
    await ctx.close();
  }
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await scan(ctx, 'http://127.0.0.1:8100/careers/', 'Public Careers');
    await ctx.close();
  }
  for (const r of results) {
    console.log(`== ${r.label} ==`);
    if (!r.violations.length) console.log('  no violations');
    for (const v of r.violations) console.log(`  ${String(v.impact).padEnd(8)} ${v.id} x${v.nodes}  ${v.sample || ''}`);
  }
  await browser.close();
})();
