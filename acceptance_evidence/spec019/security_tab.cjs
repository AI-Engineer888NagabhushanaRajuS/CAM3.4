const { createRequire } = require('module');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errs = [];
  p.on('pageerror', (e) => errs.push(String(e).slice(0, 120)));
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.getByRole('radiogroup', { name: 'Model provider' }).waitFor({ timeout: 20000 });
  await p.getByRole('button', { name: /settings/i }).first().click();
  const d = p.getByRole('dialog'); await d.waitFor({ timeout: 10000 });
  await d.getByRole('button', { name: /^Security$/ }).click();
  await p.waitForTimeout(3500);
  const text = (await d.innerText()).replace(/\s+/g, ' ');
  const i = text.indexOf('Security');
  console.log(text.slice(i, i + 1500));
  await p.screenshot({ path: 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/30-security-tab.png' });
  console.log('page errors:', JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
