// Screenshot of the Superset iframe inside the app's Reports screen (RFQ-000062). Waits for the chart to draw.
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
  await p.waitForTimeout(12000);
  await p.getByRole('button', { name: /Show Superset|Superset/i }).first().click();
  await p.waitForTimeout(25000);
  const frame = p.frames().find((f) => f.url().includes('8088/embedded'));
  if (frame) { await frame.waitForLoadState('networkidle').catch(() => {}); console.log('frame text:', (await frame.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300)); }
  const box = await p.locator('iframe[src*="8088/embedded"]').first().boundingBox().catch(() => null);
  if (box) { await p.evaluate((y) => window.scrollBy(0, y), box.y - 300); await p.waitForTimeout(1000); }
  await p.screenshot({ path: path.join(__dirname, 'screenshots', 'superset-frame.png') });
  await b.close();
})();
