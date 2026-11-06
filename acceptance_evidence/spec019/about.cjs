const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  console.log('tab title:', await p.title());
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 15000 });
  await p.locator('button:has(svg)').filter({ has: p.locator('[aria-label*="ettings" i]') }).first().click().catch(() => {});
  // gear icon top right
  await p.getByRole('button', { name: /settings/i }).first().click().catch(async () => { await p.locator('header button').nth(1).click(); });
  const d = p.getByRole('dialog'); await d.waitFor({ timeout: 10000 });
  await d.getByRole('button', { name: /^About$/ }).click();
  await p.waitForTimeout(1200);
  const text = (await d.innerText()).replace(/\s+/g, ' ');
  console.log('About:', text.slice(text.indexOf('About') , text.indexOf('About') + 700));
  console.log('contains 3.2:', /\b3\.2\b/.test(text), '| contains 3.4:', /\b3\.4\b/.test(text), '| SRIM/BuLLMQuote:', /SRIM|BuLLMQuote/i.test(text));
  await p.screenshot({ path: 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/26-about.png' });
  await b.close();
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
