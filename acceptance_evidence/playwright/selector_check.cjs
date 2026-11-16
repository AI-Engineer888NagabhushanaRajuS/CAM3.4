// Opens the composer's model dropdown and reads the OpenRouter sub-menu. Real Chrome, real daemon.
const { createRequire } = require('module');
const path = require('path');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForTimeout(4000);
  const trigger = p.locator('button').filter({ hasText: /Qwen|Select model|Local|OpenRouter|model/i }).last();
  await trigger.click().catch((e) => console.log('trigger click failed', e.message.slice(0, 120)));
  await p.waitForTimeout(1500);
  const or = p.getByRole('menuitem').filter({ hasText: /OpenRouter/i }).first();
  if (await or.count()) { await or.hover(); await p.waitForTimeout(2500); }
  const items = await p.evaluate(() => [...document.querySelectorAll('[role="menuitem"]')].map((x) => x.textContent.trim()).filter(Boolean).slice(0, 12));
  console.log('menu:', JSON.stringify(items));
  await p.screenshot({ path: path.join(__dirname, 'screenshots', 'model-selector.png') });
  await b.close();
})();
