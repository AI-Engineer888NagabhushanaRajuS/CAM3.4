// What the left pane SAYS for a finished RFQ, stage by stage, next to what the pipeline really did (router log / DB). Real Chrome.
// usage: node leftpane_truth.cjs RFQ-000024
const { createRequire } = require('module');
const fs = require('fs');
const req = createRequire('C:/CAM[3.4]-RFQ_centum/CAM-Source/accomplish-ui/packages/agent-core/mcp-tools/dev-browser/package.json');
const { chromium } = req('playwright');
const RFQ = process.argv[2] || 'RFQ-000024';
const OUT = 'C:/CAM[3.4]-RFQ_centum/acceptance_evidence/spec019/leftpane'; fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const b = await chromium.launch({ headless: true, channel: 'chrome' });
  const p = await (await b.newContext({ viewport: { width: 1440, height: 1100 } })).newPage();
  await p.goto('http://localhost:5181/', { waitUntil: 'networkidle' });
  const t = p.getByRole('button', { name: /Sign in as Tester/i }); if (await t.count()) { await t.click(); await p.waitForLoadState('networkidle'); }
  await p.waitForSelector('[data-testid="task-input-textarea"]', { timeout: 30000 });
  await p.fill('[data-testid="task-input-textarea"]', `open ${RFQ}`); await p.click('[data-testid="task-input-submit"]'); await p.waitForTimeout(6000);
  await p.getByRole('button', { name: new RegExp(`Open ${RFQ}`) }).first().click(); await p.waitForTimeout(5000);
  const rows = await p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => { const s = d.querySelectorAll('button')[1]; return [s?.querySelector('span span:nth-child(1)')?.textContent, s?.querySelector('span span:nth-child(2)')?.textContent]; }));
  console.log(JSON.stringify(rows));
  await p.screenshot({ path: `${OUT}/${RFQ}.png` });
  // The Reports & Analytics screen of a finished RFQ (read from its workbook) and the left pane statuses, expanded.
  await p.waitForTimeout(6000);
  const text = (await p.locator('body').innerText()).replace(/\s+/g, ' ');
  const at = text.indexOf('Reports & Analytics');
  console.log('DASHBOARD:', at >= 0 ? text.slice(at, at + 900) : '(not on screen) ' + text.slice(0, 200));
  await p.screenshot({ path: `${OUT}/${RFQ}-dashboard.png` });
  await p.mouse.click(28, 72); await p.waitForTimeout(1500);   // the round arrow at the top of the collapsed left pane
  const rows2 = await p.evaluate(() => [...document.querySelectorAll('[role="tree"] > div')].map((d) => d.innerText.replace(/\s+/g, ' ').slice(0, 90)));
  console.log('LEFT PANE:', JSON.stringify(rows2));
  await p.screenshot({ path: `${OUT}/${RFQ}-leftpane.png` });
  await b.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
