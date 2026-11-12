// Live proof: the All RFQs screen (stage 9 with no RFQ open) in real Chrome. usage: node portfolio_live.cjs [--store]   (--store presses "Store the values now" and waits for the job)
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/portfolio'; fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1400 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.waitForTimeout(2000);
  await p.getByRole('button', { name: 'Reports & Analytics', exact: true }).first().click();
  await p.getByText('All RFQs', { exact: true }).first().waitFor({ timeout: 60000 });
  await p.waitForTimeout(2500);
  const text = async () => (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  let s = await text();
  console.log('PORTFOLIO:', s.slice(s.indexOf('All RFQs'), s.indexOf('All RFQs') + 900));
  await p.screenshot({ path: `${OUT}/01-portfolio.png` });
  if (process.argv.includes('--store')) {
    const btn = p.getByRole('button', { name: /Store the values now/i });
    if (await btn.count()) {
      await btn.click();
      const t0 = Date.now();
      while (Date.now() - t0 < 3 * 3600 * 1000) {
        await p.waitForTimeout(15000);
        s = await text();
        const m = s.match(/Storing the values in older reports: (\d+) of (\d+) done/);
        console.log(new Date().toISOString().slice(11, 19), m ? `${m[1]} of ${m[2]}` : 'not running');
        if (!m) break;
      }
      await p.waitForTimeout(3000);
      await p.screenshot({ path: `${OUT}/02-portfolio-after-store.png` });
      s = await text();
      console.log('AFTER:', s.slice(s.indexOf('All RFQs'), s.indexOf('All RFQs') + 700));
    }
  }
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
