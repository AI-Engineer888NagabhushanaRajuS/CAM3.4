// Real check of the Superset embed in the app: open RFQ-000062, press the Superset toggle, read what the panel shows. Screenshot kept.
const { createRequire } = require('module');
const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  const s = p.getByPlaceholder(/Search by RFQ ID/i).first(); await s.fill('RFQ-000062'); await s.press('Enter');
  await p.waitForTimeout(15000);
  const toggle = p.getByRole('button', { name: /Show Superset|Superset/i }).first();
  console.log('toggle found:', await toggle.count());
  await toggle.click().catch((e) => console.log('click failed', e.message.slice(0, 120)));
  await p.waitForTimeout(20000);
  const frames = p.frames().map((f) => f.url()).filter((u) => u && !u.startsWith('about:'));
  console.log('frames:', JSON.stringify(frames.slice(0, 4)));
  const msg = await p.evaluate(() => [...document.querySelectorAll('p')].map((e) => e.textContent).filter((t) => /Superset|optional|not set up|dashboard/i.test(t)).slice(0, 3));
  console.log('panel text:', JSON.stringify(msg));
  await p.screenshot({ path: path.join(__dirname, 'screenshots', 'superset-embed.png') });
  await b.close();
})();
